"""Provenance records — the audit trail for every byte we acquire.

Task 6. Every downstream claim traces back to one of these: which URL, fetched
when, hashing to what, under which licence. Without this layer the corpus is
just "some text someone downloaded", and no citation in the paper is defensible.

Design rule: **`data/raw/` is append-only.** A re-crawl creates a new dated
snapshot directory; it never overwrites an existing one. That is what makes an
old result reproducible after a government portal silently edits a page.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

DocType = Literal["act", "rules", "regulation", "notification", "circular"]
FetchStatus = Literal["ok", "http_error", "network_error", "empty", "skipped"]

SNAPSHOT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def utc_now() -> str:
    """ISO-8601 UTC timestamp, seconds precision."""
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def today_snapshot() -> str:
    """Snapshot directory name for today, UTC."""
    return datetime.now(UTC).date().isoformat()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class FetchRecord(BaseModel):
    """One acquired file. Mirrors `policy.record_per_source` in sources.yaml."""

    source_id: str
    title: str
    url: str | None
    retrieved_at: str
    sha256: str
    size_bytes: int
    content_type: str | None
    jurisdiction: str
    publisher: str
    doc_type: DocType
    effective_from: str | None = None
    effective_until: str | None = None
    licence: str = "to_confirm"
    snapshot_version: str
    filename: str
    status: FetchStatus = "ok"
    http_status: int | None = None
    error: str | None = None
    notes: str | None = None

    @field_validator("snapshot_version")
    @classmethod
    def _snapshot_is_a_date(cls, v: str) -> str:
        if not SNAPSHOT_RE.match(v):
            raise ValueError(f"snapshot_version must be YYYY-MM-DD, got {v!r}")
        return v

    @field_validator("sha256")
    @classmethod
    def _hash_is_wellformed(cls, v: str) -> str:
        if v and (len(v) != 64 or not all(c in "0123456789abcdef" for c in v)):
            raise ValueError(f"not a sha256 hex digest: {v!r}")
        return v

    @property
    def ok(self) -> bool:
        return self.status == "ok"


class Manifest(BaseModel):
    """Every fetch attempt for one source in one snapshot.

    The manifest is tracked in git even though the raw bytes are not — it is the
    part that makes the corpus auditable without shipping hundreds of megabytes.
    """

    source_id: str
    snapshot_version: str
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)
    records: list[FetchRecord] = Field(default_factory=list)

    @property
    def successful(self) -> list[FetchRecord]:
        return [r for r in self.records if r.ok]

    @property
    def failed(self) -> list[FetchRecord]:
        return [r for r in self.records if not r.ok]

    def add(self, record: FetchRecord) -> None:
        """Add or replace by filename. Re-fetching within a snapshot updates in
        place; a genuinely new acquisition belongs in a new snapshot."""
        self.records = [r for r in self.records if r.filename != record.filename]
        self.records.append(record)
        self.records.sort(key=lambda r: r.filename)
        self.updated_at = utc_now()

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.model_dump(), indent=2) + "\n")

    @classmethod
    def load(cls, path: Path) -> Manifest:
        return cls.model_validate_json(path.read_text())

    @classmethod
    def load_or_create(cls, path: Path, source_id: str, snapshot: str) -> Manifest:
        if path.exists():
            return cls.load(path)
        return cls(source_id=source_id, snapshot_version=snapshot)


def snapshot_dir(raw_root: Path, source_id: str, snapshot: str) -> Path:
    """`data/raw/<source_id>/<snapshot>/` — the append-only unit."""
    return raw_root / source_id / snapshot


def manifest_path(raw_root: Path, source_id: str, snapshot: str) -> Path:
    return snapshot_dir(raw_root, source_id, snapshot) / "manifest.json"


def list_snapshots(raw_root: Path, source_id: str) -> list[str]:
    """Every snapshot for a source, oldest first."""
    base = raw_root / source_id
    if not base.is_dir():
        return []
    return sorted(p.name for p in base.iterdir() if p.is_dir() and SNAPSHOT_RE.match(p.name))


def latest_snapshot(raw_root: Path, source_id: str) -> str | None:
    snaps = list_snapshots(raw_root, source_id)
    return snaps[-1] if snaps else None
