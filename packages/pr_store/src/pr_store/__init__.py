"""Statute store, facts table, authorities table (SQLite)."""

from .models import DocumentSpec, ParsedDocument, SectionRecord
from .parser import (
    PARSER_VERSION,
    body_band,
    clean_text,
    devanagari_ratio,
    in_margin,
    is_english_page,
    page_language,
    parse_bundle,
    parse_document,
    read_page,
    split_on_numbering_reset,
    strip_noise,
)
from .quality import Finding, QualityReport, check_document, coverage_ratio

__version__ = "0.1.0"

__all__ = [
    "PARSER_VERSION",
    "DocumentSpec",
    "Finding",
    "ParsedDocument",
    "QualityReport",
    "SectionRecord",
    "check_document",
    "clean_text",
    "coverage_ratio",
    "devanagari_ratio",
    "is_english_page",
    "page_language",
    "body_band",
    "in_margin",
    "parse_bundle",
    "parse_document",
    "read_page",
    "split_on_numbering_reset",
    "strip_noise",
]
