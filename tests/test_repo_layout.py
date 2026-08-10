"""Tests that the repo scaffold matches PROJECT.md §11, and that the four
contract documents referenced by the task list actually exist.

Cheap, but they catch the failure mode where a directory quietly disappears and
a downstream script starts writing to the wrong place.
"""

from __future__ import annotations

import tomllib

EXPECTED_PACKAGES = [
    "pr_corpus", "pr_store", "pr_verify", "pr_datagen",
    "pr_eval", "pr_train", "pr_quant",
]

EXPECTED_DIRS = [
    "docs", "docs/schemas", "docs/paper", "packages", "scripts", "tests", "web",
    "data/raw", "data/store", "data/datasets", "data/cpt", "data/bench",
    "models", "runs",
]

CONTRACT_DOCS = [
    "PROJECT.md",
    "docs/scope.md",
    "docs/scope.yaml",
    "docs/response-contract.md",
    "docs/sources.md",
    "docs/sources.yaml",
    "docs/preregistration.md",
]


def test_expected_directories_exist(repo_root):
    for d in EXPECTED_DIRS:
        assert (repo_root / d).is_dir(), f"missing directory: {d}"


def test_contract_documents_exist(repo_root):
    for doc in CONTRACT_DOCS:
        path = repo_root / doc
        assert path.is_file(), f"missing document: {doc}"
        assert path.stat().st_size > 500, f"suspiciously small: {doc}"


def test_every_package_is_importable_and_versioned(repo_root):
    for pkg in EXPECTED_PACKAGES:
        module = __import__(pkg)
        assert module.__version__


def test_every_package_declares_a_pyproject(repo_root):
    for pkg in EXPECTED_PACKAGES:
        path = repo_root / "packages" / pkg / "pyproject.toml"
        assert path.is_file(), f"missing: {path}"
        cfg = tomllib.loads(path.read_text())
        assert cfg["project"]["name"] == pkg.replace("_", "-")


def test_workspace_lists_every_package(repo_root):
    cfg = tomllib.loads((repo_root / "pyproject.toml").read_text())
    declared = set(cfg["project"]["dependencies"])
    assert declared == {p.replace("_", "-") for p in EXPECTED_PACKAGES}


def test_data_directories_are_gitkept(repo_root):
    """Empty data dirs must survive a clone, or first-run scripts fail."""
    for d in ["data/raw", "data/store", "data/datasets", "data/cpt", "models", "runs"]:
        assert (repo_root / d / ".gitkeep").exists(), f"{d} has no .gitkeep"


def test_gitignore_protects_secrets_and_large_artifacts(repo_root):
    text = (repo_root / ".gitignore").read_text()
    for pattern in [".env", "models/**", "data/store/*.db"]:
        assert pattern in text, f".gitignore does not cover {pattern}"
