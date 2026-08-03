"""单会议 LLM 抽取最小离线合同测试。"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

MODULE_ROOT = Path(__file__).resolve().parents[1]
PROVIDER_ROOT = MODULE_ROOT.parent / "llm-providers"
for path in (MODULE_ROOT.parent, MODULE_ROOT, PROVIDER_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from llm_providers.contracts import LLMProvider, LLMRequest, LLMResponse, Usage  # noqa: E402
try:
    from .extractor import ExtractionStatus, MeetingArtifactExtractor  # noqa: E402
    from .schema import validate_artifact  # noqa: E402
except ImportError:  # unittest discover -s intelligence imports this as a top-level module
    from intelligence.extractor import ExtractionStatus, MeetingArtifactExtractor  # type: ignore  # noqa: E402
    from intelligence.schema import validate_artifact  # type: ignore  # noqa: E402


class StaticArtifactProvider(LLMProvider):
    name = "test-static"

    def complete_json(self, request: LLMRequest) -> LLMResponse:
        meeting = request.user_payload["meeting"]
        segment_id = request.user_payload["segments"][0]["segment_id"]
        data = {
            "schema_version": "meeting-artifact-v1",
            "meeting_id": meeting["meeting_id"], "tenant_id": meeting["tenant_id"],
            "summary": "测试摘要", "topics": ["测试"], "chapters": [], "facts": [],
            "decisions": [{"decision_id": "d1", "content": "测试决定", "evidence_segment_ids": [segment_id]}],
            "action_items": [], "risks": [], "open_questions": [], "keywords": [], "claims": [],
            "evidence": [], "evidence_segment_ids": [segment_id],
        }
        return LLMResponse(data=data, provider=self.name, model="static", prompt_version=request.prompt_version,
                           input_hash=request.input_hash, usage=Usage.estimate(request, data), cost_usd=0.0, latency_ms=0.0)


class TestLLMExtraction(unittest.TestCase):
    def setUp(self) -> None:
        self.meeting = {"meeting_id": "m1", "tenant_id": "t1", "title": "测试"}
        self.segments = [{"segment_id": "s1", "meeting_id": "m1", "tenant_id": "t1", "text": "决定测试", "speaker_id": "sp1", "start_ms": 0, "end_ms": 100}]

    def test_static_provider_and_evidence(self) -> None:
        result = MeetingArtifactExtractor(StaticArtifactProvider()).extract_result(self.meeting, self.segments)
        self.assertEqual(result.status, ExtractionStatus.SUCCEEDED)
        self.assertEqual(result.artifact["meeting_id"], "m1")
        self.assertTrue(validate_artifact(result.artifact, meeting=self.meeting, segments=self.segments).valid)

    def test_unknown_evidence_is_rejected(self) -> None:
        artifact = {"schema_version": "meeting-artifact-v1", "meeting_id": "m1", "tenant_id": "t1", "summary": "x", "topics": [], "chapters": [], "facts": [], "decisions": [{"content": "x", "evidence_segment_ids": ["missing"]}], "action_items": [], "risks": [], "open_questions": [], "keywords": [], "claims": [], "evidence": []}
        report = validate_artifact(artifact, meeting=self.meeting, segments=self.segments)
        self.assertFalse(report.valid)
        self.assertTrue(any("unknown segment_id" in issue for issue in report.issues))

    def test_single_segment_id_evidence_shape_is_accepted(self) -> None:
        artifact = {
            "schema_version": "meeting-artifact-v1",
            "meeting_id": "m1",
            "tenant_id": "t1",
            "summary": "x",
            "topics": [],
            "chapters": [],
            "facts": [],
            "decisions": [{"content": "x", "segment_id": "s1"}],
            "action_items": [],
            "risks": [],
            "open_questions": [],
            "keywords": [],
            "claims": [],
            "evidence": [{"segment_id": "s1"}],
        }
        report = validate_artifact(artifact, meeting=self.meeting, segments=self.segments)
        self.assertTrue(report.valid, report.issues)

    def test_fixture_replay_loop_is_offline(self) -> None:
        script = MODULE_ROOT / "baseline" / "evaluation" / "run_llm_loop.py"
        spec = importlib.util.spec_from_file_location("run_llm_loop_test", script)
        self.assertIsNotNone(spec and spec.loader)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        fixture = MODULE_ROOT / "fixtures" / "meeting-memory-fixture-10"
        with tempfile.TemporaryDirectory() as temporary:
            summary = module.run_loop(module.FixtureReplayProvider(fixture), fixture, Path(temporary), prompt_version="test-v1", max_meetings=2, max_attempts=1)
            self.assertEqual(summary["counts"]["succeeded"], 2)
            self.assertEqual(summary["provider"], "fixture-replay")
            self.assertTrue((Path(temporary) / "predictions.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
