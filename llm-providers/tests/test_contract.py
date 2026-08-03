from __future__ import annotations

import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from llm_providers import (
    AnthropicCompatibleProvider,
    InMemoryResponseCache,
    LLMRequest,
    OfflineFixtureProvider,
    OpenAICompatibleProvider,
    ProviderConfig,
    ProviderRouter,
)


class _MockHandler(BaseHTTPRequestHandler):
    calls: dict[str, int] = {}
    fail_once: set[str] = set()
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args: Any) -> None:
        return

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        _MockHandler.calls[self.path] = _MockHandler.calls.get(self.path, 0) + 1
        if self.path in _MockHandler.fail_once and _MockHandler.calls[self.path] == 1:
            body = b'{"error":"retry me"}'
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        length = int(self.headers.get("Content-Length", "0"))
        request_body = json.loads(self.rfile.read(length).decode("utf-8"))
        model = request_body.get("model")
        payload = {"answer": "mock grounded answer", "no_answer": False, "evidence": ["seg-1"]}
        if self.path.endswith("/chat/completions"):
            response = {
                "id": "mock-request-1",
                "model": model,
                "choices": [{"message": {"role": "assistant", "content": json.dumps(payload)}}],
                "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
            }
        elif self.path.endswith("/messages"):
            response = {
                "id": "mock-message-1",
                "model": model,
                "content": [{"type": "text", "text": json.dumps(payload)}],
                "usage": {"input_tokens": 13, "output_tokens": 5},
            }
        else:
            response = {"error": "unknown path"}
        raw = json.dumps(response).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


class ProviderContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _MockHandler.calls = {}
        _MockHandler.fail_once = {"/v1/chat/completions"}
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _MockHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = "http://127.0.0.1:%d" % cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def request(self) -> LLMRequest:
        return LLMRequest(
            operation="research.answer",
            system_prompt="Only answer from evidence.",
            user_payload={"tenant_id": "tenant-a", "question": "What?", "evidence": [{"id": "seg-1"}]},
            prompt_version="answer-v2",
            response_schema={"type": "object"},
            model_hint="mock-model",
            metadata={"trace_id": "trace-1"},
        )

    def test_openai_compatible_retry_usage_cost_and_metadata(self) -> None:
        config = ProviderConfig(
            api_style="openai", provider="openai-compatible", base_url=self.base_url,
            model="mock-model", api_key="secret-not-logged", max_retries=1,
            retry_backoff_s=0, input_usd_per_1m=1, output_usd_per_1m=2,
        )
        response = OpenAICompatibleProvider(config).complete_json(self.request())
        self.assertEqual(response.data["answer"], "mock grounded answer")
        self.assertEqual(response.usage.total_tokens, 18)
        self.assertAlmostEqual(response.cost_usd or 0, 0.000025)
        self.assertEqual(response.raw_metadata["retries"], 1)
        self.assertNotIn("secret-not-logged", json.dumps(response.to_dict()))
        self.assertEqual(_MockHandler.calls["/v1/chat/completions"], 2)

    def test_anthropic_compatible_contract(self) -> None:
        config = ProviderConfig(
            api_style="anthropic", provider="anthropic-compatible", base_url=self.base_url,
            model="glm-5.2", api_key="secret-not-logged", max_retries=0,
        )
        response = AnthropicCompatibleProvider(config).complete_json(self.request())
        self.assertEqual(response.provider, "anthropic-compatible")
        self.assertEqual(response.usage.input_tokens, 13)
        self.assertEqual(response.data["evidence"], ["seg-1"])
        self.assertEqual(response.raw_metadata["endpoint"].split("?")[0], self.base_url + "/v1/messages")

    def test_offline_is_default_and_never_networks(self) -> None:
        request = self.request()
        provider = ProviderRouter.from_env(ProviderConfig())
        response = provider.complete_json(request)
        self.assertEqual(response.provider, "offline-fixture")
        self.assertEqual(response.cost_usd, 0.0)

    def test_cache_marks_second_response(self) -> None:
        cache = InMemoryResponseCache()
        router = ProviderRouter({"fixture": OfflineFixtureProvider()}, "fixture", cache=cache)
        first = router.complete_json(self.request())
        second = router.complete_json(self.request())
        self.assertFalse(first.cached)
        self.assertTrue(second.cached)
        self.assertEqual(first.input_hash, second.input_hash)

    def test_env_alias_and_secret_free_public_config(self) -> None:
        names = ["LLM_PROVIDER", "LLM_API_STYLE", "LLM_BASE_URL", "LLM_MODEL", "LLM_API_KEY", "ANTHROPIC_AUTH_TOKEN"]
        old = {name: os.environ.get(name) for name in names}
        try:
            os.environ.pop("LLM_PROVIDER", None)
            os.environ["LLM_API_STYLE"] = "anthropic"
            os.environ["ANTHROPIC_BASE_URL"] = "https://open.bigmodel.cn/api/anthropic"
            os.environ["ANTHROPIC_MODEL"] = "glm-5.2"
            os.environ.pop("LLM_API_KEY", None)
            os.environ["ANTHROPIC_AUTH_TOKEN"] = "must-not-be-serialized"
            config = ProviderConfig.from_env()
            self.assertEqual(config.api_style, "anthropic")
            self.assertEqual(config.model, "glm-5.2")
            self.assertNotIn("must-not-be-serialized", json.dumps(config.public_dict()))
        finally:
            for name, value in old.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value


if __name__ == "__main__":
    unittest.main()
