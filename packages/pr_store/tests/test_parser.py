"""Tests for the Gazette PDF parser (task 13).

Every case here corresponds to a bug that actually occurred while building the
parser against the real Consumer Protection Act. They exist so those bugs
cannot come back silently — a parser regression produces training data that is
wrong in the one way nothing downstream catches.
"""

from __future__ import annotations

import pymupdf
import pytest
from pr_store.models import SectionRecord
from pr_store.parser import (
    MAX_SECTION_NUMBER,
    SECTION_START_RE,
    body_band,
    clean_text,
    devanagari_ratio,
    in_margin,
    page_language,
    split_on_numbering_reset,
    strip_noise,
)

# --------------------------------------------------------------------------
# Text cleaning
# --------------------------------------------------------------------------

def test_running_head_is_stripped_even_when_glued_to_content():
    """The Gazette concatenates the page number, running head and part marker
    onto one line. Whole-line patterns miss it and the noise reaches the text."""
    raw = "2 THE GAZETTE OF INDIA EXTRAORDINARY [PART II—\nreal content here"
    out = strip_noise(raw)
    assert "GAZETTE" not in out
    assert "real content here" in out


def test_bare_page_numbers_are_dropped():
    assert "17" not in strip_noise("17\nsubstantive text")


def test_hyphenation_across_lines_is_repaired():
    assert "commencement" in clean_text("commence-\nment of the Act")


def test_soft_wrapped_lines_are_joined():
    out = clean_text("the District Commission shall not\nadmit a complaint")
    assert "shall not admit" in out


def test_sentence_boundaries_survive_cleaning():
    out = clean_text("First sentence.\nSecond sentence.")
    assert "First sentence." in out and "Second sentence." in out


# --------------------------------------------------------------------------
# Section detection
# --------------------------------------------------------------------------

def test_section_regex_matches_every_line_not_just_the_first():
    """Without re.MULTILINE, finditer only ever matches at offset 0 — which is
    how a 107-section Act first parsed as 7 sections."""
    text = "1. First provision here\n2. Second provision here\n3. Third one"
    assert [m.group(1) for m in SECTION_START_RE.finditer(text)] == ["1", "2", "3"]


def test_lettered_sections_are_recognised():
    text = "24A. Inserted provision\n24B. Another inserted one"
    assert [m.group(1) for m in SECTION_START_RE.finditer(text)] == ["24A", "24B"]


def test_four_digit_numbers_are_not_sections():
    """'the Consumer Protection Act, 2020. The Central Government...' must not
    yield a section 2020."""
    found = [m.group(1) for m in SECTION_START_RE.finditer("2020. The Central Government")]
    assert found == [] or all(int(f.rstrip("ABC")) <= MAX_SECTION_NUMBER for f in found)


# --------------------------------------------------------------------------
# Layout: the body band and recto/verso margins
# --------------------------------------------------------------------------

def test_body_band_is_detected(gazette_pdf, spec_factory):
    doc = pymupdf.open(gazette_pdf)
    band = body_band(doc, spec_factory(page_end=len(doc)))
    doc.close()
    assert band is not None
    lo, hi = band
    assert 100 < lo < 180, f"body band starts at {lo}"
    assert 400 < hi < 520, f"body band ends at {hi}"


def test_in_margin_accepts_both_sides():
    band = (141.0, 477.0)
    left = (58, 90, 105, 100, "Definitions.")
    right = (485, 90, 540, 100, "Definitions.")
    body = (141, 90, 477, 300, "2. In this Act ...")
    assert in_margin(left, band)
    assert in_margin(right, band), "right-hand margins must be recognised too"
    assert not in_margin(body, band)


def test_titles_are_recovered_from_both_page_sides(gazette_pdf, spec_factory, parse):
    """Gazette Acts alternate the margin side. A left-only boundary found 52 of
    107 titles on the real Act, with every even page contributing none."""
    doc = parse(gazette_pdf, spec_factory())
    titled = [s for s in doc.sections if s.section_title]
    assert len(titled) >= len(doc.sections) - 1, (
        f"only {len(titled)}/{len(doc.sections)} sections got a title — "
        "recto/verso margin handling has regressed"
    )


def test_titles_belong_to_the_right_sections(gazette_pdf, spec_factory, parse):
    """Sequential pairing shifts every label after a missed title. Positional
    matching must survive that."""
    doc = parse(gazette_pdf, spec_factory())
    by = {s.section_number: s.section_title for s in doc.sections}
    assert by["2"] == "Definitions"
    assert by["69"] == "Limitation period"
    assert by["35"] == "Manner in which complaint shall be made"


def test_a_merged_title_block_yields_no_title_rather_than_a_wrong_one(
    merged_title_pdf, spec_factory, parse
):
    """When PyMuPDF glues two margin notes together, the safe outcome is an
    honest None — never a confidently wrong label."""
    doc = parse(merged_title_pdf, spec_factory())
    by = {s.section_number: s.section_title for s in doc.sections}
    for number, title in by.items():
        if title:
            assert title.count(".") == 0 or len(title) < 90, (
                f"s.{number} looks like two merged titles: {title!r}"
            )


def test_single_column_documents_still_parse(single_column_pdf, spec_factory, parse):
    """Subordinate Rules have no marginal notes. They must not fail, they just
    produce untitled sections."""
    doc = parse(single_column_pdf, spec_factory(doc_type="rules"))
    assert len(doc.sections) >= 4
    assert doc.sections[0].section_number == "1"


# --------------------------------------------------------------------------
# Section content
# --------------------------------------------------------------------------

def test_sections_are_in_order_and_unique(gazette_pdf, spec_factory, parse):
    doc = parse(gazette_pdf, spec_factory())
    nums = [int(s.section_number.rstrip("ABC")) for s in doc.sections]
    assert nums == sorted(nums), "sections came out unordered"
    assert len(nums) == len(set(nums)), "duplicate section numbers"


def test_section_text_excludes_its_own_number(gazette_pdf, spec_factory, parse):
    doc = parse(gazette_pdf, spec_factory())
    s = next(s for s in doc.sections if s.section_number == "69")
    assert not s.text.startswith("69.")
    assert "two years" in s.text


def test_section_text_does_not_bleed_into_the_next(gazette_pdf, spec_factory, parse):
    """The failure that produces confidently wrong answers: one section's text
    carrying another section's content."""
    doc = parse(gazette_pdf, spec_factory())
    s69 = next(s for s in doc.sections if s.section_number == "69")
    assert "in derogation" not in s69.text


def test_page_furniture_never_reaches_section_text(gazette_pdf, spec_factory, parse):
    doc = parse(gazette_pdf, spec_factory())
    for s in doc.sections:
        assert "GAZETTE" not in s.text, f"{s.section_uid} carries a running head"


def test_provenance_is_attached_to_every_section(gazette_pdf, spec_factory, parse):
    doc = parse(gazette_pdf, spec_factory())
    for s in doc.sections:
        assert s.source_sha256 == "a" * 64
        assert s.snapshot_version == "2026-08-13"
        assert s.page_start >= 1


def test_section_uid_carries_act_and_language(gazette_pdf, spec_factory, parse):
    doc = parse(gazette_pdf, spec_factory())
    s = doc.sections[0]
    assert s.section_uid == f"testact.s{s.section_number}.en"


# --------------------------------------------------------------------------
# Bilingual handling
# --------------------------------------------------------------------------

def test_devanagari_ratio():
    assert devanagari_ratio("यह अधिनियम") > 0.9
    assert devanagari_ratio("This Act") == 0.0
    assert devanagari_ratio("") == 0.0


def test_page_language_detection(bilingual_pdf):
    doc = pymupdf.open(bilingual_pdf)
    langs = [page_language(p) for p in doc]
    doc.close()
    assert "en" in langs and "hi" in langs


def test_english_and_hindi_are_parsed_separately(bilingual_pdf, spec_factory, parse):
    """Both language versions are law. Parsing them together produced duplicate
    section numbers and Devanagari inside 'English' records."""
    en = parse(bilingual_pdf, spec_factory(), language="en")
    hi = parse(bilingual_pdf, spec_factory(), language="hi")

    assert en.sections and hi.sections
    assert all(devanagari_ratio(s.text) < 0.2 for s in en.sections)
    assert any(devanagari_ratio(s.text) > 0.5 for s in hi.sections)


def test_language_is_recorded_on_each_section(bilingual_pdf, spec_factory, parse):
    hi = parse(bilingual_pdf, spec_factory(), language="hi")
    assert all(s.language == "hi" for s in hi.sections)
    assert all(s.section_uid.endswith(".hi") for s in hi.sections)


# --------------------------------------------------------------------------
# Bundle splitting
# --------------------------------------------------------------------------

def test_numbering_reset_finds_document_boundaries(two_document_pdf):
    """One downloaded PDF often holds several documents, each restarting at
    section 1. Hand-guessed page ranges produced duplicate sections."""
    doc = pymupdf.open(two_document_pdf)
    ranges = split_on_numbering_reset(doc, 1, len(doc))
    doc.close()
    assert len(ranges) == 2, f"expected two documents, got {ranges}"


# --------------------------------------------------------------------------
# Validation at the record level
# --------------------------------------------------------------------------

def test_implausible_section_number_is_rejected():
    with pytest.raises(ValueError, match="section number"):
        SectionRecord(
            section_uid="x.sfoo.en", act_id="x", act_title="X",
            section_number="not-a-number", section_title=None,
            text="long enough to pass the length check",
            jurisdiction="IN", doc_type="act", source_id="s",
            source_sha256="a" * 64, snapshot_version="2026-08-13",
            page_start=1, page_end=1,
        )


def test_stub_text_is_rejected():
    with pytest.raises(ValueError, match="too short"):
        SectionRecord(
            section_uid="x.s1.en", act_id="x", act_title="X",
            section_number="1", section_title=None, text="short",
            jurisdiction="IN", doc_type="act", source_id="s",
            source_sha256="a" * 64, snapshot_version="2026-08-13",
            page_start=1, page_end=1,
        )
