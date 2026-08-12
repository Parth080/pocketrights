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
from dataclasses import dataclass
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
    re.compile(r"\[?\s*PART\s+I{1,3}\s*[—–-]?\s*SEC\.?\s*\d*\s*\(?\w*\)?\s*\]?", re.I),
    re.compile(r"^\s*SEC\.\s*\d+\s*\]", re.I),
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
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)              # word-break hyphen
    text = re.sub(r"(?<![.;:—\-])\n(?=[a-z])", " ", text)      # soft wrap
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


@dataclass
class PageContent:
    number: int
    margin: list[str]
    body: str


def margin_candidates(doc: pymupdf.Document, spec: DocumentSpec) -> list[float]:
    """Plausible margin/body boundaries for a document, widest gap first.

    Looks at every block left-edge across the document's pages and finds gaps
    between low-x clusters. Only clusters whose blocks are narrow qualify — a
    margin holds short titles, not paragraphs.
    """
    lefts: list[tuple[float, float]] = []   # (x0, width)
    for i in range(spec.page_start - 1, min(spec.page_end, len(doc))):
        for b in doc[i].get_text("blocks"):
            if b[4].strip():
                lefts.append((b[0], b[2] - b[0]))
    if not lefts:
        return []

    page_width = doc[spec.page_start - 1].rect.width
    xs = sorted({round(x) for x, _ in lefts})

    out = []
    for a, b in zip(xs, xs[1:], strict=False):
        if b - a < 25:
            continue
        left_blocks = [(x, w) for x, w in lefts if x <= a]
        right_blocks = [(x, w) for x, w in lefts if x >= b]
        if not left_blocks or len(right_blocks) < len(left_blocks):
            continue
        median_width = sorted(w for _, w in left_blocks)[len(left_blocks) // 2]
        if median_width > page_width * 0.35:
            continue                      # too wide to be a margin
        out.append(((a + b) / 2, b - a))
    out.sort(key=lambda t: -t[1])
    return [x for x, _ in out]


def read_page(page: pymupdf.Page, page_number: int, boundary: float | None) -> PageContent:
    blocks = [b for b in page.get_text("blocks") if b[4].strip()]
    ordered = sorted(blocks, key=lambda b: (round(b[1]), b[0]))

    if boundary is None:
        return PageContent(page_number, [], clean_text("\n".join(b[4] for b in ordered)))

    titles, body = [], []
    for b in ordered:
        # Classify on the LEFT edge. Margin titles start far left but often
        # extend past the boundary; testing the right edge misses all of them.
        if b[0] <= boundary:
            t = " ".join(b[4].split())
            t = strip_noise(t).strip()
            if t and MARGIN_TITLE_RE.match(t):
                titles.append(t)
        else:
            body.append(b[4])
    return PageContent(page_number, titles, clean_text("\n".join(body)))


@dataclass
class _Attempt:
    boundary: float | None
    pages: list[PageContent]
    marks: list[tuple[int, str, int]]
    joined: str
    titles: list[str]

    @property
    def score(self) -> tuple[int, int]:
        """More sections is better; ties broken by how ascending they are."""
        nums = [int(re.match(r"\d+", n).group()) for _, n, _ in self.marks]
        ascending = sum(1 for a, b in zip(nums, nums[1:], strict=False) if b >= a)
        return (len(self.marks), ascending)


def _attempt(
    doc: pymupdf.Document,
    spec: DocumentSpec,
    boundary: float | None,
    language: str = "en",
) -> _Attempt:
    pages = [
        read_page(doc[i], i + 1, boundary)
        for i in range(spec.page_start - 1, min(spec.page_end, len(doc)))
        if page_language(doc[i]) == language
    ]
    marks, parts, offset = [], [], 0
    for p in pages:
        for m in SECTION_START_RE.finditer(p.body):
            marks.append((offset + m.start(), m.group(1), p.number))
        parts.append(p.body)
        offset += len(p.body) + 1
    titles = [t for p in pages for t in p.margin]
    return _Attempt(boundary, pages, marks, "\n".join(parts), titles)


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
    tried = [
        _attempt(doc, spec, b, language)
        for b in [*margin_candidates(doc, spec), None]
    ]
    best = max(tried, key=lambda a: a.score)

    warnings: list[str] = []
    if best.boundary is None:
        warnings.append("parsed as single-column (no usable margin detected)")
    else:
        warnings.append(f"parsed as two-column, margin boundary x={best.boundary:.0f}")

    sections: list[SectionRecord] = []
    for idx, (start, number, page_no) in enumerate(best.marks):
        end = best.marks[idx + 1][0] if idx + 1 < len(best.marks) else len(best.joined)
        body = SECTION_START_RE.sub("", best.joined[start:end].strip(), count=1).strip()
        if len(body) < 10:
            warnings.append(f"s.{number}: body too short ({len(body)} chars), skipped")
            continue

        title = best.titles[idx].rstrip(". ").strip() if idx < len(best.titles) else None
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

    if best.boundary is not None and len(best.titles) != len(best.marks):
        warnings.append(
            f"margin titles ({len(best.titles)}) != section starts ({len(best.marks)}); "
            "title-to-section pairing may be offset"
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
