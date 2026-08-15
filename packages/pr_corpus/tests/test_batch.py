"""Tests for batch ingest.

Batch ingest writes into an append-only store, so the important property is
that it does nothing without --apply, and that it never guesses which source a
file belongs to.
"""

from __future__ import annotations

import pymupdf
import pytest
from pr_corpus.batch import BatchIngester, inspect_pdf, parse_filename
from pr_corpus.registry import Registry


def _registry() -> Registry:
    return Registry.model_validate(
        {
            "version": "1.0",
            "publishers": [{"id": "indiacode", "name": "India Code"}],
            "policy": {"rate_limit_rps": 1000.0, "record_per_source": []},
            "blocking_determinations": [
                {"id": "labour_regime", "question": "Which regime?",
                 "status": "unresolved"}
            ],
            "sources": [
                {"id": "cpa2019", "domain": "consumer", "title": "CPA 2019",
                 "doc_type": "act", "jurisdiction": "IN", "publisher": "indiacode",
                 "priority": 1, "status": "planned"},
                {"id": "mva1988", "domain": "traffic", "title": "MV Act 1988",
                 "doc_type": "act", "jurisdiction": "IN", "publisher": "indiacode",
                 "priority": 1, "status": "planned"},
                {"id": "gratuity1972", "domain": "employment", "title": "Gratuity",
                 "doc_type": "act", "jurisdiction": "IN", "publisher": "indiacode",
                 "priority": 1, "status": "planned", "gated_on": "labour_regime"},
            ],
            "authorities": [],
        }
    )


def _pdf(path, text="1. Some provision text here.", pages=1):
    doc = pymupdf.open()
    for _ in range(pages):
        page = doc.new_page(width=595, height=842)
        page.insert_textbox(pymupdf.Rect(60, 60, 500, 400), text,
                            fontsize=10, fontname="helv")
    doc.save(path)
    doc.close()
    return path


@pytest.fixture
def batch(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    return BatchIngester(
        registry=_registry(), inbox=inbox, raw_root=tmp_path / "raw",
        snapshot="2026-08-15",
    )


# --------------------------------------------------------------------------
# Filename convention
# --------------------------------------------------------------------------

def test_plain_filename():
    assert parse_filename("cpa2019.pdf") == ("cpa2019", "en", None)


def test_hindi_suffix():
    for name in ("cpa2019.hi.pdf", "cpa2019_hi.pdf", "cpa2019-hi.pdf"):
        assert parse_filename(name) == ("cpa2019", "hi", None)


def test_variant_suffix():
    assert parse_filename("mva1988__schedule.pdf") == ("mva1988", "en", "schedule")


def test_hindi_and_variant_together():
    assert parse_filename("mva1988__schedule.hi.pdf")[1] == "hi"


# --------------------------------------------------------------------------
# Inspection
# --------------------------------------------------------------------------

def test_as_on_date_is_extracted(tmp_path):
    """India Code stamps consolidated texts with the date the content is current
    to. That is a different fact from the download date."""
    p = _pdf(tmp_path / "a.pdf", "The Motor Vehicles Act, 1988 [As on the 21st May, 2025]")
    assert "2025" in (inspect_pdf(p)["as_on"] or "")


def test_scanned_pdf_is_flagged(tmp_path):
    p = _pdf(tmp_path / "s.pdf", " ", pages=3)
    assert any("scanned" in w for w in inspect_pdf(p)["warnings"])


def test_large_file_is_flagged_as_a_probable_bundle(tmp_path):
    p = _pdf(tmp_path / "b.pdf", "1. Text with enough characters to look real. " * 8,
             pages=70)
    assert any("bundle" in w for w in inspect_pdf(p)["warnings"])


def test_non_pdf_is_not_inspected(tmp_path):
    p = tmp_path / "x.txt"
    p.write_text("hello")
    assert inspect_pdf(p)["pages"] is None


# --------------------------------------------------------------------------
# Matching
# --------------------------------------------------------------------------

def test_exact_match(batch):
    _pdf(batch.inbox / "cpa2019.pdf")
    (found,) = batch.scan()
    assert found.matched and found.source_id == "cpa2019"


def test_match_is_case_insensitive(batch):
    _pdf(batch.inbox / "CPA2019.pdf")
    assert batch.scan()[0].source_id == "cpa2019"


def test_unknown_name_is_reported_with_suggestions(batch):
    _pdf(batch.inbox / "cpa.pdf")
    (found,) = batch.scan()
    assert not found.matched
    assert "cpa2019" in found.suggestions


def test_a_near_miss_is_never_auto_matched(batch):
    """Suggesting is safe; guessing is not. A wrong match writes a document into
    the wrong Act's provenance chain."""
    _pdf(batch.inbox / "cpa201.pdf")
    assert not batch.scan()[0].matched


def test_non_documents_are_ignored(batch):
    (batch.inbox / "notes.md").write_text("x")
    (batch.inbox / ".DS_Store").write_bytes(b"\x00")
    assert batch.scan() == []


def test_gated_source_is_flagged_but_still_ingestable(batch):
    _pdf(batch.inbox / "gratuity1972.pdf")
    (found,) = batch.scan()
    assert found.matched
    assert found.gate_warning and "labour_regime" in found.gate_warning


# --------------------------------------------------------------------------
# Apply
# --------------------------------------------------------------------------

def test_scan_writes_nothing(batch, tmp_path):
    _pdf(batch.inbox / "cpa2019.pdf")
    batch.scan()
    assert not (tmp_path / "raw" / "cpa2019").exists()


def test_apply_ingests_matched_files(batch, tmp_path):
    _pdf(batch.inbox / "cpa2019.pdf")
    _pdf(batch.inbox / "mva1988.pdf", "1. Different content entirely here.")
    results = batch.apply([c for c in batch.scan() if c.matched])
    assert len(results) == 2
    assert all(not isinstance(r, Exception) for _, r in results)
    assert (tmp_path / "raw" / "cpa2019").is_dir()
    assert (tmp_path / "raw" / "mva1988").is_dir()


def test_apply_skips_unmatched(batch):
    _pdf(batch.inbox / "mystery.pdf")
    assert batch.apply(batch.scan()) == []


def test_as_on_date_is_recorded_in_provenance(batch):
    _pdf(batch.inbox / "mva1988.pdf", "MV Act [As on the 21st May, 2025] text follows")
    ((_, result),) = batch.apply([c for c in batch.scan() if c.matched])
    assert "content_as_of" in result.record.notes


def test_reingesting_identical_bytes_is_detected(batch):
    _pdf(batch.inbox / "cpa2019.pdf")
    batch.apply([c for c in batch.scan() if c.matched])
    assert batch.scan()[0].already_ingested


def test_a_changed_file_is_not_treated_as_already_ingested(batch):
    _pdf(batch.inbox / "cpa2019.pdf")
    batch.apply([c for c in batch.scan() if c.matched])
    _pdf(batch.inbox / "cpa2019.pdf", "1. A revised and different provision.")
    assert not batch.scan()[0].already_ingested


def test_a_conflicting_file_fails_rather_than_overwriting(batch):
    """data/raw is append-only. Different bytes under the same name in the same
    snapshot must raise, not silently replace."""
    _pdf(batch.inbox / "cpa2019.pdf")
    batch.apply([c for c in batch.scan() if c.matched])
    _pdf(batch.inbox / "cpa2019.pdf", "1. Completely different provision text.")
    ((_, outcome),) = batch.apply([c for c in batch.scan() if c.matched])
    assert isinstance(outcome, FileExistsError)
