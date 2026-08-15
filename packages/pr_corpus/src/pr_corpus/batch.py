"""Batch ingest — record a folder of hand-downloaded documents in one pass.

Downloading thirty documents is tedious enough without thirty separate ingest
commands. Drop the files into `data/inbox/` named after their `source_id` and
this matches, inspects and records them together.

    uv run pr-corpus batch                # preview — touches nothing
    uv run pr-corpus batch --apply        # do it

**Preview is the default.** Ingest writes into an append-only store, so a
mis-matched file is annoying to undo. The preview shows exactly what would
happen and refuses to guess.

Naming: `<source_id>.pdf`. A source with several files takes a suffix after a
double underscore — `mva1988__schedule.pdf`. A Hindi companion takes `.hi`:
`cpa2019.hi.pdf`. Anything unmatched is reported with suggestions rather than
silently skipped.

Beyond matching, each file is inspected before it is recorded:

* **"As on" date** — India Code stamps consolidated texts with the date the
  content is current to. That is `content_as_of`, and it is a different fact
  from when the file was downloaded. Conflating them is how a corpus quietly
  overstates its currency.
* **Scanned pages** — a PDF with no extractable text needs OCR, and finding
  that out at parse time is too late.
* **Bundles** — the Consumer Protection download held eight documents in one
  94-page file. Page count and internal headings flag likely bundles so a
  bundle map can be written before parsing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import get_close_matches
from pathlib import Path

from .ingest import CorpusIngester, IngestResult
from .provenance import list_snapshots, sha256_bytes
from .registry import Registry, default_registry, find_repo_root

DOC_SUFFIXES = {".pdf", ".html", ".htm", ".txt", ".doc", ".docx", ".xml"}

# "[As on the 21st May, 2025]" · "As on 21.11.2025" · "as on 21 November 2025"
AS_ON_RE = re.compile(
    r"\[?\s*as\s+on\s+(?:the\s+)?"
    r"([0-9]{1,2}\s*(?:st|nd|rd|th)?[\s.\-/]+[A-Za-z0-9]+[\s.\-/,]+[0-9]{2,4})",
    re.I,
)

# A file holding this many pages is probably several documents.
BUNDLE_PAGE_HINT = 60
# Below this many characters per page, the PDF is probably scanned images.
SCANNED_CHARS_PER_PAGE = 200


@dataclass
class Candidate:
    """One file in the inbox, matched or not."""

    path: Path
    source_id: str | None = None
    language: str = "en"
    variant: str | None = None
    reason: str | None = None            # why it could not be matched
    suggestions: list[str] = field(default_factory=list)

    # inspection
    pages: int | None = None
    chars: int | None = None
    as_on: str | None = None
    warnings: list[str] = field(default_factory=list)

    already_ingested: bool = False
    gate_warning: str | None = None

    @property
    def matched(self) -> bool:
        return self.source_id is not None

    @property
    def label(self) -> str:
        bits = [self.source_id or "?"]
        if self.language != "en":
            bits.append(self.language)
        if self.variant:
            bits.append(self.variant)
        return " · ".join(bits)


def parse_filename(name: str) -> tuple[str, str, str | None]:
    """`cpa2019.hi.pdf` -> ("cpa2019", "hi", None)
    `mva1988__schedule.pdf` -> ("mva1988", "en", "schedule")
    """
    stem = Path(name).stem
    # Language suffix comes off first: in `mva1988__schedule.hi` it trails the
    # variant, so splitting on "__" beforehand would hide it.
    language = "en"
    if stem.endswith((".hi", "_hi", "-hi")):
        stem, language = stem[:-3], "hi"
    variant = None
    if "__" in stem:
        stem, variant = stem.split("__", 1)
    return stem, language, variant


def inspect_pdf(path: Path) -> dict:
    """Page count, text volume, and any 'As on' date. Never raises."""
    out: dict = {"pages": None, "chars": None, "as_on": None, "warnings": []}
    if path.suffix.lower() != ".pdf":
        return out
    try:
        import pymupdf
    except ImportError:                                   # pragma: no cover
        out["warnings"].append("pymupdf unavailable; not inspected")
        return out

    try:
        doc = pymupdf.open(path)
    except Exception as exc:                              # pragma: no cover
        out["warnings"].append(f"could not open: {exc}")
        return out

    try:
        out["pages"] = len(doc)
        head = "".join(doc[i].get_text() for i in range(min(4, len(doc))))
        out["chars"] = sum(len(doc[i].get_text()) for i in range(len(doc)))

        if m := AS_ON_RE.search(head):
            out["as_on"] = " ".join(m.group(1).split())

        if out["pages"] and out["chars"] / out["pages"] < SCANNED_CHARS_PER_PAGE:
            out["warnings"].append(
                f"only {out['chars'] // max(out['pages'], 1)} chars/page — "
                "likely a scanned PDF, which needs OCR before parsing"
            )
        if out["pages"] and out["pages"] >= BUNDLE_PAGE_HINT:
            out["warnings"].append(
                f"{out['pages']} pages — likely a bundle of several documents; "
                "a bundle map will be needed before parsing"
            )
        if re.search(r"[ऀ-ॿ]", head):
            out["warnings"].append("contains Devanagari — bilingual or Hindi edition")
    finally:
        doc.close()
    return out


class BatchIngester:
    """Match, inspect and record a folder of downloads."""

    def __init__(
        self,
        registry: Registry | None = None,
        inbox: Path | None = None,
        raw_root: Path | None = None,
        snapshot: str | None = None,
    ) -> None:
        self.registry = registry or default_registry()
        root = find_repo_root()
        self.inbox = inbox or (root / "data" / "inbox")
        self.raw_root = raw_root or (root / "data" / "raw")
        self.ingester = CorpusIngester(
            registry=self.registry, raw_root=self.raw_root, snapshot=snapshot
        )

    # -- planning ---------------------------------------------------------

    def scan(self) -> list[Candidate]:
        """Match every document in the inbox against the registry."""
        known = {s.id for s in self.registry.sources}
        candidates: list[Candidate] = []

        for path in sorted(self.inbox.iterdir()):
            if not path.is_file() or path.suffix.lower() not in DOC_SUFFIXES:
                continue

            stem, language, variant = parse_filename(path.name)
            cand = Candidate(path=path, language=language, variant=variant)

            # Case-insensitive match; downloads often arrive as CPA.pdf.
            exact = next((k for k in known if k.lower() == stem.lower()), None)
            if exact:
                cand.source_id = exact
            else:
                cand.reason = f"'{stem}' is not a source id"
                cand.suggestions = get_close_matches(stem.lower(), sorted(known), n=3)

            info = inspect_pdf(path)
            cand.pages, cand.chars = info["pages"], info["chars"]
            cand.as_on, cand.warnings = info["as_on"], list(info["warnings"])

            if cand.source_id:
                source = self.registry.source(cand.source_id)
                cand.gate_warning = self.registry.blocks_use(source)
                cand.already_ingested = self._already_ingested(cand)

            candidates.append(cand)
        return candidates

    def _already_ingested(self, cand: Candidate) -> bool:
        """True when these exact bytes are already in some snapshot."""
        assert cand.source_id
        digest = sha256_bytes(cand.path.read_bytes())
        from .provenance import Manifest, manifest_path

        for snap in list_snapshots(self.raw_root, cand.source_id):
            mpath = manifest_path(self.raw_root, cand.source_id, snap)
            if not mpath.exists():
                continue
            if any(r.sha256 == digest for r in Manifest.load(mpath).records):
                return True
        return False

    # -- execution --------------------------------------------------------

    def apply(
        self, candidates: list[Candidate], *, force: bool = False
    ) -> list[tuple[Candidate, IngestResult | Exception]]:
        results = []
        for cand in candidates:
            if not cand.matched:
                continue
            try:
                notes = (
                    f"content_as_of={cand.as_on}" if cand.as_on else None
                )
                result = self.ingester.ingest(
                    cand.source_id,
                    cand.path,
                    effective_from=None,
                    notes=notes,
                    force=force,
                )
                results.append((cand, result))
            except Exception as exc:
                results.append((cand, exc))
        return results
