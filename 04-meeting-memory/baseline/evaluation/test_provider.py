from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from .evaluator import evaluate_provider
    from .provider import (
        FixtureReplayProvider,
        LLMRequest,
        OpenAICompatibleConfig,
        OpenAICompatibleProvider,
        Usage,
        build_meeting_extraction_request,
    )
except ImportError:  # unittest discover -s evaluation imports test as top-level
    from evaluator import evaluate_provider  # type: ignore
    from provider import (  # type: ignore
        FixtureReplayProvider,
        LLMRequest,
        OpenAICompatibleConfig,
        OpenAICompatibleProvider,
        Usage,
        build_meeting_extraction_request,
    )


ROOT = Path(__file__).resolve().parents[3]
FIXTURE_DIR = ROOT / "04-meeting-memory" / "fixtures" / "meeting-memory-fixture-10"


class FakeHTTPResponse:
    status = 200

    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class ProviderTests(unittest.TestCase):
    def test_request_hash_and_schema_are_stable(self):
        req_a = LLMRequest("x", "system", {"b": 1, "a": 2}, "v1", {"type": "object"})
        req_b = LLMRequest("x", "system", {"a": 2, "b": 1}, "v1", {"type": "object"})
        self.assertEqual(req_a.input_hash, req_b.input_hash)
        self.assertNotEqual(req_a.input_hash, LLMRequest("x", "system", {"a": 3}, "v1").input_hash)

    def test_fixture_replay_is_offline_and_structured(self):
        provider = FixtureReplayProvider(FIXTURE_DIR)
        meeting = json.loads((FIXTURE_DIR / "meetings.jsonl").read_text(encoding="utf-8").splitlines()[0])
        segments = [
            json.loads(line)
            for line in (FIXTURE_DIR / "segments.jsonl").read_text(encoding="utf-8").splitlines()
            if json.loads(line).get("meeting_id") == meeting["meeting_id"]
        ]
        response = provider.complete_json(build_meeting_extraction_request(meeting, segments))
        self.assertEqual(response.provider, "fixture-replay")
        self.assertEqual(response.cost_usd, 0.0)
        self.assertEqual(response.data["meeting_id"], "meeting_001")
        self.assertTrue(response.data["evidence_segment_ids"])
        self.assertTrue(response.raw_metadata["warning"])

    def test_openai_compatible_parses_json_and_cost(self):
        payload = {
            "id": "chatcmpl-test",
            "model": "demo",
            "choices": [{"message": {"content": "```json\n{\"ok\": true}\n```"}}],
            "usage": {"prompt_tokens": 1000, "completion_tokens": 500, "total_tokens": 1500},
        }
        provider = OpenAICompatibleProvider(
            OpenAICompatibleConfig(
                base_url="https://example.invalid/v1",
                model="demo",
                api_key="secret-not-printed",
                input_usd_per_1m=1.0,
                output_usd_per_1m=2.0,
            )
        )
        provider_module = OpenAICompatibleProvider.__module__
        with patch(f"{provider_module}.urllib.request.urlopen", return_value=FakeHTTPResponse(payload)) as urlopen:
            response = provider.complete_json(LLMRequest("x", "system", {"x": 1}, "v1"))
        self.assertEqual(response.data, {"ok": True})
        self.assertEqual(response.usage, Usage(1000, 500, 1500, estimated=False))
        self.assertEqual(response.cost_usd, 0.002)
        request = urlopen.call_args.args[0]
        body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(body["model"], "demo")
        self.assertEqual(request.headers.get("Authorization"), "Bearer secret-not-printed")
        self.assertNotIn("secret-not-printed", request.data.decode("utf-8"))

    def test_fixture_evaluation_is_a_regression_gate(self):
        result = evaluate_provider(FixtureReplayProvider(FIXTURE_DIR), FIXTURE_DIR)
        self.assertEqual(result["errors"], 0)
        self.assertEqual(result["meetings"], 10)
        self.assertEqual(result["macro"]["topics_f1"], 1.0)
        self.assertEqual(result["macro"]["evidence_f1"], 1.0)
        self.assertEqual(result["macro"]["claims_f1"], 1.0)


if __name__ == "__main__":
    unittest.main()
