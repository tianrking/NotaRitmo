"""Offline, OpenAI-compatible and Anthropic-compatible providers.

The HTTP adapters use only the Python standard library.  They own transport
concerns (timeouts, bounded retries and response parsing); meeting modules own
prompt construction, evidence validation, state and persistence.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Mapping, MutableMapping, Optional

from .config import ProviderConfig
from .contracts import LLMProvider, LLMRequest, LLMResponse, ProviderError, Usage, cost_usd
from .security import redact, safe_url


def _parse_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].lstrip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start < 0 or end <= start:
            raise ProviderError("remote LLM response is not valid JSON")
        try:
            value = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ProviderError("remote LLM response is not valid JSON") from exc
    if not isinstance(value, dict):
        raise ProviderError("structured LLM response must be a JSON object")
    return value


def _content_from_openai(value: Mapping[str, Any]) -> str:
    try:
        content = value["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ProviderError("OpenAI-compatible response has no choices[0].message.content") from exc
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            item if isinstance(item, str) else str(item.get("text", ""))
            for item in content
            if isinstance(item, (str, Mapping))
        )
    raise ProviderError("OpenAI-compatible content must be a string or content-part list")


def _content_from_anthropic(value: Mapping[str, Any]) -> str:
    content = value.get("content")
    if not isinstance(content, list):
        raise ProviderError("Anthropic-compatible response has no content blocks")
    parts = []
    for item in content:
        if isinstance(item, Mapping) and item.get("type") == "text":
            parts.append(str(item.get("text", "")))
    if not parts:
        raise ProviderError("Anthropic-compatible response has no text content")
    return "".join(parts)


class OfflineFixtureProvider(LLMProvider):
    """Deterministic, no-network provider used by default and in CI.

    ``responses`` can map an operation to a JSON object.  The fallback response
    deliberately says it is a fixture and contains no meeting facts, so it
    cannot be mistaken for a model quality result.
    """

    name = "offline-fixture"

    def __init__(self, responses: Optional[Mapping[str, Mapping[str, Any]]] = None, model: str = "fixture"):
        self.responses = {str(key): dict(value) for key, value in (responses or {}).items()}
        self.model = model

    def complete_json(self, request: LLMRequest) -> LLMResponse:
        output = dict(
            self.responses.get(
                request.operation,
                {
                    "ok": True,
                    "operation": request.operation,
                    "summary": "offline fixture response; not an LLM result",
                    "evidence": [],
                },
            )
        )
        usage = Usage.estimate(request, output)
        return LLMResponse(
            data=output,
            provider=self.name,
            model=self.model,
            prompt_version=request.prompt_version,
            input_hash=request.input_hash,
            schema_version=request.schema_version,
            usage=usage,
            cost_usd=0.0,
            latency_ms=0.0,
            raw_metadata={"mode": "offline_fixture", "warning": "contract only; not model quality"},
        )


class _HttpProvider(LLMProvider):
    """Shared safe transport implementation for both compatible protocols."""

    name = "http"
    style = "http"

    def __init__(self, config: ProviderConfig, *, opener: Any = urllib.request.urlopen):
        self.config = config
        self._opener = opener

    def _request_body(self, request: LLMRequest) -> tuple[str, dict[str, Any]]:  # pragma: no cover - abstract
        raise NotImplementedError

    def _parse_response(self, response: Mapping[str, Any]) -> tuple[str, Usage]:  # pragma: no cover - abstract
        raise NotImplementedError

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.config.api_key:
            if self.config.auth_header.lower() == "authorization":
                headers["Authorization"] = "Bearer " + self.config.api_key
            else:
                headers[self.config.auth_header] = self.config.api_key
        if self.style == "anthropic":
            headers.setdefault("anthropic-version", "2023-06-01")
        return headers

    def _call(self, request: LLMRequest) -> tuple[Mapping[str, Any], float, int]:
        endpoint, payload = self._request_body(request)
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        http_request = urllib.request.Request(endpoint, data=body, headers=self._headers(), method="POST")
        started = time.monotonic()
        retries = 0
        last_error: Optional[Exception] = None
        attempts = max(0, int(self.config.max_retries)) + 1
        for attempt in range(attempts):
            try:
                with self._opener(http_request, timeout=self.config.timeout_s) as raw:
                    raw_body = raw.read()
                    status = int(getattr(raw, "status", 200))
                if status >= 500:
                    raise urllib.error.HTTPError(endpoint, status, "server error", hdrs=None, fp=None)
                response = json.loads(raw_body.decode("utf-8"))
                if not isinstance(response, Mapping):
                    raise ProviderError("remote LLM endpoint returned a non-object JSON response")
                return response, round((time.monotonic() - started) * 1000.0, 3), retries
            except urllib.error.HTTPError as exc:
                last_error = exc
                retryable = exc.code in {408, 409, 425, 429} or exc.code >= 500
                if not retryable or attempt + 1 >= attempts:
                    detail = ""
                    if getattr(exc, "fp", None) is not None:
                        try:
                            detail = exc.read().decode("utf-8", errors="replace")[:500]
                        except Exception:
                            detail = ""
                    raise ProviderError(f"LLM HTTP {exc.code}: {detail}") from exc
            except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
                last_error = exc
                if attempt + 1 >= attempts:
                    raise ProviderError("LLM endpoint request failed: " + str(exc)) from exc
            if attempt + 1 < attempts:
                retries += 1
                time.sleep(max(0.0, self.config.retry_backoff_s) * (2**attempt))
        raise ProviderError("LLM endpoint request failed: " + str(last_error))

    def complete_json(self, request: LLMRequest) -> LLMResponse:
        response, latency_ms, retries = self._call(request)
        text, usage = self._parse_response(response)
        if not response.get("usage"):
            parsed = _parse_json_object(text)
            usage = Usage.estimate(request, parsed)
        data = _parse_json_object(text)
        return LLMResponse(
            data=data,
            provider=self.name,
            model=str(response.get("model") or request.model_hint or self.config.model),
            prompt_version=request.prompt_version,
            input_hash=request.input_hash,
            schema_version=request.schema_version,
            usage=usage,
            cost_usd=cost_usd(usage, self.config.input_usd_per_1m, self.config.output_usd_per_1m),
            latency_ms=latency_ms,
            raw_metadata=redact(
                {
                    "http_status": 200,
                    "request_id": response.get("id"),
                    "endpoint": safe_url(self._request_body(request)[0]),
                    "retries": retries,
                }
            ),
        )


class OpenAICompatibleProvider(_HttpProvider):
    """OpenAI ``/chat/completions`` compatible endpoint."""

    name = "openai-compatible"
    style = "openai"

    def _endpoint(self) -> str:
        base = self.config.base_url.rstrip("/")
        if base.endswith("/chat/completions"):
            return base
        path = "/chat/completions"
        if base.endswith("/v1"):
            return base + path
        return base + "/v1" + path if "/v1" not in urllib.parse.urlsplit(base).path else base + path

    def _request_body(self, request: LLMRequest) -> tuple[str, dict[str, Any]]:
        body: dict[str, Any] = {
            "model": request.model_hint or self.config.model,
            "messages": request.messages(),
            "temperature": self.config.temperature,
        }
        if self.config.json_mode:
            body["response_format"] = {"type": "json_object"}
        return self._endpoint(), body

    def _parse_response(self, response: Mapping[str, Any]) -> tuple[str, Usage]:
        return _content_from_openai(response), Usage.from_mapping(response.get("usage"))


class AnthropicCompatibleProvider(_HttpProvider):
    """Anthropic Messages-compatible endpoint, including BigModel routing."""

    name = "anthropic-compatible"
    style = "anthropic"

    def _endpoint(self) -> str:
        base = self.config.base_url.rstrip("/")
        if base.endswith("/messages"):
            return base
        if base.endswith("/v1"):
            return base + "/messages"
        return base + "/v1/messages"

    def _request_body(self, request: LLMRequest) -> tuple[str, dict[str, Any]]:
        return self._endpoint(), {
            "model": request.model_hint or self.config.model,
            "system": request.system_prompt,
            "messages": [{"role": "user", "content": request.user_content()}],
            "max_tokens": self.config.max_tokens,
            "temperature": self.config.temperature,
        }

    def _parse_response(self, response: Mapping[str, Any]) -> tuple[str, Usage]:
        return _content_from_anthropic(response), Usage.from_mapping(response.get("usage"))
