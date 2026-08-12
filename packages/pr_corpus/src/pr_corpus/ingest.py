"""Manual ingest — provenance for files a human downloaded.

Several publishers cannot be crawled:

* **IRDAI** publishes `robots.txt` with `Disallow: /` for every user agent. That
  is an explicit instruction not to crawl, and we honour it.
* **India Code** and **labour.gov.in** sit behind a WAF that returns 403 to
  non-browser clients — including for `robots.txt` itself, so their crawl policy
  cannot even be read. Defeating a WAF to take documents from a site that will
  not state its policy is not something this project does.

None of that stops a person opening the page in a browser and saving the PDF.
That is ordinary use of a public legal document. This module takes such a file
and gives it the same provenance treatment an automated fetch would get: hashed,
placed in a dated snapshot, recorded in the manifest.

The only thing lost versus an HTTP fetch is the server-reported content type and
final URL, so `source_url` must be supplied by hand and is marked
`acquisition="manual"` in the record.

    uv run pr-corpus ingest --source cpa2019 \\
        --file ~/Downloads/A2019-35.pdf \\
        --url https://www.indiacode.nic.in/handle/123456789/15256
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from .provenance import (
    FetchRecord,
    Manifest,
    manifest_path,
    sha256_bytes,
    snapshot_dir,
    today_snapshot,
    utc_now,
)
from .registry import Registry, default_registry, find_repo_root


@dataclass
class IngestResult:
    record: FetchRecord
    path: Path
    replaced: bool = False


CONTENT_TYPE_BY_SUFFIX = {
    ".pdf": "application/pdf",
    ".html": "text/html",
    ".htm": "text/html",
    ".txt": "text/plain",
    ".json": "application/json",
    ".xml": "application/xml",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def guess_content_type(path: Path) -> str | None:
    return CONTENT_TYPE_BY_SUFFIX.get(path.suffix.lower())


class CorpusIngester:
    """Records manually-downloaded files with full provenance."""

    def __init__(
        self,
        registry: Registry | None = None,
        raw_root: Path | None = None,
        snapshot: str | None = None,
    ) -> None:
        self.registry = registry or default_registry()
        self.raw_root = raw_root or (find_repo_root() / "data" / "raw")
        self.snapshot = snapshot or today_snapshot()

    def ingest(
        self,
        source_id: str,
        file: Path,
        *,
        source_url: str | None = None,
        effective_from: str | None = None,
        notes: str | None = None,
        force: bool = False,
    ) -> IngestResult:
        source = self.registry.source(source_id)

        # Use-gating, not acquisition-gating. Collecting a document is always
        # permitted — the Gazette notifications that RESOLVE the gate are
        # themselves employment sources. The warning rides on the record, and
        # pr_store refuses to load anything carrying it (risk R4).
        gate_warning = self.registry.blocks_use(source)

        file = Path(file).expanduser().resolve()
        if not file.is_file():
            raise FileNotFoundError(file)

        body = file.read_bytes()
        if not body:
            raise ValueError(f"{file} is empty")

        outdir = snapshot_dir(self.raw_root, source_id, self.snapshot)
        target = outdir / file.name

        replaced = target.exists()
        if replaced and not force:
            existing = sha256_bytes(target.read_bytes())
            if existing == sha256_bytes(body):
                # Byte-identical: idempotent, not a conflict.
                replaced = False
            else:
                raise FileExistsError(
                    f"{target} already exists in snapshot {self.snapshot} with different "
                    f"content. data/raw is append-only — use a new snapshot, or pass "
                    f"force=True if you are correcting a bad ingest."
                )

        outdir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file, target)

        record = FetchRecord(
            source_id=source_id,
            title=source.title,
            url=source_url or source.url,
            retrieved_at=utc_now(),
            sha256=sha256_bytes(body),
            size_bytes=len(body),
            content_type=guess_content_type(file),
            jurisdiction=source.jurisdiction,
            publisher=source.publisher,
            doc_type=source.doc_type,
            effective_from=effective_from,
            licence=self.registry.publisher(source.publisher).licence_status,
            snapshot_version=self.snapshot,
            filename=file.name,
            status="ok",
            notes=" · ".join(
                filter(
                    None,
                    [
                        "acquisition=manual (publisher not crawlable)",
                        f"USE-GATED: {gate_warning}" if gate_warning else None,
                        notes,
                    ],
                )
            ),
        )

        mpath = manifest_path(self.raw_root, source_id, self.snapshot)
        manifest = Manifest.load_or_create(mpath, source_id, self.snapshot)
        manifest.add(record)
        manifest.write(mpath)

        return IngestResult(record, target, replaced)
