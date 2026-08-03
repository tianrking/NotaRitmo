from __future__ import annotations

import unittest
from pathlib import Path

from engine import MemoryStore, load_fixture


FIXTURE_ROOT = Path(__file__).resolve().parent.parent / "fixtures" / "meeting-memory-fixture-10"


class OfflineBaselineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = load_fixture(FIXTURE_ROOT)
        cls.store = MemoryStore.from_fixture(cls.fixture)

    def test_input_and_artifact_counts(self) -> None:
        self.assertEqual(len(self.store.meetings), 10)
        self.assertEqual(len(self.store.segments), 60)
        self.assertEqual(len(self.store.artifacts), 10)
        self.assertTrue(self.store.artifacts["meeting_001"]["summary"])
        self.assertIn("项目范围", self.store.artifacts["meeting_001"]["topics"])
        self.assertTrue(self.store.artifacts["meeting_001"]["decisions"])
        self.assertTrue(self.store.artifacts["meeting_001"]["action_items"])

    def test_claim_extraction_and_evidence(self) -> None:
        claims = self.store.visible_claims("tenant_alpha")
        self.assertTrue(any(claim["subject"] == "TranscriptBundle" for claim in claims))
        for claim in claims:
            self.assertTrue(claim["evidence_segment_ids"])
            self.assertTrue(all(segment_id in self.store.segments for segment_id in claim["evidence_segment_ids"]))

    def test_current_and_historical_state(self) -> None:
        current = self.store.answer("现在生产检索的主链路是什么？", "tenant_alpha", "current_state")
        self.assertFalse(current["no_answer"])
        self.assertTrue(any("PostgreSQL全文检索加pgvector" in claim["object"] for claim in current["claims"]))
        historical = self.store.answer("最初 RAGFlow 在架构中是什么定位？", "tenant_alpha", "historical_state")
        self.assertFalse(historical["no_answer"])
        self.assertTrue(any(claim["object"] == "RAGFlow" for claim in historical["claims"]))
        old = next(claim for claim in self.store.claims.values() if claim["object"] == "RAGFlow")
        self.assertEqual(old["status"], "superseded")
        self.assertTrue(old["superseded_by"])

    def test_hybrid_retrieval_and_cross_meeting(self) -> None:
        result = self.store.answer("为什么后来不再把 RAGFlow 作为生产主链路？", "tenant_alpha", "cross_meeting_change")
        self.assertFalse(result["no_answer"])
        self.assertIn("meeting_002", result["meetings"])
        self.assertIn("meeting_009", result["meetings"])
        self.assertGreaterEqual(len(result["citations"]), 2)

    def test_citations_are_playable_shape(self) -> None:
        result = self.store.answer("如何同时搜索产品名和语义相近内容？", "tenant_alpha", "retrieval")
        self.assertFalse(result["no_answer"])
        for citation in result["citations"]:
            self.assertIn(citation["meeting_id"], self.store.meetings)
            self.assertIn(citation["segment_id"], self.store.segments)
            self.assertLess(citation["start_ms"], citation["end_ms"])
            self.assertTrue(citation["text"])

    def test_no_answer(self) -> None:
        result = self.store.answer("有没有讨论蓝海客户项目预算八万元？", "tenant_alpha", "no_answer")
        self.assertTrue(result["no_answer"])
        self.assertEqual(result["citations"], [])

    def test_tenant_isolation(self) -> None:
        alpha = self.store.answer("蓝海客户项目的前端方案是什么？", "tenant_alpha", "tenant_isolation")
        self.assertTrue(alpha["no_answer"])
        self.assertEqual(alpha["meetings"], [])
        beta = self.store.answer("蓝海客户项目的前端方案是什么？", "tenant_beta", "single_meeting")
        self.assertFalse(beta["no_answer"])
        self.assertEqual(beta["meetings"], ["meeting_010"])

    def test_all_gold_queries_have_expected_evidence_or_refusal(self) -> None:
        for query in self.fixture.queries:
            result = self.store.answer(query["question"], query["tenant_id"], query["query_type"])
            if query["no_answer"]:
                self.assertTrue(result["no_answer"], query["query_id"])
            else:
                self.assertFalse(result["no_answer"], query["query_id"])
                expected = set(query["expected_evidence"])
                actual = {citation["segment_id"] for citation in result["citations"]}
                self.assertTrue(expected & actual, query["query_id"])


if __name__ == "__main__":
    unittest.main()
