"""LEGACY COMPATIBILITY MODULE — do not add new Provider implementations here.

The canonical Provider contracts and HTTP adapters now live in the top-level
``llm-providers/llm_providers`` package.  The classes below remain temporarily
for the original 04 evaluation imports and regression fixtures.  New 03/04/05
code, including ``run_llm_loop.py``, must import ``llm_providers`` directly.
This module is intentionally marked legacy so it can be removed after the
existing baseline evaluator is migrated without changing its public test names.

模型无关的结构化 LLM Provider 接口。

设计原则：

* 会议核心只依赖 ``complete_json``，不直接依赖某家 SDK；
* 请求中显式记录 input hash、prompt version 和 response schema；
* 响应中保留 provider/model/prompt/token/cost 元数据；
* 默认使用离线 ``FixtureReplayProvider`` 做契约回归，不会偷偷联网；
* ``OpenAICompatibleProvider`` 只使用 Python 标准库，适配 SaaS 或用户自建
  的 OpenAI-compatible HTTP endpoint。

这里的 FixtureReplayProvider 是测试夹具回放器，不能当作模型质量结果。它
用于验证编排、契约、评估器和下游存储是否正确。
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Protocol, Sequence, Tuple


class ProviderError(RuntimeError):
    """LLM Provider 调用、解析或配置错误。"""


def _json_default(value: Any) -> str:
    return repr(value)


def canonical_json(value: Any) -> str:
    """用于哈希的稳定 JSON；不包含 API key 等运行时秘密。"""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    )


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class LLMRequest:
    """所有模型调用的统一请求。

    ``user_payload`` 是会议事实输入或候选证据，不允许 Provider 私自从数据库
    再读数据。上层可据此实现缓存、审计和“避免重复传全文”的策略。
    """

    operation: str
    system_prompt: str
    user_payload: Mapping[str, Any]
    prompt_version: str
    response_schema: Optional[Mapping[str, Any]] = None
    model_hint: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def input_hash(self) -> str:
        return sha256_json(
            {
                "operation": self.operation,
                "system_prompt": self.system_prompt,
                "user_payload": self.user_payload,
                "prompt_version": self.prompt_version,
                "response_schema": self.response_schema,
            }
        )

    def messages(self) -> List[Dict[str, str]]:
        return [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": canonical_json(self.user_payload)},
        ]


@dataclass(frozen=True)
class Usage:
    """Provider usage；``estimated`` 表示 API 没返回真实 token 用量。"""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    estimated: bool = False

    @classmethod
    def from_api(cls, usage: Optional[Mapping[str, Any]]) -> "Usage":
        usage = usage or {}
        input_tokens = int(usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0)
        output_tokens = int(usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0)
        total = int(usage.get("total_tokens", input_tokens + output_tokens) or 0)
        return cls(input_tokens, output_tokens, total, estimated=not bool(usage))

    @classmethod
    def estimate(cls, request: LLMRequest, output: Mapping[str, Any]) -> "Usage":
        # 这是缓存/离线模式的粗略字符估计，不冒充 tokenizer 计费结果。
        input_tokens = max(1, (len(request.system_prompt) + len(canonical_json(request.user_payload)) + 3) // 4)
        output_tokens = max(1, (len(canonical_json(output)) + 3) // 4)
        return cls(input_tokens, output_tokens, input_tokens + output_tokens, estimated=True)


@dataclass(frozen=True)
class LLMResponse:
    """结构化结果和可审计元数据。"""

    data: Mapping[str, Any]
    provider: str
    model: str
    prompt_version: str
    input_hash: str
    usage: Usage = field(default_factory=Usage)
    cost_usd: Optional[float] = None
    latency_ms: Optional[float] = None
    raw_metadata: Mapping[str, Any] = field(default_factory=dict)
    cached: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "data": dict(self.data),
            "provider": self.provider,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "input_hash": self.input_hash,
            "usage": asdict(self.usage),
            "cost_usd": self.cost_usd,
            "latency_ms": self.latency_ms,
            "raw_metadata": dict(self.raw_metadata),
            "cached": self.cached,
        }


class LLMProvider(Protocol):
    """会议理解、Claim 抽取和受证据约束问答共享的最小 Provider 接口。"""

    name: str

    def complete_json(self, request: LLMRequest) -> LLMResponse:
        ...


def _cost_usd(usage: Usage, input_rate: Optional[float], output_rate: Optional[float]) -> Optional[float]:
    if input_rate is None and output_rate is None:
        return None
    value = 0.0
    if input_rate is not None:
        value += usage.input_tokens / 1_000_000.0 * float(input_rate)
    if output_rate is not None:
        value += usage.output_tokens / 1_000_000.0 * float(output_rate)
    return round(value, 10)


@dataclass(frozen=True)
class OpenAICompatibleConfig:
    """OpenAI-compatible HTTP endpoint 配置。

    ``base_url`` 可以是 ``https://api.example/v1``，也可以直接包含
    ``/chat/completions``。不要求 API key，方便接局域网服务；SaaS 端点通常
    需要设置 ``api_key``。
    """

    base_url: str
    model: str
    api_key: str = ""
    timeout_s: float = 90.0
    chat_path: str = "/chat/completions"
    input_usd_per_1m: Optional[float] = None
    output_usd_per_1m: Optional[float] = None
    temperature: float = 0.0
    json_mode: bool = True

    @classmethod
    def from_env(cls, prefix: str = "LLM_") -> "OpenAICompatibleConfig":
        base_url = os.getenv(prefix + "BASE_URL", "").strip()
        model = os.getenv(prefix + "MODEL", "").strip()
        if not base_url or not model:
            raise ProviderError(
                "OpenAI-compatible Provider requires LLM_BASE_URL and LLM_MODEL; "
                "the default evaluation mode is offline fixture replay."
            )
        def _float(name: str, default: Optional[float]) -> Optional[float]:
            raw = os.getenv(prefix + name, "").strip()
            return default if not raw else float(raw)
        return cls(
            base_url=base_url,
            model=model,
            api_key=os.getenv(prefix + "API_KEY", ""),
            timeout_s=float(os.getenv(prefix + "TIMEOUT_S", "90")),
            chat_path=os.getenv(prefix + "CHAT_PATH", "/chat/completions"),
            input_usd_per_1m=_float("INPUT_USD_PER_1M", None),
            output_usd_per_1m=_float("OUTPUT_USD_PER_1M", None),
            temperature=float(os.getenv(prefix + "TEMPERATURE", "0")),
            json_mode=os.getenv(prefix + "JSON_MODE", "1").lower() not in {"0", "false", "no"},
        )


class OpenAICompatibleProvider:
    """通过标准库调用 OpenAI-compatible ``/chat/completions``。"""

    name = "openai-compatible"

    def __init__(self, config: OpenAICompatibleConfig):
        self.config = config

    def _endpoint(self) -> str:
        base = self.config.base_url.rstrip("/")
        if base.endswith("/chat/completions"):
            return base
        path = self.config.chat_path
        if not path.startswith("/"):
            path = "/" + path
        return base + path

    def _safe_endpoint(self) -> str:
        """元数据只记录路由位置，不把 URL query 中可能误放的密钥写入结果。"""

        endpoint = self._endpoint()
        parsed = urllib.parse.urlsplit(endpoint)
        if not parsed.scheme or not parsed.netloc:
            return endpoint.split("?", 1)[0].split("#", 1)[0]
        return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))

    @staticmethod
    def _content(response: Mapping[str, Any]) -> str:
        try:
            content = response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError("OpenAI-compatible response has no choices[0].message.content") from exc
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: List[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, Mapping) and isinstance(item.get("text"), str):
                    parts.append(item["text"])
            return "".join(parts)
        raise ProviderError("OpenAI-compatible content must be a string or content-part list")

    @staticmethod
    def _parse_json(text: str) -> Dict[str, Any]:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            cleaned = "\n".join(lines).strip()
        try:
            value = json.loads(cleaned)
        except json.JSONDecodeError:
            # 少量 Provider 会在 JSON 前后加一句话；仅提取首个完整对象。
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start < 0 or end <= start:
                raise ProviderError("LLM response is not valid JSON")
            try:
                value = json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError as exc:
                raise ProviderError("LLM response is not valid JSON") from exc
        if not isinstance(value, dict):
            raise ProviderError("structured LLM response must be a JSON object")
        return value

    def complete_json(self, request: LLMRequest) -> LLMResponse:
        payload: Dict[str, Any] = {
            "model": request.model_hint or self.config.model,
            "messages": request.messages(),
            "temperature": self.config.temperature,
        }
        if self.config.json_mode:
            payload["response_format"] = {"type": "json_object"}
        if request.response_schema:
            # response_schema 也写入 user message，兼容不支持 strict JSON schema 的端点。
            payload["messages"][-1]["content"] += "\n\nRequired JSON schema:\n" + canonical_json(request.response_schema)
        body = canonical_json(payload).encode("utf-8")
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = "Bearer " + self.config.api_key
        req = urllib.request.Request(self._endpoint(), data=body, headers=headers, method="POST")
        started = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=self.config.timeout_s) as raw:
                raw_body = raw.read()
                status = int(getattr(raw, "status", 200))
                response_json = json.loads(raw_body.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                detail = exc.read().decode("utf-8", errors="replace")[:1000]
            except Exception:
                detail = ""
            raise ProviderError("LLM HTTP %s: %s" % (exc.code, detail)) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ProviderError("LLM endpoint request failed: %s" % exc) from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProviderError("LLM endpoint returned invalid JSON") from exc
        if not isinstance(response_json, Mapping):
            raise ProviderError("LLM endpoint returned a non-object JSON response")
        data = self._parse_json(self._content(response_json))
        usage = Usage.from_api(response_json.get("usage"))
        if not response_json.get("usage"):
            usage = Usage.estimate(request, data)
        latency_ms = round((time.monotonic() - started) * 1000.0, 3)
        return LLMResponse(
            data=data,
            provider=self.name,
            model=str(response_json.get("model") or request.model_hint or self.config.model),
            prompt_version=request.prompt_version,
            input_hash=request.input_hash,
            usage=usage,
            cost_usd=_cost_usd(usage, self.config.input_usd_per_1m, self.config.output_usd_per_1m),
            latency_ms=latency_ms,
            raw_metadata={
                "http_status": status,
                "request_id": response_json.get("id"),
                "endpoint": self._safe_endpoint(),
            },
        )


class FixtureReplayProvider:
    """离线回放 gold fixture 的契约 Provider。

    它不是 ASR、不是 LLM，也不代表实际模型的准确率。它的价值是让 CI 在无网络、
    无 API key 时验证：请求 schema、Metadata、Artifact/Claim 连接和评估器流程。
    """

    name = "fixture-replay"

    def __init__(self, fixture_dir: Path):
        self.fixture_dir = Path(fixture_dir)
        self.artifacts = self._load_index(self.fixture_dir / "gold_artifacts.jsonl", "meeting_id")
        self.claims = self._load_claims(self.fixture_dir / "gold_claims.jsonl")

    @staticmethod
    def _read_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ProviderError("invalid JSONL %s:%d" % (path, line_number)) from exc
                if not isinstance(value, dict):
                    raise ProviderError("JSONL row must be an object: %s:%d" % (path, line_number))
                yield value

    @classmethod
    def _load_index(cls, path: Path, key: str) -> Dict[str, Dict[str, Any]]:
        return {str(row[key]): row for row in cls._read_jsonl(path)}

    @classmethod
    def _load_claims(cls, path: Path) -> Dict[str, List[Dict[str, Any]]]:
        result: Dict[str, List[Dict[str, Any]]] = {}
        for row in cls._read_jsonl(path):
            result.setdefault(str(row.get("source_meeting_id", "")), []).append(row)
        return result

    def complete_json(self, request: LLMRequest) -> LLMResponse:
        if request.operation != "meeting.extract":
            raise ProviderError("fixture replay only supports operation meeting.extract")
        meeting = request.user_payload.get("meeting", {})
        meeting_id = str(meeting.get("meeting_id", "")) if isinstance(meeting, Mapping) else ""
        if meeting_id not in self.artifacts:
            raise ProviderError("fixture has no gold artifact for %s" % meeting_id)
        gold = self.artifacts[meeting_id]
        output = {
            "meeting_id": meeting_id,
            "summary": "[fixture replay; not an LLM result]",
            "topics": list(gold.get("expected_topics", [])),
            "decisions": list(gold.get("expected_decisions", [])),
            "action_items": list(gold.get("expected_action_items", [])),
            "risks": list(gold.get("expected_risks", [])),
            "evidence_segment_ids": list(gold.get("evidence_segment_ids", [])),
            "claims": [dict(row) for row in self.claims.get(meeting_id, [])],
        }
        usage = Usage.estimate(request, output)
        return LLMResponse(
            data=output,
            provider=self.name,
            model="gold-fixture",
            prompt_version=request.prompt_version,
            input_hash=request.input_hash,
            usage=usage,
            cost_usd=0.0,
            latency_ms=0.0,
            raw_metadata={
                "mode": "fixture_replay",
                "warning": "contract regression only; do not report as LLM quality",
            },
        )


def build_meeting_extraction_request(
    meeting: Mapping[str, Any],
    segments: Sequence[Mapping[str, Any]],
    prompt_version: str = "meeting-extract-v1",
) -> LLMRequest:
    """构造单会议理解请求；输出只允许引用输入里的 segment_id。"""

    schema = {
        "type": "object",
        "required": ["meeting_id", "summary", "topics", "decisions", "action_items", "risks", "evidence_segment_ids", "claims"],
        "properties": {
            "meeting_id": {"type": "string"},
            "summary": {"type": "string"},
            "topics": {"type": "array", "items": {"type": "string"}},
            "decisions": {"type": "array"},
            "action_items": {"type": "array"},
            "risks": {"type": "array"},
            "evidence_segment_ids": {"type": "array", "items": {"type": "string"}},
            "claims": {"type": "array"},
        },
    }
    system = (
        "你是会议理解抽取器。只根据输入的 TranscriptBundle 提取结构化结果；"
        "不编造原文没有的事实、Speaker、时间或截止日期。每个决策、待办、风险和 Claim "
        "必须包含 evidence_segment_ids，且只能使用输入中的 segment_id。没有证据就不要输出。"
        "返回严格 JSON，不要 Markdown。"
    )
    payload = {
        "meeting": dict(meeting),
        "segments": [dict(segment) for segment in segments],
        "output_contract": "meeting_artifact_v1",
    }
    return LLMRequest(
        operation="meeting.extract",
        system_prompt=system,
        user_payload=payload,
        prompt_version=prompt_version,
        response_schema=schema,
        metadata={"tenant_id": meeting.get("tenant_id"), "meeting_id": meeting.get("meeting_id")},
    )


def build_answer_request(
    question: str,
    candidates: Sequence[Mapping[str, Any]],
    tenant_id: str,
    prompt_version: str = "evidence-answer-v1",
) -> LLMRequest:
    """构造受证据约束的回答请求；no-answer 由确定性策略层最终裁决。"""

    schema = {
        "type": "object",
        "required": ["answer", "no_answer", "confidence", "citation_ids"],
        "properties": {
            "answer": {"type": ["string", "null"]},
            "no_answer": {"type": "boolean"},
            "confidence": {"type": "number"},
            "citation_ids": {"type": "array", "items": {"type": "string"}},
        },
    }
    system = (
        "你是证据约束的会议问答生成器。只能使用 candidates 中的事实和引用；"
        "如果证据不足，answer 必须为 null 并将 no_answer 设为 true。不要猜测。"
        "返回严格 JSON，不要 Markdown。"
    )
    return LLMRequest(
        operation="research.answer",
        system_prompt=system,
        user_payload={"tenant_id": tenant_id, "question": question, "candidates": [dict(c) for c in candidates]},
        prompt_version=prompt_version,
        response_schema=schema,
        metadata={"tenant_id": tenant_id},
    )
