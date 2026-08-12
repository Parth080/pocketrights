"""The corpus fetcher — task 6.

Acquires authoritative legal sources, stores the raw bytes untouched, and
records full provenance.

Three properties that matter more than speed:

**Append-only.** Bytes land in `data/raw/<source_id>/<snapshot>/` and are never
overwritten. A re-crawl on a later date creates a new snapshot beside the old
one, so a result from an old corpus stays reproducible after a portal edits a
page.

**Polite.** These are government servers. One request every two seconds by
default, a real user agent, and retries that back off rather than hammer.

**Honest about failure.** A failed fetch is recorded in the manifest with its
reason, not silently dropped. A source that 404s must be visible, because the
alternative is a corpus with a quiet hole in it.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

import httpx
from tenacity import (
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .provenance import (
    FetchRecord,
    Manifest,
    manifest_path,
    sha256_bytes,
    snapshot_dir,
    today_snapshot,
    utc_now,
)
from .registry import Registry, Source, default_registry, find_repo_root

RETRYABLE = (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError)

EXT_BY_CONTENT_TYPE = {
    "application/pdf": ".pdf",
    "text/html": ".html",
    "application/xhtml+xml": ".html",
    "text/plain": ".txt",
    "application/json": ".json",
}


def filename_for(url: str, content_type: str | None) -> str:
    """A stable, filesystem-safe name for a fetched document."""
    path = unquote(urlparse(url).path)
    stem = Path(path).name or "index"
    if "." in stem:
        return stem.replace("/", "_")
    ext = EXT_BY_CONTENT_TYPE.get((content_type or "").split(";")[0].strip(), ".bin")
    return f"{stem}{ext}"


class RateLimiter:
    """Trailing-edge limiter. Sleeps so that consecutive calls are at least
    `1/rps` apart."""

    def __init__(self, rps: float) -> None:
        self.min_interval = 1.0 / rps if rps > 0 else 0.0
        self._last = 0.0

    def wait(self) -> None:
        if self.min_interval <= 0:
            return
        gap = time.monotonic() - self._last
        if gap < self.min_interval:
            time.sleep(self.min_interval - gap)
        self._last = time.monotonic()


@dataclass
class FetchResult:
    record: FetchRecord
    path: Path | None
    already_present: bool = False


class CorpusFetcher:
    """Fetches sources listed in the registry into dated snapshots."""

    def __init__(
        self,
        registry: Registry | None = None,
        raw_root: Path | None = None,
        snapshot: str | None = None,
        client: httpx.Client | None = None,
        timeout: float = 60.0,
        max_attempts: int = 4,
        backoff_multiplier: float = 2.0,
    ) -> None:
        self.registry = registry or default_registry()
        self.raw_root = raw_root or (find_repo_root() / "data" / "raw")
        self.snapshot = snapshot or today_snapshot()
        self.limiter = RateLimiter(self.registry.policy.rate_limit_rps)
        # Injectable so tests can disable backoff. Retrying real government
        # portals matters in production; sleeping 14s in a unit test does not.
        self.max_attempts = max_attempts
        self.backoff_multiplier = backoff_multiplier
        self._owns_client = client is None
        self.client = client or httpx.Client(
            follow_redirects=True,
            timeout=timeout,
            headers={"User-Agent": self.registry.policy.user_agent},
        )

    def __enter__(self) -> CorpusFetcher:
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    # -- internals -------------------------------------------------------

    def _get(self, url: str) -> httpx.Response:
        retrier = Retrying(
            retry=retry_if_exception_type(RETRYABLE),
            stop=stop_after_attempt(self.max_attempts),
            wait=wait_exponential(
                multiplier=self.backoff_multiplier,
                min=self.backoff_multiplier,
                max=30,
            ),
            reraise=True,
        )
        for attempt in retrier:
            with attempt:
                self.limiter.wait()
                return self.client.get(url)
        raise RuntimeError("unreachable")  # pragma: no cover

    def _blank_record(self, source: Source, url: str | None, **kw) -> FetchRecord:
        return FetchRecord(
            source_id=source.id,
            title=source.title,
            url=url,
            retrieved_at=utc_now(),
            sha256=kw.pop("sha256", ""),
            size_bytes=kw.pop("size_bytes", 0),
            content_type=kw.pop("content_type", None),
            jurisdiction=source.jurisdiction,
            publisher=source.publisher,
            doc_type=source.doc_type,
            licence=self.registry.publisher(source.publisher).licence_status,
            snapshot_version=self.snapshot,
            filename=kw.pop("filename", "-"),
            **kw,
        )

    # -- public API ------------------------------------------------------

    def fetch_source(self, source_id: str, *, force: bool = False) -> FetchResult:
        """Fetch one source into the current snapshot."""
        source = self.registry.source(source_id)

        # Use-gating is NOT acquisition-gating. Fetching bytes is always
        # allowed; the warning travels with the record so the store can refuse.
        gate_warning = self.registry.blocks_use(source)

        if not source.url:
            return FetchResult(
                self._blank_record(
                    source,
                    None,
                    status="skipped",
                    error="no url recorded in contracts/sources.yaml",
                ),
                None,
            )

        outdir = snapshot_dir(self.raw_root, source.id, self.snapshot)
        mpath = manifest_path(self.raw_root, source.id, self.snapshot)
        manifest = Manifest.load_or_create(mpath, source.id, self.snapshot)

        try:
            response = self._get(source.url)
        except Exception as exc:
            record = self._blank_record(
                source, source.url, status="network_error", error=f"{type(exc).__name__}: {exc}"
            )
            manifest.add(record)
            manifest.write(mpath)
            return FetchResult(record, None)

        if response.status_code != 200:
            record = self._blank_record(
                source,
                source.url,
                status="http_error",
                http_status=response.status_code,
                error=f"HTTP {response.status_code}",
            )
            manifest.add(record)
            manifest.write(mpath)
            return FetchResult(record, None)

        body = response.content
        if not body:
            record = self._blank_record(
                source, source.url, status="empty", http_status=200, error="empty body"
            )
            manifest.add(record)
            manifest.write(mpath)
            return FetchResult(record, None)

        content_type = response.headers.get("content-type")
        filename = filename_for(str(response.url), content_type)
        target = outdir / filename

        # Append-only: never rewrite an existing file in a committed snapshot.
        if target.exists() and not force:
            existing = target.read_bytes()
            record = self._blank_record(
                source,
                str(response.url),
                sha256=sha256_bytes(existing),
                size_bytes=len(existing),
                content_type=content_type,
                filename=filename,
                http_status=200,
                notes="already present in this snapshot; not overwritten",
            )
            manifest.add(record)
            manifest.write(mpath)
            return FetchResult(record, target, already_present=True)

        outdir.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)

        record = self._blank_record(
            source,
            str(response.url),
            sha256=sha256_bytes(body),
            size_bytes=len(body),
            content_type=content_type,
            filename=filename,
            http_status=200,
            notes=f"USE-GATED: {gate_warning}" if gate_warning else None,
        )
        manifest.add(record)
        manifest.write(mpath)
        return FetchResult(record, target)

    def fetch_domain(self, domain: str, *, max_priority: int = 3) -> list[FetchResult]:
        return [
            self.fetch_source(s.id)
            for s in self.registry.fetchable(domain=domain, max_priority=max_priority)
        ]

    def plan(self, domain: str | None = None) -> dict[str, list[str]]:
        """What would happen, without touching the network."""
        ready, no_url, use_gated = [], [], []
        for s in self.registry.sources:
            if domain and s.domain != domain:
                continue
            if not s.url:
                no_url.append(s.id)
            else:
                ready.append(s.id)
            if (reason := self.registry.blocks_use(s)) is not None:
                use_gated.append(f"{s.id}: {reason.splitlines()[0]}")
        return {
            "ready": ready,
            "no_url": no_url,
            "blocked": [],
            "use_gated": use_gated,
        }
