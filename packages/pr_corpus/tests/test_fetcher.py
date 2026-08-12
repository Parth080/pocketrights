"""Tests for the corpus fetcher (task 6).

All offline — httpx.MockTransport stands in for the network, so the suite never
touches a government portal.
"""

from __future__ import annotations

import json

import httpx
import pytest
from pr_corpus.fetcher import CorpusFetcher, RateLimiter, filename_for
from pr_corpus.provenance import (
    FetchRecord,
    Manifest,
    latest_snapshot,
    list_snapshots,
    manifest_path,
    sha256_bytes,
    snapshot_dir,
)
from pr_corpus.registry import Registry

PDF_BYTES = b"%PDF-1.4\nfake consumer protection act\n%%EOF"
SNAP = "2026-08-11"


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------

def _registry(**overrides) -> Registry:
    data = {
        "version": "1.0",
        "corpus_snapshot": None,
        "publishers": [
            {"id": "indiacode", "name": "India Code", "licence_status": "to_confirm"},
        ],
        "policy": {
            "raw_immutable": True,
            "hash_algorithm": "sha256",
            "rate_limit_rps": 1000.0,  # no real sleeping in tests
            "user_agent": "test",
            "record_per_source": [],
        },
        "blocking_determinations": [
            {
                "id": "labour_regime",
                "question": "Which employment regime is in force?",
                "status": "unresolved",
                "resolution": None,
                "resolved_at": None,
            }
        ],
        "sources": [
            {
                "id": "cpa2019", "domain": "consumer", "title": "Consumer Protection Act, 2019",
                "doc_type": "act", "jurisdiction": "IN", "publisher": "indiacode",
                "url": "https://example.test/cpa2019.pdf", "priority": 1, "status": "planned",
            },
            {
                "id": "no_url_src", "domain": "consumer", "title": "Something Unlocated",
                "doc_type": "rules", "jurisdiction": "IN", "publisher": "indiacode",
                "url": None, "priority": 2, "status": "planned",
            },
            {
                "id": "gratuity1972", "domain": "employment",
                "title": "Payment of Gratuity Act, 1972",
                "doc_type": "act", "jurisdiction": "IN", "publisher": "indiacode",
                "url": "https://example.test/gratuity.pdf", "priority": 1,
                "status": "planned", "gated_on": "labour_regime",
            },
            {
                "id": "missing_src", "domain": "consumer", "title": "A 404",
                "doc_type": "rules", "jurisdiction": "IN", "publisher": "indiacode",
                "url": "https://example.test/gone.pdf", "priority": 3, "status": "planned",
            },
        ],
        "authorities": [],
    }
    data.update(overrides)
    return Registry.model_validate(data)


def _handler(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith("gone.pdf"):
        return httpx.Response(404)
    if request.url.path.endswith("empty.pdf"):
        return httpx.Response(200, content=b"")
    return httpx.Response(
        200, content=PDF_BYTES, headers={"content-type": "application/pdf"}
    )


@pytest.fixture
def fetcher(tmp_path):
    client = httpx.Client(transport=httpx.MockTransport(_handler), follow_redirects=True)
    f = CorpusFetcher(
        registry=_registry(), raw_root=tmp_path / "raw", snapshot=SNAP, client=client,
        max_attempts=2, backoff_multiplier=0.001
    )
    yield f
    client.close()


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def test_filename_from_url_path():
    assert filename_for("https://x.test/a/cpa2019.pdf", "application/pdf") == "cpa2019.pdf"


def test_filename_falls_back_to_content_type():
    assert filename_for("https://x.test/view", "text/html; charset=utf-8") == "view.html"
    assert filename_for("https://x.test/blob", "application/octet-stream") == "blob.bin"


def test_rate_limiter_spaces_calls():
    import time

    limiter = RateLimiter(rps=20.0)  # 50 ms apart
    limiter.wait()
    start = time.monotonic()
    limiter.wait()
    assert time.monotonic() - start >= 0.04


def test_sha256_is_stable():
    assert sha256_bytes(b"abc") == sha256_bytes(b"abc")
    assert len(sha256_bytes(b"abc")) == 64


# --------------------------------------------------------------------------
# Happy path
# --------------------------------------------------------------------------

def test_fetch_writes_bytes_and_manifest(fetcher, tmp_path):
    result = fetcher.fetch_source("cpa2019")

    assert result.record.ok
    assert result.path.read_bytes() == PDF_BYTES
    assert result.record.sha256 == sha256_bytes(PDF_BYTES)
    assert result.record.size_bytes == len(PDF_BYTES)

    mpath = manifest_path(tmp_path / "raw", "cpa2019", SNAP)
    manifest = Manifest.load(mpath)
    assert len(manifest.successful) == 1
    assert manifest.records[0].filename == "cpa2019.pdf"


def test_snapshot_directory_layout(fetcher, tmp_path):
    fetcher.fetch_source("cpa2019")
    expected = snapshot_dir(tmp_path / "raw", "cpa2019", SNAP)
    assert expected.is_dir()
    assert expected.parent.name == "cpa2019"
    assert expected.name == SNAP


def test_provenance_captures_the_required_fields(fetcher):
    r = fetcher.fetch_source("cpa2019").record
    assert r.source_id == "cpa2019"
    assert r.jurisdiction == "IN"
    assert r.publisher == "indiacode"
    assert r.doc_type == "act"
    assert r.licence == "to_confirm"
    assert r.snapshot_version == SNAP
    assert r.retrieved_at.endswith("+00:00")
    assert r.content_type == "application/pdf"


def test_manifest_is_valid_json_on_disk(fetcher, tmp_path):
    fetcher.fetch_source("cpa2019")
    raw = manifest_path(tmp_path / "raw", "cpa2019", SNAP).read_text()
    assert json.loads(raw)["source_id"] == "cpa2019"


# --------------------------------------------------------------------------
# Append-only discipline
# --------------------------------------------------------------------------

def test_refetch_does_not_overwrite(fetcher, tmp_path):
    first = fetcher.fetch_source("cpa2019")
    first.path.write_bytes(b"EDITED BY HAND")

    second = fetcher.fetch_source("cpa2019")

    assert second.already_present
    assert second.path.read_bytes() == b"EDITED BY HAND", "existing snapshot was overwritten"
    assert "not overwritten" in (second.record.notes or "")


def test_force_overwrites_within_a_snapshot(fetcher):
    first = fetcher.fetch_source("cpa2019")
    first.path.write_bytes(b"EDITED BY HAND")
    second = fetcher.fetch_source("cpa2019", force=True)
    assert second.path.read_bytes() == PDF_BYTES


def test_new_snapshot_sits_beside_the_old_one(tmp_path):
    client = httpx.Client(transport=httpx.MockTransport(_handler))
    reg, raw = _registry(), tmp_path / "raw"
    for snap in ("2026-08-11", "2026-09-01"):
        with CorpusFetcher(registry=reg, raw_root=raw, snapshot=snap, client=client) as f:
            f.fetch_source("cpa2019")
    client.close()

    assert list_snapshots(raw, "cpa2019") == ["2026-08-11", "2026-09-01"]
    assert latest_snapshot(raw, "cpa2019") == "2026-09-01"


def test_manifest_add_replaces_by_filename():
    m = Manifest(source_id="x", snapshot_version=SNAP)
    for size in (1, 2):
        m.add(
            FetchRecord(
                source_id="x", title="t", url=None, retrieved_at="2026-08-11T00:00:00+00:00",
                sha256="a" * 64, size_bytes=size, content_type=None, jurisdiction="IN",
                publisher="p", doc_type="act", snapshot_version=SNAP, filename="same.pdf",
            )
        )
    assert len(m.records) == 1
    assert m.records[0].size_bytes == 2


# --------------------------------------------------------------------------
# Failures are recorded, never silently dropped
# --------------------------------------------------------------------------

def test_http_error_is_recorded(fetcher, tmp_path):
    result = fetcher.fetch_source("missing_src")
    assert not result.record.ok
    assert result.record.status == "http_error"
    assert result.record.http_status == 404
    assert result.path is None

    manifest = Manifest.load(manifest_path(tmp_path / "raw", "missing_src", SNAP))
    assert len(manifest.failed) == 1, "a failed fetch must still appear in the manifest"


def test_missing_url_is_skipped_with_a_reason(fetcher):
    r = fetcher.fetch_source("no_url_src").record
    assert r.status == "skipped"
    assert "no url" in r.error.lower()


def test_network_error_is_recorded(tmp_path):
    def boom(request):
        raise httpx.ConnectError("dns failure")

    client = httpx.Client(transport=httpx.MockTransport(boom))
    with CorpusFetcher(
        registry=_registry(), raw_root=tmp_path / "raw", snapshot=SNAP, client=client,
        max_attempts=2, backoff_multiplier=0.001
    ) as f:
        r = f.fetch_source("cpa2019").record
    client.close()
    assert r.status == "network_error"
    assert "ConnectError" in r.error


# --------------------------------------------------------------------------
# The labour-regime gate — risk R4, enforced in code
# --------------------------------------------------------------------------

def test_gated_source_is_still_acquired_but_flagged(fetcher, tmp_path):
    """Use-gating, not acquisition-gating. Collecting bytes creates no training
    data, and the Gazette notifications that RESOLVE the gate are themselves
    employment sources — a gate must not block the document that lifts it."""
    result = fetcher.fetch_source("gratuity1972")
    assert result.record.ok, "acquisition should not be blocked"
    assert "USE-GATED" in (result.record.notes or "")
    assert "labour_regime" in result.record.notes
    assert (tmp_path / "raw" / "gratuity1972").exists()


def test_gated_source_is_excluded_from_usable(fetcher):
    """The gate must still bite where it matters: loading into the store."""
    reg = fetcher.registry
    assert reg.blocks_use(reg.source("gratuity1972")) is not None
    assert "gratuity1972" not in [s.id for s in reg.usable()]
    assert "cpa2019" in [s.id for s in reg.usable()]


def test_gated_source_fetches_once_resolved(tmp_path):
    reg = _registry()
    det = reg.determination("labour_regime")
    det.status, det.resolution, det.resolved_at = "resolved", "codes in force", "2026-08-11"

    client = httpx.Client(transport=httpx.MockTransport(_handler))
    with CorpusFetcher(
        registry=reg, raw_root=tmp_path / "raw", snapshot=SNAP, client=client,
        max_attempts=2, backoff_multiplier=0.001
    ) as f:
        assert f.fetch_source("gratuity1972").record.ok
    client.close()


def test_gate_on_an_unknown_determination_blocks(tmp_path):
    reg = _registry()
    reg.source("cpa2019").gated_on = "does_not_exist"
    assert "does not exist" in reg.is_blocked(reg.source("cpa2019"))


# --------------------------------------------------------------------------
# Planning and selection
# --------------------------------------------------------------------------

def test_plan_classifies_every_source(fetcher):
    plan = fetcher.plan()
    assert plan["ready"] == ["cpa2019", "gratuity1972", "missing_src"]
    assert plan["no_url"] == ["no_url_src"]
    assert plan["blocked"] == []


def test_plan_touches_no_network(tmp_path):
    def explode(request):
        raise AssertionError("plan() must not make requests")

    client = httpx.Client(transport=httpx.MockTransport(explode))
    with CorpusFetcher(
        registry=_registry(), raw_root=tmp_path / "raw", snapshot=SNAP, client=client,
        max_attempts=2, backoff_multiplier=0.001
    ) as f:
        f.plan()
    client.close()


def test_fetchable_includes_gated_sources_and_respects_priority():
    reg = _registry()
    assert [s.id for s in reg.fetchable(max_priority=1)] == ["cpa2019", "gratuity1972"]
    assert "gratuity1972" in [s.id for s in reg.fetchable()]
    assert "gratuity1972" not in [s.id for s in reg.usable()]


def test_fetch_domain_acquires_gated_sources(tmp_path):
    client = httpx.Client(transport=httpx.MockTransport(_handler))
    with CorpusFetcher(
        registry=_registry(), raw_root=tmp_path / "raw", snapshot=SNAP, client=client,
        max_attempts=2, backoff_multiplier=0.001
    ) as f:
        results = f.fetch_domain("employment")
    client.close()
    assert len(results) == 1
    assert results[0].record.ok
    assert "USE-GATED" in (results[0].record.notes or "")


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------

def test_snapshot_must_be_a_date():
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        FetchRecord(
            source_id="x", title="t", url=None, retrieved_at="now", sha256="", size_bytes=0,
            content_type=None, jurisdiction="IN", publisher="p", doc_type="act",
            snapshot_version="latest", filename="f",
        )


def test_malformed_hash_is_rejected():
    with pytest.raises(ValueError, match="sha256"):
        FetchRecord(
            source_id="x", title="t", url=None, retrieved_at="now", sha256="nope",
            size_bytes=0, content_type=None, jurisdiction="IN", publisher="p",
            doc_type="act", snapshot_version=SNAP, filename="f",
        )
