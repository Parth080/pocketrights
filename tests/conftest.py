"""Shared fixtures.

Contracts live in `contracts/` and are version-controlled — they are what code
reads. The prose narratives in `docs/` are deliberately untracked, so no test
may *require* them; tests that reference them skip when they are absent.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = REPO_ROOT / "contracts"
SCHEMAS = CONTRACTS / "schemas"
DOCS = REPO_ROOT / "docs"          # untracked; may not exist in a fresh clone


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def contracts_dir() -> Path:
    return CONTRACTS


@pytest.fixture(scope="session")
def scope() -> dict:
    return yaml.safe_load((CONTRACTS / "scope.yaml").read_text())


@pytest.fixture(scope="session")
def sources() -> dict:
    return yaml.safe_load((CONTRACTS / "sources.yaml").read_text())


@pytest.fixture(scope="session")
def response_schema() -> dict:
    return json.loads((SCHEMAS / "response.schema.json").read_text())


@pytest.fixture(scope="session")
def examples() -> dict[str, dict]:
    return {
        p.stem: json.loads(p.read_text())
        for p in sorted((SCHEMAS / "examples").glob("*.json"))
    }


@pytest.fixture(scope="session")
def narrative():
    """Reader for the untracked docs/ narratives. Skips the test if absent."""

    def _read(name: str) -> str:
        path = DOCS / name
        if not path.exists():
            pytest.skip(f"docs/{name} is untracked and not present locally")
        return path.read_text()

    return _read
