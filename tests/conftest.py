"""Shared fixtures. Everything is loaded from docs/ — the contracts are the tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS = REPO_ROOT / "docs"
SCHEMAS = DOCS / "schemas"


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def scope() -> dict:
    return yaml.safe_load((DOCS / "scope.yaml").read_text())


@pytest.fixture(scope="session")
def sources() -> dict:
    return yaml.safe_load((DOCS / "sources.yaml").read_text())


@pytest.fixture(scope="session")
def response_schema() -> dict:
    return json.loads((SCHEMAS / "response.schema.json").read_text())


@pytest.fixture(scope="session")
def examples() -> dict[str, dict]:
    return {
        p.stem: json.loads(p.read_text())
        for p in sorted((SCHEMAS / "examples").glob("*.json"))
    }
