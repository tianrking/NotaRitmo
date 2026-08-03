"""LLM adapters for the offline baseline.

No network client is constructed here. OfflineLLMProvider is the safe default
and fails explicitly if a caller invokes a model without configuring a provider.
A future SaaS or OpenAI-compatible adapter only has to implement LLMProvider.
"""

from __future__ import annotations

from typing import Any, Mapping

from ports import LLMResponse


class LLMNotConfiguredError(RuntimeError):
    """Raised instead of silently making an unexpected network request."""


class OfflineLLMProvider:
    """Explicit no-network provider used by tests and local development."""

    provider_id = "offline"
    model = None

    def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_format: str = "text",
        metadata: Mapping[str, Any] | None = None,
    ) -> LLMResponse:
        raise LLMNotConfiguredError(
            "No LLM provider is configured. Configure a provider explicitly "
            "before enabling model-backed extraction or answering."
        )


class StaticLLMProvider:
    """Deterministic provider useful for contract tests; never performs I/O."""

    def __init__(
        self,
        response: str | dict[str, Any] | list[Any],
        *,
        provider_id: str = "static",
        model: str | None = "fixture",
    ) -> None:
        self.response = response
        self.provider_id = provider_id
        self.model = model

    def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_format: str = "text",
        metadata: Mapping[str, Any] | None = None,
    ) -> LLMResponse:
        if response_format == "json" and not isinstance(self.response, (dict, list)):
            raise TypeError("StaticLLMProvider json responses must be dict or list")
        if response_format != "json" and not isinstance(self.response, str):
            raise TypeError("StaticLLMProvider text responses must be str")
        return LLMResponse(
            text=self.response if isinstance(self.response, str) else None,
            data=self.response if not isinstance(self.response, str) else None,
            provider=self.provider_id,
            model=self.model,
        )
