"""Gazette-layout PDF parser — task 13.

Indian Gazette Acts use a two-column layout: section titles sit in a narrow left
margin, body text in a wide right column. Flattened text extraction interleaves
them, so this parser works positionally.

    x=58–99    "Definitions."                            <- margin: the title
    x=142–477  "2. In this Act, unless the context ..."  <- body: the text

Subordinate Rules bundled in the same file use a single column instead. Rather
than guess the layout from geometry alone — which misfires, because sub-clause
indents are more numerous than body indents and skew any modal estimate — the
parser **tries both layouts and keeps whichever produces a sane section
sequence.** Detection by outcome, not by heuristic.

**Everything here is built to fail loudly.** A parser that silently drops a
section, or lets one section's text bleed into the next, produces training data
that is wrong in the one way nothing downstream catches: the citation exists,
the number checks out, and the answer is still false. So every extraction comes
with a quality report (see `quality.py`), and a document that fails a blocking
check does not reach the store.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from .models import DocumentSpec, ParsedDocument, SectionRecord

PARSER_VERSION = "1.1"

# Running heads and page furniture. Matched as SUBSTRINGS — the Gazette often
# concatenates the page number, the running head and the part marker onto one
# line ("2 THE GAZETTE OF INDIA EXTRAORDINARY [PART II—"), so anchored
# whole-line patterns miss them and the noise survives into section text.
NOISE_SUBSTRINGS = [
    re.compile(r"THE GAZETTE OF INDIA\s*:?\s*EXTRAORDINARY", re.I),
    # "SEC." is OPTIONAL. Many Gazette pages carry only "[PART II—", and
    # requiring SEC left that fragment embedded in 16 sections of the real
    # Consumer Protection Act.
    re.compile(
        r"\[?\s*PART\s+I{1,3}\s*(?:[—–-]\s*)?(?:SEC\.?\s*\d*\s*\(?\w*\)?)?\s*\]?",
        re.I,
    ),
    re.compile(r"^\s*SEC\.\s*\d+\s*\]", re.I),
    re.compile(r"भारत का राजपत्र\s*:?\s*असाधारण"),      # the Hindi running head
]
NOISE_ONLY_LINES = [
    re.compile(r"^\s*\d{1,4}\s*$"),        # bare page number
    re.compile(r"^\s*$"),
]

# "2. In this Act, ..."  ·  "35. (1) A complaint ..."  ·  "24A. ..."
# MULTILINE is essential: without it `finditer` only ever matches at offset 0.
SECTION_START_RE = re.compile(r"^[ \t]*(\d{1,3}[A-Z]{0,2})\s*\.\s+(?=\S)", re.M)

# A four-digit "section" is a year inside a citation, not a provision.
# Capping at three digits is safe: no Indian Act has a section 1000.
MAX_SECTION_NUMBER = 999

MARGIN_TITLE_RE = re.compile(r"^[A-Z][A-Za-z0-9 ,;:()'/&.\-]{2,150}$")


DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")


def devanagari_ratio(text: str) -> float:
    """Fraction of letters that are Devanagari."""
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if DEVANAGARI_RE.match(c)) / len(letters)


def page_language(page: pymupdf.Page, threshold: float = 0.25) -> str:
    """Which language version of the document this page belongs to.

    Gazette bundles carry the authoritative Hindi text interleaved with the
    English. Both are law. We parse both, tag each section with its language,
    and keep them as separate records sharing an act_id and section number —
    so a citation resolves in either language.
    """
    return "hi" if devanagari_ratio(page.get_text()) >= threshold else "en"


def is_english_page(page: pymupdf.Page, threshold: float = 0.25) -> bool:
    return page_language(page, threshold) == "en"


def strip_noise(raw: str) -> str:
    out = []
    for line in raw.splitlines():
        for pat in NOISE_SUBSTRINGS:
            line = pat.sub(" ", line)
        if any(p.match(line) for p in NOISE_ONLY_LINES):
            continue
        out.append(line.rstrip())
    return "\n".join(out)


def clean_text(raw: str) -> str:
    """Strip page furniture, repair hyphenation, normalise whitespace."""
    text = strip_noise(raw)
    # Word-break hyphens occur between lowercase letters. Matching any word
    # character let "…[PART II-\n1. This Act…" collapse into "II1.", which hid
    # the start of the next section.
    text = re.sub(r"([a-z])-\n([a-z])", r"\1\2", text)        # word-break hyphen
    text = re.sub(r"(?<![.;:—\-])\n(?=[a-z])", " ", text)      # soft wrap
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


@dataclass
class PageContent:
    number: int
    margin: list[tuple[float, str]]      # (y, title)
    body: str
    body_blocks: list[tuple[float, str]] = field(default_factory=list)  # (y, text)

    @property
    def margin_titles(self) -> list[str]:
        return [t for _, t in self.margin]


BODY_WIDTH_FRACTION = 0.45   # a block this wide, relative to the page, is body


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    return ordered[mid] if n % 2 else (ordered[mid - 1] + ordered[mid]) / 2


def body_band(
    doc: pymupdf.Document, spec: DocumentSpec, language: str = "en"
) -> tuple[float, float] | None:
    """The horizontal span occupied by body text; blocks outside it are margins.

    Gazette Acts are typeset like a book: marginal notes sit in the OUTER
    margin, so they are on the LEFT of odd pages and the RIGHT of even ones.
    Detecting a single left-hand boundary finds only half of them — on the
    Consumer Protection Act that was 52 of 107 titles, with every even page
    contributing none.

    So instead of one boundary we derive a band from the blocks wide enough to
    be running text, and treat anything lying wholly outside it, on either
    side, as marginalia.

    **Median, not min/max.** A single merged block spanning both margins, or a
    Hindi page with a different layout, is enough to collapse a min/max band to
    the full page width — after which every title is misread as body. The band
    is also computed only over the pages that will actually be parsed, since
    the two language versions are typeset differently.
    """
    page_width = doc[spec.page_start - 1].rect.width
    threshold = page_width * BODY_WIDTH_FRACTION

    lo_edges, hi_edges = [], []
    for i in range(spec.page_start - 1, min(spec.page_end, len(doc))):
        if page_language(doc[i]) != language:
            continue
        for b in doc[i].get_text("blocks"):
            if b[4].strip() and (b[2] - b[0]) >= threshold:
                lo_edges.append(b[0])
                hi_edges.append(b[2])
    if len(lo_edges) < 3:
        return None
    return (_median(lo_edges), _median(hi_edges))


def in_margin(block, band: tuple[float, float]) -> bool:
    """True when a block sits wholly outside the body band, on either side."""
    lo, hi = band
    return block[2] <= lo or block[0] >= hi


def read_page(
    page: pymupdf.Page, page_number: int, band: tuple[float, float] | None
) -> PageContent:
    blocks = [b for b in page.get_text("blocks") if b[4].strip()]
    ordered = sorted(blocks, key=lambda b: (round(b[1]), b[0]))

    if band is None:
        blocks_yt = [(b[1], clean_text(b[4])) for b in ordered]
        return PageContent(
            page_number,
            [],
            clean_text("\n".join(b[4] for b in ordered)),
            [(y, txt) for y, txt in blocks_yt if txt],
        )

    titles: list[tuple[float, str]] = []
    body: list[str] = []
    body_blocks: list[tuple[float, str]] = []
    for b in ordered:
        if in_margin(b, band):
            # The margin also carries cross-references to other Acts
            # ("2 of 1974.") and printer marks. MARGIN_TITLE_RE filters those.
            label = strip_noise(" ".join(b[4].split())).strip()
            if label and MARGIN_TITLE_RE.match(label):
                titles.append((b[1], label))
        else:
            body.append(b[4])
            cleaned = clean_text(b[4])
            if cleaned:
                body_blocks.append((b[1], cleaned))
    return PageContent(page_number, titles, clean_text("\n".join(body)), body_blocks)


TITLE_Y_TOLERANCE = 26.0    # points; a margin title sits level with its section


def _y_of(page: PageContent, number: str) -> float | None:
    """Vertical position of the body block that starts section `number`."""
    prefix = re.compile(rf"^\s*{re.escape(number)}\s*\.\s")
    for y, text in page.body_blocks:
        if prefix.match(text):
            return y
    return None


@dataclass
class _Attempt:
    band: tuple[float, float] | None
    pages: list[PageContent]
    marks: list[tuple[int, str, int, float | None]]
    joined: str
    page_objs: list[PageContent]

    @property
    def score(self) -> tuple[int, int]:
        """More sections is better; ties broken by how ascending they are."""
        nums = [int(re.match(r"\d+", n).group()) for _, n, _, _ in self.marks]
        ascending = sum(1 for a, b in zip(nums, nums[1:], strict=False) if b >= a)
        return (len(self.marks), ascending)

    def title_for(self, page_number: int, y: float | None) -> str | None:
        """The margin title level with this section, if there is one.

        Positional matching, not sequential: a missed title costs one label
        rather than shifting every label after it.
        """
        if y is None:
            return None
        page = next((p for p in self.page_objs if p.number == page_number), None)
        if page is None or not page.margin:
            return None
        best_y, best = min(page.margin, key=lambda ty: abs(ty[0] - y))
        if abs(best_y - y) > TITLE_Y_TOLERANCE:
            return None
        return best.rstrip(". ").strip() or None


def _attempt(
    doc: pymupdf.Document,
    spec: DocumentSpec,
    band: tuple[float, float] | None,
    language: str = "en",
) -> _Attempt:
    pages = [
        read_page(doc[i], i + 1, band)
        for i in range(spec.page_start - 1, min(spec.page_end, len(doc)))
        if page_language(doc[i]) == language
    ]
    marks, parts, offset = [], [], 0
    for p in pages:
        for m in SECTION_START_RE.finditer(p.body):
            marks.append(
                (offset + m.start(), m.group(1), p.number, _y_of(p, m.group(1)))
            )
        parts.append(p.body)
        offset += len(p.body) + 1
    return _Attempt(band, pages, marks, "\n".join(parts), pages)


def parse_document(
    doc: pymupdf.Document,
    spec: DocumentSpec,
    *,
    source_id: str,
    source_sha256: str,
    snapshot_version: str,
    language: str = "en",
) -> ParsedDocument:
    """Extract every section of one logical document, in one language."""
    band = body_band(doc, spec, language)
    tried = [_attempt(doc, spec, b, language) for b in [band, None] if b or b is None]
    best = max(tried, key=lambda a: a.score)

    warnings: list[str] = []
    if best.band is None:
        warnings.append("parsed as single-column (no usable body band detected)")
    else:
        warnings.append(
            f"parsed with body band x={best.band[0]:.0f}-{best.band[1]:.0f}; "
            "blocks outside it on either side treated as marginalia"
        )

    sections: list[SectionRecord] = []
    for idx, (start, number, page_no, y) in enumerate(best.marks):
        end = best.marks[idx + 1][0] if idx + 1 < len(best.marks) else len(best.joined)
        body = SECTION_START_RE.sub("", best.joined[start:end].strip(), count=1).strip()
        if len(body) < 10:
            warnings.append(f"s.{number}: body too short ({len(body)} chars), skipped")
            continue

        title = best.title_for(page_no, y)
        try:
            sections.append(
                SectionRecord(
                    section_uid=f"{spec.act_id}.s{number}.{language}",
                    act_id=spec.act_id,
                    act_title=spec.act_title,
                    section_number=number,
                    section_title=title or None,
                    text=body,
                    language=language,
                    jurisdiction=spec.jurisdiction,
                    doc_type=spec.doc_type,
                    source_id=source_id,
                    source_sha256=source_sha256,
                    snapshot_version=snapshot_version,
                    page_start=page_no,
                    page_end=(
                        best.marks[idx + 1][2] if idx + 1 < len(best.marks) else spec.page_end
                    ),
                    content_as_of=spec.content_as_of,
                    parser_version=PARSER_VERSION,
                )
            )
        except ValueError as exc:
            warnings.append(f"s.{number}: rejected — {exc}")

    if best.band is not None:
        found = sum(1 for s in sections if s.section_title)
        available = sum(len(p.margin) for p in best.page_objs)
        if available and found < available * 0.6:
            warnings.append(
                f"only {found} of {available} margin titles matched a section by "
                "position; check TITLE_Y_TOLERANCE for this layout"
            )

    return ParsedDocument(
        act_id=spec.act_id,
        act_title=spec.act_title,
        doc_type=spec.doc_type,
        jurisdiction=spec.jurisdiction,
        page_start=spec.page_start,
        page_end=spec.page_end,
        sections=sections,
        content_as_of=spec.content_as_of,
        language=language,
        warnings=warnings,
    )


def parse_bundle(
    pdf_path: Path,
    specs: list[DocumentSpec],
    *,
    source_id: str,
    source_sha256: str,
    snapshot_version: str,
) -> list[ParsedDocument]:
    doc = pymupdf.open(pdf_path)
    try:
        out = []
        for spec in specs:
            if spec.skip:
                continue
            for lang in spec.languages:
                parsed = parse_document(
                    doc, spec,
                    source_id=source_id,
                    source_sha256=source_sha256,
                    snapshot_version=snapshot_version,
                    language=lang,
                )
                if parsed.sections:
                    out.append(parsed)
        return out
    finally:
        doc.close()


def split_on_numbering_reset(
    doc: pymupdf.Document,
    page_start: int,
    page_end: int,
    *,
    min_pages: int = 1,
) -> list[tuple[int, int]]:
    """Find document boundaries inside a page range by numbering resets.

    Subordinate Rules bundled into one file each restart at section 1. Rather
    than hand-guess page ranges — which produced duplicate section numbers on
    the first attempt — locate the pages where numbering falls back to 1.

    Returns 1-based inclusive (start, end) page pairs.
    """
    first_num: dict[int, int] = {}
    for i in range(page_start - 1, min(page_end, len(doc))):
        if not is_english_page(doc[i]):
            continue
        nums = [
            int(m.group(1))
            for m in SECTION_START_RE.finditer(clean_text(doc[i].get_text()))
            if int(m.group(1)) <= MAX_SECTION_NUMBER
        ]
        if nums:
            first_num[i + 1] = nums[0]

    starts = [page_start]
    pages = sorted(first_num)
    for prev, cur in zip(pages, pages[1:], strict=False):
        if first_num[cur] == 1 and first_num[prev] > 1 and cur - starts[-1] >= min_pages:
            starts.append(cur)

    return [
        (s, (starts[i + 1] - 1) if i + 1 < len(starts) else page_end)
        for i, s in enumerate(starts)
    ]
