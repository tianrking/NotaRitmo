import pytest

from app.services.llm import LLMClient


class FakeResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {
            "choices": [{"message": {"content": '{"summary":{"text":"ok"}}'}}],
            "usage": {
                "prompt_tokens": 120,
                "completion_tokens": 30,
                "total_tokens": 150,
            },
        }


class FakeAsyncClient:
    calls: list[dict] = []

    def __init__(self, **_: object) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def post(self, url: str, *, headers: dict, json: dict):
        self.calls.append({"url": url, "headers": headers, "json": json})
        return FakeResponse()


@pytest.mark.asyncio
async def test_complete_json_is_one_versionable_openai_compatible_call(
    monkeypatch,
) -> None:
    FakeAsyncClient.calls.clear()
    monkeypatch.setattr("app.services.llm.httpx.AsyncClient", FakeAsyncClient)
    client = LLMClient()
    client.enabled = True
    client.base_url = "http://llm.test/v1"

    result, usage = await client.complete_json(system="system-v1", user="transcript-once")

    assert result == {"summary": {"text": "ok"}}
    assert usage == {"input_tokens": 120, "output_tokens": 30, "total_tokens": 150}
    assert len(FakeAsyncClient.calls) == 1
    payload = FakeAsyncClient.calls[0]["json"]
    assert payload["response_format"] == {"type": "json_object"}
    assert payload["messages"][1]["content"] == "transcript-once"
