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

    ss = sub.add_parser("status", help="what has been acquired so far")
    ss.set_defaults(fn=_status)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
