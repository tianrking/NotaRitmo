import json
import re
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

    async def complete_json(
        self,
        *,
        system: str,
        user: str,
    ) -> tuple[dict[str, Any], dict[str, int]]:
        if not self.enabled:
            raise RuntimeError("LLM is disabled")
        payload = {
            "model": settings.llm_model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        async with httpx.AsyncClient(timeout=300) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers=self.headers,
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
        content = data["choices"][0]["message"]["content"]
        if isinstance(content, list):
            content = "".join(
                str(item.get("text", "")) if isinstance(item, dict) else str(item)
                for item in content
            )
        try:
            result = json.loads(content)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", str(content), re.DOTALL)
            if not match:
                raise ValueError("LLM did not return a JSON object") from None
            result = json.loads(match.group(0))
        if not isinstance(result, dict):
            raise ValueError("LLM JSON root must be an object")
        usage = data.get("usage") or {}
        input_tokens = int(usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0)
        output_tokens = int(
            usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0
        )
        return result, {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": int(
                usage.get("total_tokens", input_tokens + output_tokens) or 0
            ),
        }

    async def answer_with_context(
        self, query: str, context: dict[str, Any]
    ) -> str | None:
        if not self.enabled:
            return None
        serialized = json.dumps(context, ensure_ascii=False, default=str)
        if len(serialized) > 100_000:
            serialized = serialized[:100_000]
        payload = {
            "model": settings.llm_model,
            "temperature": 0.1,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是 NotaRitmo 会议分析助手。只能使用输入中的会议原文、"
                        "结构化记忆和摘要回答。所有判断必须能由证据支持；"
                        "信息不足时明确说明，禁止编造负责人、日期、决定和会议。"
                    ),
                },
                {
                    "role": "user",
                    "content": f"问题：{query}\n\n授权会议上下文：\n{serialized}",
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
