"""Quality gates for parsed sections.

The failure mode this exists to prevent: a section whose text has bled into its
neighbour, or whose number is wrong, becomes training data that is confidently
false in the one way nothing downstream catches. The citation-existence check
passes — the section really is in the store. The numeric check passes — the
figure really is in the facts table. The answer is still wrong.

So parsing is not trusted on the basis that it ran without an exception. Every
document gets scored against explicit checks, and anything that fails a
BLOCKING check does not reach the store.

Severity:
  * **blocking** — the corpus would be wrong. Refuse to load.
  * **warning**  — probably fine, look at it.
  * **info**     — recorded for the audit trail.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Literal

from .models import ParsedDocument

Severity = Literal["blocking", "warning", "info"]

# Page furniture that must never survive into section text.
LEAKED_NOISE = [
    re.compile(r"GAZETTE OF INDIA", re.I),
    # Bare "[PART II—" counts. The earlier pattern required SEC and so missed
    # the very leak it was written to catch.
    re.compile(r"\[\s*PART\s+I{1,3}\b", re.I),
    re.compile(r"भारत का राजपत्र"),
]

# Symptoms of broken PDF extraction.
MOJIBAKE = re.compile(r"[�\x00-\x08\x0b\x0c\x0e-\x1f]")


@dataclass
class Finding:
    severity: Severity
    check: str
    message: str
    section_uid: str | None = None


@dataclass
class QualityReport:
    act_id: str
    findings: list[Finding] = field(default_factory=list)
    stats: dict[str, float | int] = field(default_factory=dict)

    def add(self, severity: Severity, check: str, message: str, uid: str | None = None):
        self.findings.append(Finding(severity, check, message, uid))

    @property
    def blocking(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "blocking"]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "warning"]

    @property
    def ok(self) -> bool:
        return not self.blocking

    def summary(self) -> str:
        n_block, n_warn = len(self.blocking), len(self.warnings)
        verdict = "PASS" if self.ok else "BLOCKED"
        return (
            f"{self.act_id}: {verdict} — {self.stats.get('sections', 0)} sections, "
            f"{n_block} blocking, {n_warn} warnings"
        )


def _numeric_prefix(section_number: str) -> int:
    m = re.match(r"^(\d+)", section_number)
    return int(m.group(1)) if m else 0


def check_document(
    doc: ParsedDocument,
    *,
    expected_sections: int | None = None,
    min_section_chars: int = 25,
    max_section_chars: int = 40_000,
) -> QualityReport:
    """Run every quality check over one parsed document."""
    rep = QualityReport(act_id=doc.act_id)
    sections = doc.sections

    rep.stats = {
        "sections": len(sections),
        "total_chars": doc.total_chars,
        "mean_chars": round(doc.total_chars / len(sections), 1) if sections else 0,
        "titled": sum(1 for s in sections if s.section_title),
    }

    # ---- nothing at all -------------------------------------------------
    if not sections:
        rep.add("blocking", "empty", "no sections extracted")
        return rep

    # ---- duplicate section numbers --------------------------------------
    counts = Counter(s.section_number for s in sections)
    for number, n in counts.items():
        if n > 1:
            rep.add(
                "blocking", "duplicate_section",
                f"section {number} extracted {n} times — numbering or splitting is wrong",
            )

    # ---- ordering and gaps ----------------------------------------------
    nums = [_numeric_prefix(s.section_number) for s in sections]
    if nums != sorted(nums):
        rep.add(
            "blocking", "out_of_order",
            "sections are not in ascending order — the split is misaligned",
        )

    present = set(nums)
    span = range(min(nums), max(nums) + 1)
    missing = sorted(set(span) - present)
    if missing:
        severity: Severity = "blocking" if len(missing) > len(span) * 0.10 else "warning"
        rep.add(
            severity, "missing_sections",
            f"{len(missing)} gap(s) in {min(nums)}–{max(nums)}: "
            f"{missing[:15]}{' …' if len(missing) > 15 else ''}",
        )

    # ---- expected count --------------------------------------------------
    if expected_sections is not None:
        drift = abs(len(sections) - expected_sections)
        if drift > max(2, expected_sections * 0.05):
            rep.add(
                "blocking", "count_mismatch",
                f"expected ~{expected_sections} sections, extracted {len(sections)}",
            )

    # ---- per-section checks ----------------------------------------------
    for s in sections:
        if len(s.text) < min_section_chars:
            rep.add("warning", "short_section",
                    f"only {len(s.text)} chars", s.section_uid)
        if len(s.text) > max_section_chars:
            rep.add("warning", "long_section",
                    f"{len(s.text)} chars — likely swallowed the next section",
                    s.section_uid)

        for pat in LEAKED_NOISE:
            if pat.search(s.text):
                rep.add("blocking", "noise_leak",
                        f"page furniture survived into the text: {pat.pattern!r}",
                        s.section_uid)
                break

        if MOJIBAKE.search(s.text):
            rep.add("blocking", "mojibake",
                    "control characters or replacement chars in text", s.section_uid)

        # A section that starts mid-sentence signals a bad split point.
        if s.text[:1].islower() and not s.text.startswith("("):
            rep.add("warning", "starts_lowercase",
                    f"text begins {s.text[:40]!r} — split point may be wrong",
                    s.section_uid)

    # ---- title coverage --------------------------------------------------
    titled = rep.stats["titled"]
    if titled == 0:
        rep.add("warning", "no_titles",
                "no section titles extracted — margin detection may have failed")
    elif titled < len(sections) * 0.5:
        rep.add("warning", "sparse_titles",
                f"only {titled}/{len(sections)} sections have titles")

    # ---- parser's own warnings -------------------------------------------
    for w in doc.warnings:
        rep.add("warning", "parser", w)

    # ---- provenance completeness -----------------------------------------
    for s in sections:
        if not s.source_sha256:
            rep.add("blocking", "no_provenance",
                    "section has no source hash", s.section_uid)
            break

    return rep


def coverage_ratio(doc: ParsedDocument, raw_char_count: int) -> float:
    """Fraction of the source text that ended up inside a section.

    Low coverage means text was dropped — schedules, footnotes, or whole pages
    silently missing. High coverage (>1) means duplication.
    """
    return doc.total_chars / raw_char_count if raw_char_count else 0.0
