"""Stable extension points for the meeting-memory core.

The baseline deliberately uses plain dictionaries as its wire format. These
protocols keep the format stable while allowing production implementations to
replace the extractor, repository, retriever, answerer, or LLM.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, Sequence


JsonObject = dict[str, Any]
Meeting = Mapping[str, Any]
Segment = Mapping[str, Any]


class Extractor(Protocol):
    """Create one MeetingArtifactBundle from one transcript."""

    def extract(self, meeting: Meeting, segments: Sequence[Segment]) -> JsonObject:
        ...


class Repository(Protocol):
    """Authoritative storage boundary for meetings, evidence and claims."""

    meetings: Mapping[str, JsonObject]
    segments: Mapping[str, JsonObject]
    artifacts: Mapping[str, JsonObject]
    claims: Mapping[str, JsonObject]

    def ingest_meeting(
        self,
        meeting: JsonObject,
        segments: Sequence[JsonObject],
        *,
        extractor: Extractor | None = None,
    ) -> JsonObject:
        ...

    def upsert_claim(self, claim: JsonObject) -> None:
        ...

    def visible_segments(self, tenant_id: str) -> list[JsonObject]:
        ...

    def visible_claims(self, tenant_id: str) -> list[JsonObject]:
        ...


class Retriever(Protocol):
    """Return tenant-filtered segment and claim candidates."""

    def retrieve(
        self,
        question: str,
        tenant_id: str,
        query_type: str,
        top_k: int = 5,
    ) -> dict[str, list[JsonObject]]:
        ...


class Answerer(Protocol):
    """Turn retrieved candidates into a citation-grounded response."""

    def answer(
        self,
        question: str,
        tenant_id: str,
        query_type: str,
        *,
        top_k: int,
        repository: Repository,
        retriever: Retriever,
    ) -> JsonObject:
        ...


@dataclass(frozen=True)
class LLMResponse:
    """Provider-neutral model response metadata."""

    text: str | None = None
    data: Any = None
    provider: str = "unknown"
    model: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    cost: float | None = None
    raw: Any = None


class LLMProvider(Protocol):
    """Optional model boundary; implementations may target SaaS or local API."""

    provider_id: str
    model: str | None

    def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_format: str = "text",
        metadata: Mapping[str, Any] | None = None,
    ) -> LLMResponse:
        ...
