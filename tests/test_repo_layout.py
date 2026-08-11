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
    "contracts", "contracts/schemas", "contracts/schemas/examples",
    "packages", "scripts", "tests", "web",
    "data/raw", "data/store", "data/datasets", "data/cpt", "data/bench",
    "models", "runs",
]

# Version-controlled. A fresh clone must have all of these or the pipeline
# cannot run.
TRACKED_CONTRACTS = [
    "PROJECT.md",
    "README.md",
    "contracts/README.md",
    "contracts/scope.yaml",
    "contracts/sources.yaml",
    "contracts/preregistration.md",
    "contracts/schemas/response.schema.json",
    "contracts/schemas/response.gbnf",
]

# Deliberately untracked (docs/ is gitignored). Present on the author's machine,
# absent in a clone. Nothing may depend on them.
LOCAL_NARRATIVES = [
    "docs/scope.md",
    "docs/response-contract.md",
    "docs/sources.md",
]


def test_expected_directories_exist(repo_root):
    for d in EXPECTED_DIRS:
        assert (repo_root / d).is_dir(), f"missing directory: {d}"


def test_tracked_contracts_exist(repo_root):
    for doc in TRACKED_CONTRACTS:
        path = repo_root / doc
        assert path.is_file(), f"missing tracked contract: {doc}"
        assert path.stat().st_size > 300, f"suspiciously small: {doc}"


def test_local_narratives_are_intact_when_present(repo_root):
    """docs/ is untracked, so absence is fine — but a truncated file is not."""
    for doc in LOCAL_NARRATIVES:
        path = repo_root / doc
        if path.exists():
            assert path.stat().st_size > 500, f"suspiciously small: {doc}"


def test_nothing_tracked_lives_under_docs(repo_root):
    """docs/ is gitignored by design. If a file code depends on ends up there,
    a fresh clone breaks — so no contract may live under docs/."""
    docs = repo_root / "docs"
    if not docs.exists():
        return
    for pattern in ("*.yaml", "*.yml", "*.json", "*.gbnf"):
        stragglers = list(docs.rglob(pattern))
        assert not stragglers, (
            f"machine-readable files found under untracked docs/: {stragglers}. "
            "Move them to contracts/."
        )


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
