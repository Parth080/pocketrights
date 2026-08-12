"""Structural tests for contracts/scope.yaml.

scope.yaml is the source of truth for what PocketRights answers. These tests
enforce the invariants that everything downstream relies on — stable ids, valid
cross-references, and a behaviour mix that actually sums to one.
"""

from __future__ import annotations

import re

import pytest

ID_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)?$")
EXPECTED_DOMAINS = {"consumer", "tenancy", "traffic", "employment", "insurance"}


def _categories(scope: dict) -> list[dict]:
    return [c for d in scope["domains"] for c in d["categories"]]


# --------------------------------------------------------------------------
# Shape
# --------------------------------------------------------------------------

def test_top_level_keys(scope):
    required = {
        "version", "status", "corpus_jurisdiction", "clarification_triggers",
        "domains", "out_of_scope", "behaviours", "language",
    }
    assert required <= set(scope)


def test_status_is_valid(scope):
    assert scope["status"] in {"draft", "frozen"}


def test_frozen_scope_is_stamped(scope):
    """A frozen scope must record when it was frozen."""
    if scope["status"] == "frozen":
        assert scope["frozen_at"], "status is frozen but frozen_at is empty"


def test_expected_domains_present(scope):
    assert {d["id"] for d in scope["domains"]} == EXPECTED_DOMAINS


# --------------------------------------------------------------------------
# Identifier discipline — ids are permanent and must be well-formed
# --------------------------------------------------------------------------

def test_category_ids_are_wellformed(scope):
    for cat in _categories(scope):
        assert ID_RE.match(cat["id"]), f"malformed category id: {cat['id']}"


def test_category_ids_are_unique(scope):
    ids = [c["id"] for c in _categories(scope)]
    dupes = {i for i in ids if ids.count(i) > 1}
    assert not dupes, f"duplicate category ids: {dupes}"


def test_category_ids_are_namespaced_by_domain(scope):
    for domain in scope["domains"]:
        for cat in domain["categories"]:
            assert cat["id"].startswith(f"{domain['id']}."), (
                f"{cat['id']} is not namespaced under {domain['id']}"
            )


def test_out_of_scope_ids_are_namespaced(scope):
    for entry in scope["out_of_scope"]:
        assert entry["id"].startswith("oos."), f"{entry['id']} missing oos. prefix"


# --------------------------------------------------------------------------
# Cross-references must resolve
# --------------------------------------------------------------------------

def test_every_requires_resolves_to_a_trigger(scope):
    known = {t["id"] for t in scope["clarification_triggers"]}
    for cat in _categories(scope):
        for trigger in cat.get("requires", []):
            assert trigger in known, f"{cat['id']} requires unknown trigger '{trigger}'"


def test_every_trigger_is_used(scope):
    """An unused trigger is dead weight — either wire it up or delete it."""
    used = {t for c in _categories(scope) for t in c.get("requires", [])}
    declared = {t["id"] for t in scope["clarification_triggers"]}
    assert not (declared - used), f"declared but never used: {declared - used}"


# --------------------------------------------------------------------------
# Content requirements
# --------------------------------------------------------------------------

def test_every_category_has_an_example(scope):
    for cat in _categories(scope):
        assert cat.get("example", "").strip(), f"{cat['id']} has no example question"


def test_every_category_declares_critical_omissions_key(scope):
    """The key must exist even when empty — an omitted key means 'not considered'."""
    for cat in _categories(scope):
        assert "critical_omissions" in cat, f"{cat['id']} missing critical_omissions"
        assert isinstance(cat["critical_omissions"], list)


def test_state_sensitive_domains_require_state(scope):
    """If a domain is flagged state-sensitive, its categories must ask for the
    state — or opt out explicitly with a documented reason. Silent exemptions
    are how a vertical quietly stops asking and starts guessing."""
    for domain in scope["domains"]:
        if not domain.get("state_sensitive"):
            continue
        for cat in domain["categories"]:
            if cat.get("state_exempt"):
                assert cat.get("state_exempt_reason", "").strip(), (
                    f"{cat['id']} claims state_exempt with no reason given"
                )
                continue
            assert "state" in cat.get("requires", []), (
                f"{cat['id']} is in state-sensitive domain '{domain['id']}' "
                "but neither requires the state trigger nor declares state_exempt"
            )


def test_out_of_scope_entries_have_near_misses(scope):
    """Easy refusals teach nothing. Every out-of-scope class needs hard cases."""
    for entry in scope["out_of_scope"]:
        assert entry.get("near_misses"), f"{entry['id']} has no near-miss examples"
        assert entry.get("redirect", "").strip(), f"{entry['id']} has no redirect text"


# --------------------------------------------------------------------------
# Distribution
# --------------------------------------------------------------------------

def test_behaviour_shares_sum_to_one(scope):
    total = sum(b["target_share"] for b in scope["behaviours"])
    assert total == pytest.approx(1.0), f"behaviour shares sum to {total}"


def test_language_shares_sum_to_one(scope):
    total = sum(s["target_share"] for s in scope["language"]["input_styles"])
    assert total == pytest.approx(1.0), f"language shares sum to {total}"


def test_hinglish_share_matches_spec(scope):
    """The spec calls for ~15% romanized Hinglish."""
    styles = {s["id"]: s["target_share"] for s in scope["language"]["input_styles"]}
    assert styles["romanized_hinglish"] == pytest.approx(0.15)


# --------------------------------------------------------------------------
# Coverage — a sanity floor, not a target
# --------------------------------------------------------------------------

def test_each_domain_has_enough_categories(scope):
    for domain in scope["domains"]:
        n = len(domain["categories"])
        assert n >= 5, f"domain '{domain['id']}' has only {n} categories"


def test_every_domain_has_an_escalation_route_category(scope):
    """Every vertical needs an escalation-route question — it is among the most
    commonly asked, and it is the main consumer of the authorities table."""
    for domain in scope["domains"]:
        tagged = [c["id"] for c in domain["categories"] if c.get("escalation_route")]
        assert tagged, (
            f"domain '{domain['id']}' has no category tagged escalation_route: true"
        )


def test_escalation_route_categories_name_a_forum(scope):
    """An escalation category that does not tell the user where to go is useless."""
    for cat in _categories(scope):
        if cat.get("escalation_route"):
            assert cat["critical_omissions"], (
                f"{cat['id']} is an escalation route but lists no critical omissions "
                "— it must at least require naming the forum"
            )


# --------------------------------------------------------------------------
# Sensitive categories — distress contexts need hard rules, not model judgement
# --------------------------------------------------------------------------

def test_sensitive_categories_carry_mandatory_rules(scope):
    for cat in _categories(scope):
        if cat.get("sensitive"):
            rules = cat.get("mandatory_response_rules") or []
            assert len(rules) >= 3, (
                f"{cat['id']} is marked sensitive but declares only {len(rules)} "
                "mandatory response rules — a distress context must not be left "
                "to model judgement"
            )
            assert cat.get("note", "").strip(), f"{cat['id']} is sensitive with no note"


def test_sensitive_categories_require_a_support_redirect(scope):
    for cat in _categories(scope):
        if cat.get("sensitive"):
            joined = " ".join(cat.get("mandatory_response_rules", [])).lower()
            assert "helpline" in joined or "support" in joined, (
                f"{cat['id']} is sensitive but no rule requires a support redirect"
            )


# --------------------------------------------------------------------------
# Bilingual output
# --------------------------------------------------------------------------

def test_answer_languages_declared(scope):
    langs = scope["language"]["answer_languages"]
    assert "en" in langs and "hi" in langs


def test_output_policy_declared(scope):
    assert scope["language"]["output_policy"] in {"mirror_input", "english_only"}


def test_hindi_input_share_is_material(scope):
    """A token share of Hindi input teaches nothing. If Hindi is an output
    language, it needs real representation on the input side too."""
    styles = {s["id"]: s["target_share"] for s in scope["language"]["input_styles"]}
    hindi = styles.get("devanagari_hindi", 0) + styles.get("romanized_hinglish", 0)
    if "hi" in scope["language"]["answer_languages"]:
        assert hindi >= 0.30, f"Hindi-family inputs only {hindi:.0%} of the mix"


def test_register_warning_present_for_hindi(scope):
    """Gazette Hindi is not spoken Hindi. The distinction must be written down
    or the model will answer citizens in statutory register."""
    if "hi" in scope["language"]["answer_languages"]:
        assert scope["language"].get("register_warning", "").strip()
