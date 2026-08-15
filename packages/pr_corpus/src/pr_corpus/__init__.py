"""Source acquisition, provenance, hashing, dated snapshots."""

from .batch import BatchIngester, Candidate, inspect_pdf, parse_filename
from .fetcher import CorpusFetcher, FetchResult, RateLimiter, filename_for
from .ingest import CorpusIngester, IngestResult, guess_content_type
from .provenance import (
    FetchRecord,
    Manifest,
    latest_snapshot,
    list_snapshots,
    manifest_path,
    sha256_bytes,
    snapshot_dir,
    today_snapshot,
)
from .registry import Registry, Source, default_registry, find_repo_root, load_registry

__version__ = "0.1.0"

__all__ = [
    "BatchIngester",
    "Candidate",
    "CorpusFetcher",
    "CorpusIngester",
    "FetchRecord",
    "FetchResult",
    "IngestResult",
    "Manifest",
    "RateLimiter",
    "Registry",
    "Source",
    "default_registry",
    "filename_for",
    "find_repo_root",
    "inspect_pdf",
    "parse_filename",
    "guess_content_type",
    "latest_snapshot",
    "list_snapshots",
    "load_registry",
    "manifest_path",
    "sha256_bytes",
    "snapshot_dir",
    "today_snapshot",
]
