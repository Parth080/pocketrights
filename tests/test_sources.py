"""Structural tests for docs/sources.yaml.

The registry drives acquisition. These tests enforce the discipline that keeps
the corpus defensible: every source traceable to a publisher, nothing marked
verified without provenance, and the labour-regime gate honoured.
"""

from __future__ import annotations

import re

ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")
VALID_STATUS = {"planned", "fetched", "parsed", "verified"}
VALID_DOC_TYPES = {"act", "rules", "regulation", "notification", "circular"}
EXPECTED_DOMAINS = {"consumer", "tenancy", "traffic", "employment", "insurance"}


# --------------------------------------------------------------------------
# Shape
# --------------------------------------------------------------------------

def test_top_level_keys(sources):
    required = {
        "version", "corpus_snapshot", "publishers", "policy",
        "blocking_determinations", "sources", "authorities",
    }
    assert required <= set(sources)


def test_source_ids_are_wellformed_and_unique(sources):
    ids = [s["id"] for s in sources["sources"]]
    for sid in ids:
        assert ID_RE.match(sid), f"malformed source id: {sid}"
    assert len(ids) == len(set(ids)), "duplicate source ids"


def test_statuses_are_valid(sources):
    for s in sources["sources"]:
        assert s["status"] in VALID_STATUS, f"{s['id']}: bad status {s['status']}"


def test_doc_types_are_valid(sources):
    for s in sources["sources"]:
        assert s["doc_type"] in VALID_DOC_TYPES, f"{s['id']}: bad doc_type"


def test_every_source_has_a_known_publisher(sources):
    known = {p["id"] for p in sources["publishers"]}
    for s in sources["sources"]:
        assert s["publisher"] in known, f"{s['id']} cites unknown publisher"


def test_every_domain_has_at_least_one_source(sources):
    covered = {s["domain"] for s in sources["sources"]}
    assert covered >= EXPECTED_DOMAINS, f"uncovered: {EXPECTED_DOMAINS - covered}"


def test_every_domain_has_a_priority_one_source(sources):
    for domain in EXPECTED_DOMAINS:
        has = any(
            s["domain"] == domain and s["priority"] == 1 for s in sources["sources"]
        )
        assert has, f"domain '{domain}' has no priority-1 source"


# --------------------------------------------------------------------------
# Provenance discipline — the rules that keep the corpus defensible
# --------------------------------------------------------------------------

def test_verified_sources_have_a_url(sources):
    """A source cannot be verified against a publisher we never recorded."""
    for s in sources["sources"]:
        if s["status"] == "verified":
            assert s.get("url"), f"{s['id']} is verified but has no url"


def test_nothing_is_verified_before_a_corpus_snapshot_exists(sources):
    verified = [s["id"] for s in sources["sources"] if s["status"] == "verified"]
    if verified:
        assert sources["corpus_snapshot"], (
            f"sources marked verified ({verified}) but corpus_snapshot is unset"
        )


def test_raw_storage_is_append_only(sources):
    assert sources["policy"]["raw_immutable"] is True


def test_hashing_is_configured(sources):
    assert sources["policy"]["hash_algorithm"] == "sha256"


def test_crawl_is_polite(sources):
    assert sources["policy"]["rate_limit_rps"] <= 1.0


def test_provenance_record_covers_the_required_fields(sources):
    required = {
        "source_id", "title", "url", "retrieved_at", "sha256", "jurisdiction",
        "publisher", "doc_type", "effective_from", "licence", "snapshot_version",
    }
    assert required <= set(sources["policy"]["record_per_source"])


# --------------------------------------------------------------------------
# The labour-regime gate (risk R4)
# --------------------------------------------------------------------------

def _labour_gate(sources: dict) -> dict:
    gates = {b["id"]: b for b in sources["blocking_determinations"]}
    return gates["labour_regime"]


def test_labour_regime_gate_exists(sources):
    gate = _labour_gate(sources)
    assert gate["status"] in {"unresolved", "resolved"}


def test_employment_sources_are_gated_until_the_regime_is_settled(sources):
    """No employment source may advance past `planned` while the regime is
    unresolved. This is the automated form of risk R4."""
    gate = _labour_gate(sources)
    if gate["status"] == "resolved":
        return
    for s in sources["sources"]:
        if s["domain"] == "employment":
            assert s["status"] == "planned", (
                f"{s['id']} has status '{s['status']}' but the labour-regime "
                "determination is still unresolved"
            )


def test_resolved_gate_records_its_answer(sources):
    gate = _labour_gate(sources)
    if gate["status"] == "resolved":
        assert gate["resolution"], "gate marked resolved with no recorded resolution"
        assert gate["resolved_at"], "gate marked resolved with no date"


def test_employment_sources_declare_the_gate(sources):
    for s in sources["sources"]:
        if s["domain"] == "employment":
            assert s.get("gated_on") == "labour_regime", (
                f"{s['id']} is an employment source but does not declare gated_on"
            )


# --------------------------------------------------------------------------
# Authorities — must never be populated from memory
# --------------------------------------------------------------------------

def test_authorities_entries_carry_provenance(sources):
    for a in sources["authorities"]:
        assert a.get("source_ref"), f"authority '{a.get('id')}' has no source_ref"


# --------------------------------------------------------------------------
# Consistency with scope.yaml
# --------------------------------------------------------------------------

def test_source_domains_match_scope_domains(sources, scope):
    scope_domains = {d["id"] for d in scope["domains"]}
    source_domains = {s["domain"] for s in sources["sources"]}
    assert source_domains <= scope_domains, (
        f"sources reference domains not in scope.yaml: {source_domains - scope_domains}"
    )


def test_primary_acts_in_scope_are_registered_sources(sources, scope):
    """Every act named in scope.yaml must exist in the registry, or acquisition
    will silently skip it."""
    registered = {s["id"] for s in sources["sources"]}
    for domain in scope["domains"]:
        for act in domain.get("primary_acts", []):
            assert act in registered, (
                f"scope.yaml domain '{domain['id']}' names primary act '{act}' "
                "which is not in sources.yaml"
            )
