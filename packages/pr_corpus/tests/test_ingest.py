"""Tests for manual ingest.

Manual ingest exists because several publishers cannot be crawled (IRDAI says
`Disallow: /`; India Code and labour.gov.in 403 everything). The provenance
guarantees must hold exactly as they do for an HTTP fetch — including the
labour-regime gate, which would otherwise be bypassable by downloading by hand.
"""

from __future__ import annotations

import pytest
from pr_corpus.ingest import CorpusIngester, guess_content_type
from pr_corpus.provenance import Manifest, manifest_path, sha256_bytes
from pr_corpus.registry import Registry

SNAP = "2026-08-11"
BODY = b"%PDF-1.4\nConsumer Protection Act 2019\n%%EOF"


def _registry() -> Registry:
    return Registry.model_validate(
        {
            "version": "1.0",
            "publishers": [
                {"id": "indiacode", "name": "India Code", "licence_status": "to_confirm"}
            ],
            "policy": {"rate_limit_rps": 1000.0, "record_per_source": []},
            "blocking_determinations": [
                {
                    "id": "labour_regime",
                    "question": "Which employment regime is in force?",
                    "status": "unresolved",
                }
            ],
            "sources": [
                {
                    "id": "cpa2019", "domain": "consumer",
                    "title": "Consumer Protection Act, 2019", "doc_type": "act",
                    "jurisdiction": "IN", "publisher": "indiacode", "url": None,
                    "priority": 1, "status": "planned",
                },
                {
                    "id": "gratuity1972", "domain": "employment",
                    "title": "Payment of Gratuity Act, 1972", "doc_type": "act",
                    "jurisdiction": "IN", "publisher": "indiacode", "url": None,
                    "priority": 1, "status": "planned", "gated_on": "labour_regime",
                },
            ],
            "authorities": [],
        }
    )


@pytest.fixture
def ingester(tmp_path):
    return CorpusIngester(
        registry=_registry(), raw_root=tmp_path / "raw", snapshot=SNAP
    )


@pytest.fixture
def downloaded(tmp_path):
    p = tmp_path / "downloads" / "A2019-35.pdf"
    p.parent.mkdir(parents=True)
    p.write_bytes(BODY)
    return p


def test_content_type_from_suffix():
    from pathlib import Path

    assert guess_content_type(Path("a.pdf")) == "application/pdf"
    assert guess_content_type(Path("a.HTML")) == "text/html"
    assert guess_content_type(Path("a.weird")) is None


def test_ingest_copies_and_hashes(ingester, downloaded, tmp_path):
    result = ingester.ingest(
        "cpa2019", downloaded, source_url="https://indiacode.example/handle/1"
    )

    assert result.path.read_bytes() == BODY
    assert result.record.sha256 == sha256_bytes(BODY)
    assert result.record.size_bytes == len(BODY)
    assert result.record.content_type == "application/pdf"
    assert result.record.url == "https://indiacode.example/handle/1"
    assert downloaded.exists(), "the original download must not be moved"


def test_ingest_marks_acquisition_as_manual(ingester, downloaded):
    r = ingester.ingest("cpa2019", downloaded).record
    assert "acquisition=manual" in r.notes


def test_ingest_writes_a_manifest(ingester, downloaded, tmp_path):
    ingester.ingest("cpa2019", downloaded)
    m = Manifest.load(manifest_path(tmp_path / "raw", "cpa2019", SNAP))
    assert len(m.successful) == 1
    assert m.records[0].filename == "A2019-35.pdf"


def test_ingest_is_idempotent_for_identical_bytes(ingester, downloaded):
    first = ingester.ingest("cpa2019", downloaded)
    second = ingester.ingest("cpa2019", downloaded)
    assert not second.replaced
    assert first.record.sha256 == second.record.sha256


def test_differing_content_in_the_same_snapshot_is_refused(ingester, downloaded, tmp_path):
    ingester.ingest("cpa2019", downloaded)
    downloaded.write_bytes(b"%PDF-1.4\nDIFFERENT\n%%EOF")

    with pytest.raises(FileExistsError, match="append-only"):
        ingester.ingest("cpa2019", downloaded)


def test_force_allows_correcting_a_bad_ingest(ingester, downloaded):
    ingester.ingest("cpa2019", downloaded)
    downloaded.write_bytes(b"%PDF-1.4\nCORRECTED\n%%EOF")
    result = ingester.ingest("cpa2019", downloaded, force=True)
    assert result.replaced
    assert result.path.read_bytes() == b"%PDF-1.4\nCORRECTED\n%%EOF"


def test_a_new_snapshot_accepts_a_revised_document(tmp_path, downloaded):
    reg, raw = _registry(), tmp_path / "raw"
    CorpusIngester(registry=reg, raw_root=raw, snapshot="2026-08-11").ingest(
        "cpa2019", downloaded
    )
    downloaded.write_bytes(b"%PDF-1.4\nAMENDED 2026\n%%EOF")
    later = CorpusIngester(registry=reg, raw_root=raw, snapshot="2027-01-05").ingest(
        "cpa2019", downloaded
    )
    assert later.path.read_bytes() == b"%PDF-1.4\nAMENDED 2026\n%%EOF"
    assert (raw / "cpa2019" / "2026-08-11" / "A2019-35.pdf").read_bytes() == BODY


# --------------------------------------------------------------------------
# The gate must not be bypassable by hand — risk R4
# --------------------------------------------------------------------------

def test_gated_source_cannot_be_ingested_manually(ingester, downloaded):
    with pytest.raises(PermissionError, match="labour_regime"):
        ingester.ingest("gratuity1972", downloaded)


def test_gated_source_ingests_once_resolved(tmp_path, downloaded):
    reg = _registry()
    det = reg.determination("labour_regime")
    det.status, det.resolution, det.resolved_at = "resolved", "codes in force", "2026-08-11"
    ing = CorpusIngester(registry=reg, raw_root=tmp_path / "raw", snapshot=SNAP)
    assert ing.ingest("gratuity1972", downloaded).record.ok


# --------------------------------------------------------------------------
# Input validation
# --------------------------------------------------------------------------

def test_missing_file_raises(ingester, tmp_path):
    with pytest.raises(FileNotFoundError):
        ingester.ingest("cpa2019", tmp_path / "nope.pdf")


def test_empty_file_raises(ingester, tmp_path):
    empty = tmp_path / "empty.pdf"
    empty.write_bytes(b"")
    with pytest.raises(ValueError, match="empty"):
        ingester.ingest("cpa2019", empty)


def test_unknown_source_raises(ingester, downloaded):
    with pytest.raises(KeyError):
        ingester.ingest("not_a_source", downloaded)
