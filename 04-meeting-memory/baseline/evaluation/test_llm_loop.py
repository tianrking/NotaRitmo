"""Offline regression for the real meeting-artifact extraction loop."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

try:
    from .run_llm_loop import FixtureReplayProvider, run_loop
except ImportError:  # unittest discover from evaluation/ as a top-level module
    from run_llm_loop import FixtureReplayProvider, run_loop  # type: ignore


FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "meeting-memory-fixture-10"


class LLMOfflineLoopTests(unittest.TestCase):
    def test_fixture_replay_runs_one_meeting_without_network(self) -> None:
        """Fixture replay proves orchestration/evidence validation, not LLM quality."""

        with tempfile.TemporaryDirectory(prefix="notaritmo-llm-loop-") as temporary:
            result = run_loop(
                FixtureReplayProvider(FIXTURE_DIR),
                FIXTURE_DIR,
                Path(temporary),
                prompt_version="test-loop-v1",
                max_meetings=1,
                max_attempts=2,
            )
            self.assertEqual(result["provider"], "fixture-replay")
            self.assertEqual(result["meetings"], 1)
            self.assertEqual(result["counts"]["succeeded"], 1)
            self.assertEqual(result["counts"]["failed"], 0)
            # The evaluator intentionally keeps all ten gold rows even when the
            # loop is capped at one meeting; inspect the processed row rather
            # than treating unprocessed meetings as model misses.
            first_score = result["extraction_quality"]["scores"][0]
            self.assertEqual(first_score["evidence"]["f1"], 1.0)
            self.assertTrue(Path(result["predictions_path"]).is_file())
            self.assertTrue((Path(temporary) / "summary.json").is_file())


if __name__ == "__main__":
    unittest.main()
