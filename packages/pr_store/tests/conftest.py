"""Synthetic Gazette PDFs for parser tests.

The parser is tested against PDFs built here, not against downloaded law. Two
reasons: the suite must pass in a fresh clone where `data/raw/` is empty, and a
synthetic fixture lets us construct the exact pathologies that broke the real
parser — recto/verso margins, bilingual interleaving, merged title blocks, and
running heads glued onto content lines.

Geometry mirrors what was measured on the real Consumer Protection Act:

    page width 595
    body band  x = 141 .. 477
    margin     x = 58 .. 103    (odd pages)
               x = 490 .. 550   (even pages)

Text boxes are kept tight and well separated. Overlapping boxes make PyMuPDF
merge the margin into the body, which is a fixture artifact rather than
anything the real documents do.
"""

from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest

PAGE_W, PAGE_H = 595, 842
BODY_LO, BODY_HI = 141.0, 477.0
MARGIN_LEFT, MARGIN_LEFT_W = 58.0, 45.0
MARGIN_RIGHT, MARGIN_RIGHT_W = 492.0, 60.0
FONT_SIZE = 8
ROW_HEIGHT = 200.0

RUNNING_HEAD = "THE GAZETTE OF INDIA EXTRAORDINARY [PART II-"

# A Devanagari-capable font, if this machine has one. Base-14 fonts render
# Devanagari as '?', so Hindi fixtures are skipped where none is available.
DEVANAGARI_FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/DevanagariMT.ttc",
    "/System/Library/Fonts/Supplemental/Devanagari Sangam MN.ttc",
    "/System/Library/Fonts/Supplemental/Kohinoor.ttc",
    "/usr/share/fonts/truetype/lohit-devanagari/Lohit-Devanagari.ttf",
    "/usr/share/fonts/truetype/Sarai/Sarai.ttf",
]


def devanagari_font() -> str | None:
    for candidate in DEVANAGARI_FONT_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    return None


# Margins are written in a second pass, slightly higher and slightly smaller.
# Written on the same baseline in one pass, PyMuPDF merges the margin block into
# the body block — an artifact of how we build the fixture, not of the real
# documents. The offset stays far inside TITLE_Y_TOLERANCE.
MARGIN_Y_OFFSET = 2.0
MARGIN_FONT_SIZE = 7


def _put(page, x, y, text, width, height, fontfile=None, size=FONT_SIZE):
    rect = pymupdf.Rect(x, y, x + width, y + height)
    kwargs = {"fontsize": size}
    if fontfile:
        kwargs.update(fontname="deva", fontfile=fontfile)
    else:
        kwargs.update(fontname="helv")
    page.insert_textbox(rect, text, **kwargs)


def build_gazette_pdf(
    path,
    sections: list[tuple[str, str, str]],
    *,
    per_page: int = 3,
    recto_verso: bool = True,
    running_heads: bool = True,
    fontfile: str | None = None,
    merge_titles_on_page: int | None = None,
):
    """Write a Gazette-style PDF.

    sections: (number, title, body) triples.
    recto_verso: margins alternate sides, as the real Act does.
    merge_titles_on_page: glue two margin titles into one block, reproducing
        the PyMuPDF behaviour seen on p36 of the real Act.
    """
    doc = pymupdf.open()
    for start in range(0, len(sections), per_page):
        chunk = sections[start : start + per_page]
        page = doc.new_page(width=PAGE_W, height=PAGE_H)
        page_no = len(doc)
        on_left = (not recto_verso) or (page_no % 2 == 1)
        mx, mw = (
            (MARGIN_LEFT, MARGIN_LEFT_W) if on_left else (MARGIN_RIGHT, MARGIN_RIGHT_W)
        )

        if running_heads:
            _put(page, BODY_LO, 30, f"{page_no} {RUNNING_HEAD}", BODY_HI - BODY_LO, 14)

        # Pass 1 — body text.
        y = 80.0
        for number, _title, body in chunk:
            _put(page, BODY_LO, y, f"{number}. {body}", BODY_HI - BODY_LO, 120, fontfile)
            y += ROW_HEIGHT

        # Pass 2 — marginal notes.
        y = 80.0
        skip_next_title = False
        for idx, (_number, title, _body) in enumerate(chunk):
            label = f"{title}."
            if merge_titles_on_page == page_no and idx == 0 and len(chunk) > 1:
                label = f"{title}. {chunk[1][1]}."
                skip_next_title = True
            elif skip_next_title:
                skip_next_title = False
                y += ROW_HEIGHT
                continue
            _put(page, mx, y - MARGIN_Y_OFFSET, label, mw, 70, fontfile,
                 size=MARGIN_FONT_SIZE)
            y += ROW_HEIGHT
    doc.save(path)
    doc.close()
    return path


ENGLISH_SECTIONS = [
    ("1", "Short title and commencement",
     "This Act may be called the Test Consumer Act, 2019."),
    ("2", "Definitions",
     'In this Act, unless the context otherwise requires, "defect" means any '
     "fault or imperfection in the quality of any goods."),
    ("3", "Central Council",
     "The Central Government shall establish a Central Council to advise on "
     "the promotion of consumer rights."),
    ("4", "Procedure for meetings",
     "The Central Council shall meet as and when necessary, at such time as "
     "the Chairperson may think fit."),
    ("5", "Objects of Council",
     "The objects of the Central Council shall be to render advice on the "
     "protection of the rights of consumers."),
    ("6", "State Councils",
     "Every State Government shall establish a State Consumer Protection "
     "Council for that State."),
    ("35", "Manner in which complaint shall be made",
     "A complaint in relation to any goods sold may be filed with a District "
     "Commission by the consumer to whom such goods are sold."),
    ("69", "Limitation period",
     "The District Commission shall not admit a complaint unless it is filed "
     "within two years from the date on which the cause of action has arisen."),
    ("100", "Act not in derogation of any other law",
     "The provisions of this Act shall be in addition to and not in derogation "
     "of any other law for the time being in force."),
]

HINDI_SECTIONS = [
    ("1", "Sankshipt naam",
     "यह अधिनियम परीक्षण उपभोक्ता अधिनियम कहा जा सकता है और यह पूरे भारत पर लागू होगा।"),
    ("2", "Paribhasha",
     "इस अधिनियम में जब तक संदर्भ से अन्यथा अपेक्षित न हो त्रुटि से अभिप्राय है।"),
    ("3", "Kendriya Parishad",
     "केंद्रीय सरकार एक केंद्रीय परिषद की स्थापना करेगी जो सलाह देगी।"),
]


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------

@pytest.fixture
def gazette_pdf(tmp_path):
    """Nine sections, recto/verso margins, running heads. The realistic case."""
    return build_gazette_pdf(tmp_path / "gazette.pdf", ENGLISH_SECTIONS)


@pytest.fixture
def single_column_pdf(tmp_path):
    """Subordinate Rules layout: no marginal notes at all."""
    doc = pymupdf.open()
    page = doc.new_page(width=PAGE_W, height=PAGE_H)
    y = 80.0
    for number, title, body in ENGLISH_SECTIONS[:5]:
        _put(page, BODY_LO, y, f"{number}. {title}.- {body}", BODY_HI - BODY_LO, 120)
        y += 140
    path = tmp_path / "rules.pdf"
    doc.save(path)
    doc.close()
    return path


@pytest.fixture
def bilingual_pdf(tmp_path):
    """English pages followed by the Hindi version of the same document."""
    font = devanagari_font()
    if font is None:
        pytest.skip("no Devanagari-capable font on this machine")

    en = build_gazette_pdf(tmp_path / "_en.pdf", ENGLISH_SECTIONS[:3], per_page=1)
    hi = build_gazette_pdf(
        tmp_path / "_hi.pdf", HINDI_SECTIONS, per_page=1, fontfile=font
    )
    merged = pymupdf.open(en)
    merged.insert_pdf(pymupdf.open(hi))
    path = tmp_path / "bilingual.pdf"
    merged.save(path)
    merged.close()
    return path


@pytest.fixture
def merged_title_pdf(tmp_path):
    """Two margin titles glued into one block — the real p36 pathology."""
    return build_gazette_pdf(
        tmp_path / "merged.pdf", ENGLISH_SECTIONS[:6], merge_titles_on_page=1
    )


@pytest.fixture
def two_document_pdf(tmp_path):
    """One file holding two documents, each restarting at section 1."""
    a = build_gazette_pdf(tmp_path / "_a.pdf", ENGLISH_SECTIONS[:3], per_page=1)
    b = build_gazette_pdf(tmp_path / "_b.pdf", ENGLISH_SECTIONS[:3], per_page=1)
    merged = pymupdf.open(a)
    merged.insert_pdf(pymupdf.open(b))
    path = tmp_path / "two_docs.pdf"
    merged.save(path)
    merged.close()
    return path


@pytest.fixture
def spec_factory():
    from pr_store.models import DocumentSpec

    def _make(**kw):
        base = dict(
            act_id="testact",
            act_title="Test Consumer Act, 2019",
            doc_type="act",
            page_start=1,
            page_end=99,
            languages=["en"],
        )
        base.update(kw)
        return DocumentSpec(**base)

    return _make


@pytest.fixture
def parse():
    """Parse a fixture PDF and return the ParsedDocument."""
    from pr_store.parser import parse_document

    def _parse(path, spec, language="en"):
        doc = pymupdf.open(path)
        try:
            spec = spec.model_copy(update={"page_end": min(spec.page_end, len(doc))})
            return parse_document(
                doc,
                spec,
                source_id="testsrc",
                source_sha256="a" * 64,
                snapshot_version="2026-08-13",
                language=language,
            )
        finally:
            doc.close()

    return _parse
