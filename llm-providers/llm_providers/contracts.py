"""Provider-neutral request/response contracts.

This package deliberately contains no vendor SDK.  The Go platform or a Python
orchestrator builds :class:`LLMRequest`, selects a provider, and validates the
returned candidate before it becomes a meeting artifact or a memory claim.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Optional


class ProviderError(RuntimeError):
    """A provider was unavailable, rejected the request, or returned bad data."""


def canonical_json(value: Any) -> str:
    """Serialize values deterministically for cache keys and audit hashes."""

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=repr)


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class LLMRequest:
    """The only input shape accepted by every provider.

    ``user_payload`` must contain the evidence or structured candidate supplied
    by the owning module.  A provider must not fetch extra meeting data from a
    database.  ``metadata`` is operational context and is intentionally not
    included in ``input_hash`` so trace IDs do not invalidate a cached result.
    """

    operation: str
    system_prompt: str
    user_payload: Mapping[str, Any]
    prompt_version: str
    response_schema: Optional[Mapping[str, Any]] = None
    model_hint: Optional[str] = None
    schema_version: str = "llm-contract-v1"
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
                "schema_version": self.schema_version,
                "model_hint": self.model_hint,
            }
        )

    def user_content(self) -> str:
        payload = canonical_json(self.user_payload)
        if not self.response_schema:
            return payload
        return payload + "\n\nRequired JSON schema:\n" + canonical_json(self.response_schema)

    def messages(self) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": self.user_content()},
        ]


@dataclass(frozen=True)
class Usage:
    """Token usage.  ``estimated`` prevents estimates being mistaken for billing data."""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    estimated: bool = False

    @classmethod
    def from_mapping(cls, value: Optional[Mapping[str, Any]]) -> "Usage":
        data = value or {}
        input_tokens = int(data.get("prompt_tokens", data.get("input_tokens", 0)) or 0)
        output_tokens = int(data.get("completion_tokens", data.get("output_tokens", 0)) or 0)
        total = int(data.get("total_tokens", input_tokens + output_tokens) or 0)
        return cls(input_tokens, output_tokens, total, estimated=not bool(value))

    @classmethod
    def estimate(cls, request: LLMRequest, output: Mapping[str, Any]) -> "Usage":
        input_tokens = max(1, (len(request.system_prompt) + len(request.user_content()) + 3) // 4)
        output_tokens = max(1, (len(canonical_json(output)) + 3) // 4)
        return cls(input_tokens, output_tokens, input_tokens + output_tokens, estimated=True)


@dataclass(frozen=True)
class LLMResponse:
    """Structured candidate plus non-sensitive provider run metadata."""

    data: Mapping[str, Any]
    provider: str
    model: str
    prompt_version: str
    input_hash: str
    schema_version: str = "llm-contract-v1"
    usage: Usage = field(default_factory=Usage)
    cost_usd: Optional[float] = None
    latency_ms: Optional[float] = None
    raw_metadata: Mapping[str, Any] = field(default_factory=dict)
    cached: bool = False

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["usage"] = asdict(self.usage)
        result["data"] = dict(self.data)
        result["raw_metadata"] = dict(self.raw_metadata)
        return result


def cost_usd(usage: Usage, input_rate: float | None, output_rate: float | None) -> float | None:
    """Calculate a transparent estimate; ``None`` means no rate was configured."""

    if input_rate is None and output_rate is None:
        return None
    total = 0.0
    if input_rate is not None:
        total += usage.input_tokens / 1_000_000.0 * float(input_rate)
    if output_rate is not None:
        total += usage.output_tokens / 1_000_000.0 * float(output_rate)
    return round(total, 10)


class LLMProvider:
    """Small runtime protocol kept as a base class for easy introspection."""

    name = "provider"

    def complete_json(self, request: LLMRequest) -> LLMResponse:  # pragma: no cover - interface only
        raise NotImplementedError


# Compatibility names used by early module adapters.  These are aliases, not
# second contracts, so 03/04 can migrate without converting payload objects.
ProviderRequest = LLMRequest
ProviderResponse = LLMResponse
JsonProvider = LLMProvider
