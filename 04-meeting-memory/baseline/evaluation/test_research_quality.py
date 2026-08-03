from __future__ import annotations

import unittest
from pathlib import Path

from engine import load_fixture
from service import MeetingMemoryService
try:
    from .research_quality import evaluate_store, ndcg_at_k, recall_at_k, reciprocal_rank
except ImportError:  # unittest discover with evaluation as search root
    from research_quality import evaluate_store, ndcg_at_k, recall_at_k, reciprocal_rank


FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "fixtures" / "meeting-memory-fixture-10"


class ResearchQualityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = load_fixture(FIXTURE_ROOT)
        cls.store = MeetingMemoryService.from_fixture(cls.fixture)
        cls.report = evaluate_store(cls.store, cls.fixture.queries)

    def test_basic_ranking_metrics(self):
        self.assertEqual(recall_at_k(["a", "b"], {"b"}, 2), 1.0)
        self.assertEqual(reciprocal_rank(["x", "b"], {"b"}), 0.5)
        self.assertEqual(ndcg_at_k(["b"], {"b"}, 1), 1.0)

    def test_policy_and_retrieval_metrics(self):
        summary = self.report["summary"]
        self.assertEqual(summary["queries"], 18)
        self.assertEqual(summary["no_answer_accuracy"], 1.0)
        self.assertEqual(summary["tenant_leakage_count"], 0)
        self.assertEqual(summary["citation_playable_rate"], 1.0)
        # The lexical baseline is intentionally not treated as production quality.
        # These gates only detect a broken pipeline; optimization is measured by
        # comparing this report with later hybrid/vector/reranked providers.
        self.assertGreaterEqual(summary["meeting_recall_at_k"]["5"], 0.90)
        self.assertGreaterEqual(summary["evidence_recall_at_k"]["5"], 0.80)
        self.assertEqual(summary["state_hit_rate"], 1.0)


if __name__ == "__main__":
    unittest.main()
