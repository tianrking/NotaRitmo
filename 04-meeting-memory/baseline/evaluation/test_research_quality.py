from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from research_quality import (  # type: ignore
        _mrr,
        _ndcg,
        _recall,
        evaluate_fixture,
        evaluate_query,
    )
else:
    from .research_quality import _mrr, _ndcg, _recall, evaluate_fixture, evaluate_query

try:
    from engine import load_fixture
    from service import MeetingMemoryService
except ImportError:
    from ..engine import load_fixture  # type: ignore
    from ..service import MeetingMemoryService  # type: ignore


FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "fixtures" / "meeting-memory-fixture-10"


class ResearchQualityTests(unittest.TestCase):
    def test_rank_metrics_have_expected_semantics(self) -> None:
        self.assertEqual(_recall(["a", "b"], {"b"}, 1), 0.0)
        self.assertEqual(_recall(["a", "b"], {"b"}, 2), 1.0)
        self.assertEqual(_mrr(["a", "b"], {"b"}), 0.5)
        self.assertEqual(_mrr([], set()), 1.0)
        self.assertEqual(_ndcg(["b", "a"], {"b"}, 1), 1.0)
        self.assertLess(_ndcg(["a", "b"], {"b"}, 1), 1.0)

    def test_fixed_fixture_report_covers_required_dimensions(self) -> None:
        report = evaluate_fixture(FIXTURE_ROOT, ks=(1, 3, 5))
        self.assertEqual(report["queries"], 18)
        self.assertEqual(report["meetings_loaded"], 10)
        self.assertEqual(report["segments_loaded"], 60)
        self.assertIn("meeting", report["recall_at_k"])
        self.assertIn("claim", report["recall_at_k"])
        self.assertIn("evidence", report["recall_at_k"])
        self.assertIn("meeting", report["mrr"])
        self.assertIn("evidence", report["ndcg_at_k"])
        self.assertEqual(report["no_answer_accuracy"], 1.0)
        self.assertEqual(report["tenant_isolation"]["leakage_free_rate"], 1.0)
        self.assertEqual(report["citation_playable_rate"], 1.0)
        self.assertEqual(report["current_state_hit_rate"], 1.0)
        self.assertEqual(report["historical_state_hit_rate"], 1.0)
        self.assertEqual(report["cross_meeting_queries"], 2)
        self.assertGreater(report["cross_meeting_recall"], 0.0)
        self.assertGreater(report["evidence_recall"], 0.0)

    def test_query_result_retains_ranked_evidence_and_answer(self) -> None:
        fixture = load_fixture(FIXTURE_ROOT)
        service = MeetingMemoryService.from_fixture(fixture)
        query = next(row for row in fixture.queries if row["query_id"] == "q004")
        row = evaluate_query(service, query, gold_claims=fixture.gold_claims, ks=(1, 3, 5))
        self.assertEqual(row["query_id"], "q004")
        self.assertTrue(row["ranked"]["claims"])
        self.assertTrue(row["ranked"]["evidence"])
        self.assertTrue(row["answer"]["citations"])
        self.assertEqual(row["state_kind"], "current_state")
        self.assertEqual(row["state_hit"], True)

    def test_tenant_leak_is_reported_even_if_answerer_is_wrong(self) -> None:
        fixture = load_fixture(FIXTURE_ROOT)
        service = MeetingMemoryService.from_fixture(fixture)
        original_answer = service.answer

        class LeakyService:
            meetings = service.meetings
            segments = service.segments
            claims = service.claims

            def answer(self, question: str, tenant_id: str, query_type: str, *, top_k: int = 5) -> Any:
                result = dict(original_answer(question, tenant_id, query_type, top_k=top_k))
                result["meetings"] = list(result.get("meetings", [])) + ["meeting_010"]
                result["citations"] = list(result.get("citations", [])) + [{
                    "meeting_id": "meeting_010",
                    "segment_id": "m010_s02",
                    "speaker_id": "speaker_05",
                    "start_ms": 55000,
                    "end_ms": 95000,
                    "text": "客户门户首版计划使用 React。",
                }]
                return result

        query = next(row for row in fixture.queries if row["query_id"] == "q016")
        row = evaluate_query(LeakyService(), query, gold_claims=fixture.gold_claims, ks=(1, 3, 5))
        self.assertFalse(row["tenant_isolation"]["leak_free"])
        self.assertIn("meeting_010", row["tenant_isolation"]["leaked_meetings"])
        self.assertIn("m010_s02", row["tenant_isolation"]["leaked_segments"])


if __name__ == "__main__":
    unittest.main()
