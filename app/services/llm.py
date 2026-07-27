from typing import Any

import httpx

from app.config import settings


class LLMClient:
    def __init__(self) -> None:
        self.enabled = bool(settings.llm_enabled and settings.llm_model)
        self.base_url = settings.llm_base_url.rstrip("/")
        self.headers = {"Content-Type": "application/json"}
        if settings.llm_api_key:
            self.headers["Authorization"] = f"Bearer {settings.llm_api_key}"

    async def answer(self, query: str, evidence: list[dict[str, Any]]) -> str | None:
        if not self.enabled:
            return None
        evidence_text = "\n".join(
            (
                f"[{index + 1}] 会议={item['meeting_title']} "
                f"Speaker={item['speaker_name']} "
                f"时间={item['start_ms']}-{item['end_ms']}ms "
                f"原文={item['text']}"
            )
            for index, item in enumerate(evidence)
        )
        payload = {
            "model": settings.llm_model,
            "temperature": 0.1,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是会议证据分析助手。只能根据给定证据回答；"
                        "证据不足时明确说明，不得补造负责人、日期或结论。"
                    ),
                },
                {
                    "role": "user",
                    "content": f"问题：{query}\n\n证据：\n{evidence_text}",
                },
            ],
        }
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers=self.headers,
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]

    async def embed(self, texts: list[str]) -> list[list[float]] | None:
        if not settings.embedding_model or not texts:
            return None
        payload = {"model": settings.embedding_model, "input": texts}
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                f"{self.base_url}/embeddings",
                headers=self.headers,
                json=payload,
            )
            response.raise_for_status()
            ordered = sorted(response.json()["data"], key=lambda item: item["index"])
            return [item["embedding"] for item in ordered]

