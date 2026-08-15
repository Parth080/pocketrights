"""Command line for the corpus fetcher.

    uv run pr-corpus plan
    uv run pr-corpus plan --domain consumer
    uv run pr-corpus fetch --domain consumer
    uv run pr-corpus fetch --source cpa2019
    uv run pr-corpus status
"""

from __future__ import annotations

import argparse
import sys

from .batch import BatchIngester
from .fetcher import CorpusFetcher
from .ingest import CorpusIngester
from .provenance import Manifest, list_snapshots, manifest_path
from .registry import default_registry, find_repo_root


def _plan(args) -> int:
    with CorpusFetcher() as f:
        plan = f.plan(args.domain)
    for label, ids in plan.items():
        print(f"\n{label.upper()} ({len(ids)})")
        for i in ids:
            print(f"  {i}")
    if plan["blocked"]:
        print("\nBlocked sources are gated on an unresolved determination "
              "(contracts/sources.yaml).")
    if plan["no_url"]:
        print("\nSources without a URL cannot be fetched until one is recorded. "
              "That is deliberate — a guessed URL is worse than none.")
    return 0


def _fetch(args) -> int:
    reg = default_registry()
    ids = [args.source] if args.source else [
        s.id for s in reg.fetchable(domain=args.domain, max_priority=args.max_priority)
    ]
    if not ids:
        print("nothing to fetch")
        return 0

    failures = 0
    with CorpusFetcher(snapshot=args.snapshot) as f:
        print(f"snapshot {f.snapshot} · {len(ids)} source(s) · "
              f"{reg.policy.rate_limit_rps} req/s\n")
        for sid in ids:
            result = f.fetch_source(sid, force=args.force)
            r = result.record
            if r.ok:
                note = " (already present)" if result.already_present else ""
                print(f"  ok       {sid:34} {r.size_bytes:>9,}B  {r.sha256[:12]}{note}")
            else:
                failures += 1
                print(f"  {r.status:8} {sid:34} {r.error}")
    print(f"\n{len(ids) - failures}/{len(ids)} succeeded")
    return 1 if failures else 0


def _ingest(args) -> int:
    from pathlib import Path

    ing = CorpusIngester(snapshot=args.snapshot)
    try:
        result = ing.ingest(
            args.source,
            Path(args.file),
            source_url=args.url,
            effective_from=args.effective_from,
            notes=args.notes,
            force=args.force,
        )
    except (PermissionError, FileExistsError, FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}")
        return 1

    r = result.record
    verb = "replaced" if result.replaced else "ingested"
    print(f"{verb} {r.source_id}: {r.filename}  {r.size_bytes:,}B  {r.sha256[:16]}")
    print(f"  -> {result.path}")
    if not r.url:
        print("  warning: no source URL recorded. Pass --url so the document "
              "remains traceable to its publisher.")
    return 0


def _batch(args) -> int:
    from pathlib import Path

    batch = BatchIngester(
        inbox=Path(args.inbox) if args.inbox else None, snapshot=args.snapshot
    )
    if not batch.inbox.is_dir():
        print(f"no such folder: {batch.inbox}")
        return 1

    candidates = batch.scan()
    if not candidates:
        print(f"no documents found in {batch.inbox}")
        print("Drop files there named <source_id>.pdf — see docs/download-list.md")
        return 0

    matched = [c for c in candidates if c.matched and not c.already_ingested]
    duplicate = [c for c in candidates if c.matched and c.already_ingested]
    unmatched = [c for c in candidates if not c.matched]

    print(f"snapshot {batch.ingester.snapshot} · scanning {batch.inbox}\n")

    if matched:
        print(f"WILL INGEST ({len(matched)})")
        for c in matched:
            size = c.path.stat().st_size
            meta = []
            if c.pages:
                meta.append(f"{c.pages}p")
            if c.as_on:
                meta.append(f"as-on {c.as_on}")
            print(f"  {c.label:<34} {c.path.name:<34} {size:>10,}B  {' · '.join(meta)}")
            for w in c.warnings:
                print(f"       ! {w}")
            if c.gate_warning:
                print("       ! use-gated: collected now, cannot be loaded into the "
                      "store until the labour-regime question is resolved")
        print()

    if duplicate:
        print(f"ALREADY RECORDED ({len(duplicate)}) — identical bytes, skipping")
        for c in duplicate:
            print(f"  {c.label:<34} {c.path.name}")
        print()

    if unmatched:
        print(f"UNMATCHED ({len(unmatched)}) — not ingested")
        for c in unmatched:
            print(f"  {c.path.name:<44} {c.reason}")
            if c.suggestions:
                print(f"       did you mean: {', '.join(c.suggestions)}")
        print("\n  Rename to <source_id>.pdf and re-run. Hindi companion files "
              "take a .hi suffix\n  (cpa2019.hi.pdf); extra files for one source "
              "take __suffix (mva1988__schedule.pdf).")
        print("  Full id list: uv run pr-corpus names\n")

    if not args.apply:
        print("PREVIEW ONLY — nothing was written. Re-run with --apply to ingest.")
        return 0

    if not matched:
        print("nothing to ingest")
        return 1 if unmatched else 0

    print("ingesting…\n")
    failures = 0
    for cand, outcome in batch.apply(matched, force=args.force):
        if isinstance(outcome, Exception):
            failures += 1
            print(f"  FAILED  {cand.label:<32} {type(outcome).__name__}: {outcome}")
        else:
            r = outcome.record
            print(f"  ok      {cand.label:<32} {r.sha256[:12]}  -> {outcome.path}")

    print(f"\n{len(matched) - failures}/{len(matched)} ingested")
    if unmatched:
        print(f"{len(unmatched)} file(s) still unmatched — see above")
    return 1 if failures else 0


def _names(args) -> int:
    """Print the filename each source expects."""
    reg = default_registry()
    by_domain: dict[str, list] = {}
    for s in reg.sources:
        by_domain.setdefault(s.domain, []).append(s)

    print("Name each download after its source id, then run: uv run pr-corpus batch\n")
    for domain in ["consumer", "tenancy", "traffic", "employment", "insurance"]:
        items = sorted(by_domain.get(domain, []), key=lambda s: (s.priority, s.id))
        if not items:
            continue
        print(f"{domain.upper()}")
        for s in items:
            star = "*" if s.priority == 1 else " "
            print(f" {star} {s.id + '.pdf':<40} {' '.join(s.title.split())[:64]}")
        print()
    print("* = priority 1")
    print("Hindi companion: <source_id>.hi.pdf   extra file: <source_id>__suffix.pdf")
    return 0


def _status(args) -> int:
    reg = default_registry()
    raw = find_repo_root() / "data" / "raw"
    print(f"{'source':<34} {'status':<10} snapshots")
    for s in reg.sources:
        snaps = list_snapshots(raw, s.id)
        detail = ""
        if snaps:
            mp = manifest_path(raw, s.id, snaps[-1])
            if mp.exists():
                m = Manifest.load(mp)
                detail = f"  [{len(m.successful)} ok, {len(m.failed)} failed]"
        print(f"{s.id:<34} {s.status:<10} {','.join(snaps) or '-'}{detail}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="pr-corpus", description="PocketRights corpus acquisition")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("plan", help="show what would be fetched, no network")
    sp.add_argument("--domain")
    sp.set_defaults(fn=_plan)

    sf = sub.add_parser("fetch", help="acquire sources into a dated snapshot")
    sf.add_argument("--domain")
    sf.add_argument("--source")
    sf.add_argument("--snapshot", help="override the snapshot date (YYYY-MM-DD)")
    sf.add_argument("--max-priority", type=int, default=3)
    sf.add_argument("--force", action="store_true",
                    help="overwrite a file already present in this snapshot")
    sf.set_defaults(fn=_fetch)

    si = sub.add_parser(
        "ingest",
        help="record a manually-downloaded file with full provenance "
             "(for publishers that cannot be crawled)",
    )
    si.add_argument("--source", required=True)
    si.add_argument("--file", required=True)
    si.add_argument("--url", help="the page or file URL it was downloaded from")
    si.add_argument("--effective-from")
    si.add_argument("--notes")
    si.add_argument("--snapshot")
    si.add_argument("--force", action="store_true",
                    help="replace a differing file already in this snapshot")
    si.set_defaults(fn=_ingest)

    sb = sub.add_parser(
        "batch",
        help="record every document in data/inbox at once (preview by default)",
    )
    sb.add_argument("--inbox", help="folder to scan (default data/inbox)")
    sb.add_argument("--snapshot", help="override the snapshot date (YYYY-MM-DD)")
    sb.add_argument("--apply", action="store_true", help="actually ingest")
    sb.add_argument("--force", action="store_true",
                    help="replace differing files already in this snapshot")
    sb.set_defaults(fn=_batch)

    sn = sub.add_parser("names", help="the filename each source expects")
    sn.set_defaults(fn=_names)

    ss = sub.add_parser("status", help="what has been acquired so far")
    ss.set_defaults(fn=_status)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
