"""Reader for `contracts/sources.yaml`.

The registry is the acquisition plan. This module loads it, resolves publishers,
and — importantly — enforces the labour-regime gate in code rather than by
convention. See risk R4 in PROJECT.md §14.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field


def find_repo_root(start: Path | None = None) -> Path:
    """Walk up looking for the contracts directory."""
    here = (start or Path(__file__)).resolve()
    for candidate in [here, *here.parents]:
        if (candidate / "contracts" / "sources.yaml").is_file():
            return candidate
    raise FileNotFoundError("could not locate repo root (no contracts/sources.yaml)")


class Publisher(BaseModel):
    id: str
    name: str
    base_url: str | None = None
    notes: str | None = None
    licence_status: str = "to_confirm"


class Source(BaseModel):
    id: str
    domain: str
    title: str
    doc_type: str
    jurisdiction: str
    publisher: str
    url: str | None = None
    priority: int = 3
    status: str = "planned"
    notes: str | None = None
    gated_on: str | None = None
    section_filter: str | None = None
    resolves: str | None = None
    sensitive: bool = False
    url_verified_at: str | None = None
    url_note: str | None = None


class BlockingDetermination(BaseModel):
    id: str
    question: str
    why_it_blocks: str | None = None
    resolve_from: str | None = None
    resolution: str | None = None
    resolved_at: str | None = None
    status: str = "unresolved"
    blocks: list[str] = Field(default_factory=list)

    @property
    def resolved(self) -> bool:
        return self.status == "resolved"


class Policy(BaseModel):
    raw_immutable: bool = True
    hash_algorithm: str = "sha256"
    rate_limit_rps: float = 0.5
    user_agent: str = "PocketRights research crawler"
    record_per_source: list[str] = Field(default_factory=list)


class Registry(BaseModel):
    version: str
    corpus_snapshot: str | None = None
    corpus_hash: str | None = None
    publishers: list[Publisher]
    policy: Policy
    blocking_determinations: list[BlockingDetermination] = Field(default_factory=list)
    sources: list[Source]
    authorities: list[dict] = Field(default_factory=list)

    # -- lookups ---------------------------------------------------------

    def source(self, source_id: str) -> Source:
        for s in self.sources:
            if s.id == source_id:
                return s
        raise KeyError(f"unknown source: {source_id}")

    def publisher(self, publisher_id: str) -> Publisher:
        for p in self.publishers:
            if p.id == publisher_id:
                return p
        raise KeyError(f"unknown publisher: {publisher_id}")

    def determination(self, det_id: str) -> BlockingDetermination:
        for d in self.blocking_determinations:
            if d.id == det_id:
                return d
        raise KeyError(f"unknown determination: {det_id}")

    def by_domain(self, domain: str) -> list[Source]:
        return [s for s in self.sources if s.domain == domain]

    # -- gating ----------------------------------------------------------

    def blocks_use(self, source: Source) -> str | None:
        """Return the reason a source may not be USED, or None.

        Risk R4 expressed as code. An employment source loaded into the store
        before the labour-regime question is settled produces training data
        citing real sections with real numbers from the wrong regime — and
        nothing downstream catches that.

        Note this gates USE, not acquisition. Downloading a PDF creates no
        training data, and the Gazette notifications needed to resolve the gate
        are themselves employment sources. Acquisition is always permitted;
        `pr_store` and `pr_datagen` are what must honour this.
        """
        if source.gated_on is None:
            return None
        try:
            det = self.determination(source.gated_on)
        except KeyError:
            return f"declares gated_on='{source.gated_on}' which does not exist"
        if det.resolved:
            return None
        return (
            f"blocked by unresolved determination '{det.id}': {det.question.strip()}"
        )

    def is_blocked(self, source: Source) -> str | None:
        """Deprecated alias for :meth:`blocks_use`."""
        return self.blocks_use(source)

    def fetchable(self, *, domain: str | None = None, max_priority: int = 3) -> list[Source]:
        """Sources that may be fetched right now, priority order.

        Everything with a URL is fetchable. Use-gating is enforced later, when
        sections are loaded into the store.
        """
        out = [
            s
            for s in self.sources
            if (domain is None or s.domain == domain) and s.priority <= max_priority
        ]
        return sorted(out, key=lambda s: (s.priority, s.id))

    def usable(self, *, domain: str | None = None) -> list[Source]:
        """Sources cleared for loading into the statute store."""
        return [
            s
            for s in self.sources
            if (domain is None or s.domain == domain) and self.blocks_use(s) is None
        ]


def load_registry(path: Path | None = None) -> Registry:
    if path is None:
        path = find_repo_root() / "contracts" / "sources.yaml"
    return Registry.model_validate(yaml.safe_load(path.read_text()))


@lru_cache(maxsize=1)
def default_registry() -> Registry:
    return load_registry()
