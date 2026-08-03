from __future__ import annotations

import unittest
from pathlib import Path

from engine import FixtureRuleExtractor, load_fixture
from hybrid_retrievers import HybridRetriever
from retrievers import LexicalRetriever
from service import MeetingMemoryService
from sqlite_repository import SQLiteRepository


FIXTURE_ROOT = Path(__file__).resolve().parent.parent / "fixtures" / "meeting-memory-fixture-10"


class BoostingRetriever:
    retrieval_mode = "fixture_secondary"

    def __init__(self, repository):
        self.repository = repository

    def retrieve(self, question, tenant_id, query_type, top_k=5):
        del question, query_type
        segments = self.repository.visible_segments(tenant_id)
        claims = self.repository.visible_claims(tenant_id)
        return {
            "segments": [{"score": 1.0, "segment": segments[0]}] if segments else [],
            "claims": [{"score": 1.0, "claim": claims[0]}] if claims else [],
        }


class StorageAndHybridTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = load_fixture(FIXTURE_ROOT)

    def test_sqlite_repository_preserves_fixture_behavior(self):
        repository = SQLiteRepository(":memory:")
        service = MeetingMemoryService(
            extractor=FixtureRuleExtractor(),
            repository=repository,
            retriever=LexicalRetriever(repository),
        )
        for meeting in self.fixture.meetings:
            service.ingest_meeting(
                meeting,
                [s for s in self.fixture.segments if s["meeting_id"] == meeting["meeting_id"]],
            )
        self.assertEqual(len(repository.meetings), 10)
        self.assertEqual(len(repository.segments), 60)
        self.assertEqual(len(repository.claims), 18)
        current = service.answer("现在生产检索的主链路是什么？", "tenant_alpha", "current_state")
        self.assertFalse(current["no_answer"])
        self.assertTrue(any("PostgreSQL全文检索加pgvector" in c["object"] for c in current["claims"]))
        isolated = service.answer("蓝海客户项目的前端方案是什么？", "tenant_alpha", "tenant_isolation")
        self.assertTrue(isolated["no_answer"])
        repository.close()

    def test_hybrid_fuses_secondary_without_changing_scope(self):
        repository = SQLiteRepository(":memory:")
        service = MeetingMemoryService(extractor=FixtureRuleExtractor(), repository=repository)
        for meeting in self.fixture.meetings:
            service.ingest_meeting(
                meeting,
                [s for s in self.fixture.segments if s["meeting_id"] == meeting["meeting_id"]],
            )
        primary = LexicalRetriever(repository)
        hybrid = HybridRetriever(primary, BoostingRetriever(repository), primary_weight=0.7, secondary_weight=0.3)
        service.retriever = hybrid
        result = service.answer("现在生产检索的主链路是什么？", "tenant_alpha", "current_state")
        self.assertFalse(result["no_answer"])
        self.assertEqual(result["retrieval_mode"], "hybrid_lexical_secondary")
        self.assertTrue(all(citation["meeting_id"] != "meeting_010" for citation in result["citations"]))
        repository.close()


if __name__ == "__main__":
    unittest.main()
