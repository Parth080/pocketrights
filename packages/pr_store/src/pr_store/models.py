"""Section records — the unit everything downstream is built from.

One row per legal provision. Task 13 produces these; task 14 stores them.

The whole project rests on this being correct. A section whose text has bled
into its neighbour, or whose number is wrong, produces training data that is
confidently wrong in a way no later check catches — the citation exists, the
number matches, and the answer is still nonsense.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

DocType = Literal["act", "rules", "regulation", "notification", "circular"]
Language = Literal["en", "hi"]

# 69 · 2(11) · 35(1)(a) · 24A · 2A(3)
SECTION_NUMBER_RE = re.compile(r"^\d+[A-Z]{0,2}(\(\w{1,4}\))*$")


class SectionRecord(BaseModel):
    """One section of one legal document."""

    section_uid: str          # "cpa2019.s69.en"
    act_id: str               # "cpa2019"
    act_title: str
    section_number: str       # "69", "2", "35"
    section_title: str | None
    text: str
    language: Language = "en"
    jurisdiction: str
    doc_type: DocType

    # provenance — every record traces to bytes on disk
    source_id: str
    source_sha256: str
    snapshot_version: str
    page_start: int
    page_end: int

    # temporal — two distinct dates, and conflating them overstates currency
    content_as_of: str | None = None    # what the DOCUMENT says it is current to
    effective_from: str | None = None
    effective_until: str | None = None

    char_count: int = 0
    parser_version: str = "1.0"
    warnings: list[str] = Field(default_factory=list)

    @field_validator("section_number")
    @classmethod
    def _wellformed_number(cls, v: str) -> str:
        if not SECTION_NUMBER_RE.match(v):
            raise ValueError(f"implausible section number: {v!r}")
        return v

    @field_validator("text")
    @classmethod
    def _text_is_substantive(cls, v: str) -> str:
        if len(v.strip()) < 10:
            raise ValueError(f"section text too short to be real: {v!r}")
        return v

    def model_post_init(self, _ctx) -> None:
        object.__setattr__(self, "char_count", len(self.text))


class ParsedDocument(BaseModel):
    """One logical document extracted from a source file.

    A single downloaded PDF may contain several of these — the India Code
    Consumer Protection bundle holds the Act, a corrigendum, and six sets of
    Rules in one file.
    """

    act_id: str
    act_title: str
    doc_type: DocType
    jurisdiction: str
    page_start: int
    page_end: int
    sections: list[SectionRecord] = Field(default_factory=list)
    content_as_of: str | None = None
    warnings: list[str] = Field(default_factory=list)

    language: Language = "en"

    @property
    def section_numbers(self) -> list[str]:
        return [s.section_number for s in self.sections]

    @property
    def total_chars(self) -> int:
        return sum(s.char_count for s in self.sections)


class DocumentSpec(BaseModel):
    """Where a logical document sits inside a bundled source file.

    Page ranges are 1-based and inclusive, matching what a human sees in a PDF
    viewer — these get checked by hand, so they should read the same way.
    """

    act_id: str
    act_title: str
    doc_type: DocType
    page_start: int
    page_end: int
    jurisdiction: str = "IN"
    expected_sections: int | None = None   # if known, the parser asserts it
    content_as_of: str | None = None
    languages: list[Language] = ["en", "hi"]
    skip: bool = False
    skip_reason: str | None = None
    note: str | None = None
