"""Composition root for the pluggable meeting-memory core."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

from answerers import GroundedLLMAnswerer, TemplateAnswerer
from engine import FixtureRuleExtractor, Fixture, MemoryStore, load_fixture
from llm import OfflineLLMProvider
from ports import Answerer, Extractor, LLMProvider, Repository, Retriever
from retrievers import LexicalRetriever


class MeetingMemoryService:
    """Orchestrate extraction, persistence, retrieval and answering.

    All dependencies are constructor-injected. Defaults are deterministic and
    offline so this service runs on Windows or WSL without credentials, model
    downloads, or network access.
    """

    def __init__(
        self,
        *,
        extractor: Extractor | None = None,
        repository: Repository | None = None,
        retriever: Retriever | None = None,
        answerer: Answerer | None = None,
        llm_provider: LLMProvider | None = None,
    ) -> None:
        self.extractor = extractor or FixtureRuleExtractor()
        self.repository = repository or MemoryStore(extractor=self.extractor)
        self.retriever = retriever or LexicalRetriever(self.repository)
        self.llm_provider = llm_provider or OfflineLLMProvider()
        if answerer is not None:
            self.answerer = answerer
        elif llm_provider is not None:
            self.answerer = GroundedLLMAnswerer(llm_provider)
        else:
            self.answerer = TemplateAnswerer()

    @property
    def meetings(self) -> Any:
        return self.repository.meetings

    @property
    def segments(self) -> Any:
        return self.repository.segments

    @property
    def artifacts(self) -> Any:
        return self.repository.artifacts

    @property
    def claims(self) -> Any:
        return self.repository.claims

    @classmethod
    def from_fixture(
        cls,
        fixture: Fixture,
        **dependencies: Any,
    ) -> "MeetingMemoryService":
        service = cls(**dependencies)
        for meeting in fixture.meetings:
            meeting_segments = [
                segment
                for segment in fixture.segments
                if segment["meeting_id"] == meeting["meeting_id"]
            ]
            service.ingest_meeting(meeting, meeting_segments)
        return service

    @classmethod
    def from_fixture_root(
        cls,
        root: Path,
        **dependencies: Any,
    ) -> "MeetingMemoryService":
        return cls.from_fixture(load_fixture(root), **dependencies)

    def ingest_meeting(
        self,
        meeting: dict[str, Any],
        segments: Sequence[dict[str, Any]],
    ) -> dict[str, Any]:
        return self.repository.ingest_meeting(
            meeting,
            list(segments),
            extractor=self.extractor,
        )

    def answer(
        self,
        question: str,
        tenant_id: str,
        query_type: str = "retrieval",
        *,
        top_k: int = 5,
    ) -> dict[str, Any]:
        return self.answerer.answer(
            question,
            tenant_id,
            query_type,
            top_k=top_k,
            repository=self.repository,
            retriever=self.retriever,
        )
