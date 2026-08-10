"""Tests for the response contract.

Three layers are checked:
  1. the JSON Schema is itself valid
  2. the worked examples validate against it, and the conditional rules bite
  3. the GBNF grammar loads in llama.cpp  (skipped until llama.cpp is on PATH)
"""

from __future__ import annotations

import copy
import shutil
import subprocess
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError

DISCLAIMER = "This is general legal information, not legal advice."


# --------------------------------------------------------------------------
# Schema validity
# --------------------------------------------------------------------------

def test_schema_is_a_valid_json_schema(response_schema):
    Draft202012Validator.check_schema(response_schema)


def test_schema_forbids_extra_keys(response_schema):
    assert response_schema["additionalProperties"] is False


def test_disclaimer_is_a_constant(response_schema):
    assert response_schema["properties"]["disclaimer"]["const"] == DISCLAIMER


# --------------------------------------------------------------------------
# Examples
# --------------------------------------------------------------------------

def test_all_three_behaviours_have_an_example(examples):
    assert set(examples) == {"answer", "clarify", "refuse"}


def test_examples_validate(response_schema, examples):
    validator = Draft202012Validator(response_schema)
    for name, doc in examples.items():
        errors = sorted(validator.iter_errors(doc), key=lambda e: e.path)
        assert not errors, f"{name}.json: {[e.message for e in errors]}"


def test_examples_declare_matching_behaviour(examples):
    for name, doc in examples.items():
        assert doc["behaviour"] == name


def test_every_example_has_the_full_key_set(response_schema, examples):
    """All ten keys are always present — unused ones are empty, never omitted."""
    required = set(response_schema["required"])
    for name, doc in examples.items():
        assert set(doc) == required, f"{name}.json key set differs from schema"


# --------------------------------------------------------------------------
# The conditional rules must actually reject bad documents
# --------------------------------------------------------------------------

def _assert_invalid(schema: dict, doc: dict, why: str) -> None:
    validator = Draft202012Validator(schema)
    errors = list(validator.iter_errors(doc))
    assert errors, f"schema accepted a document it should reject: {why}"


def test_answer_requires_at_least_one_citation(response_schema, examples):
    bad = copy.deepcopy(examples["answer"])
    bad["citations"] = []
    _assert_invalid(response_schema, bad, "answer with no citations")


def test_refuse_may_not_carry_citations(response_schema, examples):
    bad = copy.deepcopy(examples["refuse"])
    bad["citations"] = [
        {"act": "Consumer Protection Act, 2019", "section": "69", "supports": "x"}
    ]
    _assert_invalid(response_schema, bad, "refusal citing a provision")


def test_clarify_must_ask_a_question(response_schema, examples):
    bad = copy.deepcopy(examples["clarify"])
    bad["clarifying_question"] = None
    _assert_invalid(response_schema, bad, "clarify with no question")


def test_clarify_may_not_half_answer(response_schema, examples):
    bad = copy.deepcopy(examples["clarify"])
    bad["what_the_law_says"] = "Deposits are generally returned within a month."
    _assert_invalid(response_schema, bad, "clarify that also answers")


def test_answer_may_not_ask_a_question(response_schema, examples):
    bad = copy.deepcopy(examples["answer"])
    bad["clarifying_question"] = "Which state are you in?"
    _assert_invalid(response_schema, bad, "answer that also asks")


def test_altered_disclaimer_is_rejected(response_schema, examples):
    bad = copy.deepcopy(examples["answer"])
    bad["disclaimer"] = "This is not legal advice."
    _assert_invalid(response_schema, bad, "reworded disclaimer")


def test_unknown_key_is_rejected(response_schema, examples):
    bad = copy.deepcopy(examples["answer"])
    bad["confidence"] = 0.9
    _assert_invalid(response_schema, bad, "extra top-level key")


def test_unknown_unit_is_rejected(response_schema, examples):
    bad = copy.deepcopy(examples["answer"])
    bad["key_numbers"] = [{"claim": "limitation period", "value": 2, "unit": "weeks"}]
    _assert_invalid(response_schema, bad, "unit outside the enum")


def test_numeric_value_must_be_a_number(response_schema, examples):
    bad = copy.deepcopy(examples["answer"])
    bad["key_numbers"] = [{"claim": "limit", "value": "2 years", "unit": "years"}]
    _assert_invalid(response_schema, bad, "value given as a string")


# --------------------------------------------------------------------------
# GBNF
# --------------------------------------------------------------------------

def test_gbnf_exists_and_covers_every_field(repo_root, response_schema):
    """Cheap structural check that runs without llama.cpp."""
    grammar = (repo_root / "docs/schemas/response.gbnf").read_text()
    for field in response_schema["required"]:
        assert f'"\\"{field}\\":"' in grammar, f"grammar does not emit key '{field}'"


def test_gbnf_pins_the_disclaimer(repo_root):
    grammar = (repo_root / "docs/schemas/response.gbnf").read_text()
    assert DISCLAIMER in grammar


@pytest.mark.needs_llamacpp
def test_gbnf_parses_in_llamacpp(repo_root):
    """The real check. Skipped until a llama.cpp build is available (task 43)."""
    binary = shutil.which("llama-gbnf-validator")
    if binary is None:
        pytest.skip("llama-gbnf-validator not on PATH")

    grammar = repo_root / "docs/schemas/response.gbnf"
    sample = repo_root / "docs/schemas/examples/answer.json"
    result = subprocess.run(
        [binary, str(grammar), str(sample)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


# --------------------------------------------------------------------------
# Cross-document consistency
# --------------------------------------------------------------------------

def test_schema_behaviours_match_scope(response_schema, scope):
    """The schema's behaviour enum and scope.yaml's behaviour list must agree,
    ignoring multi_turn, which is a conversation shape rather than a response
    shape."""
    schema_behaviours = set(response_schema["properties"]["behaviour"]["enum"])
    scope_behaviours = {b["id"] for b in scope["behaviours"]} - {"multi_turn"}
    assert schema_behaviours == scope_behaviours


def test_docs_reference_the_current_schema_version(repo_root, response_schema):
    doc = (repo_root / "docs/response-contract.md").read_text()
    version = response_schema["$id"].rsplit("/", 1)[-1].removesuffix(".json")
    assert version.replace("response-", "v") in doc.lower().replace(" ", "")


def test_paths_referenced_in_docs_exist(repo_root):
    for rel in [
        "docs/schemas/response.schema.json",
        "docs/schemas/response.gbnf",
        "docs/schemas/examples/answer.json",
        "docs/schemas/examples/clarify.json",
        "docs/schemas/examples/refuse.json",
    ]:
        assert (repo_root / rel).exists(), f"missing: {rel}"


def test_unused_import_guard():
    """Keeps ValidationError imported for downstream use without tripping lint."""
    assert issubclass(ValidationError, Exception)
    assert Path(".").exists()
