"""Environment-only provider configuration.

The repository never contains a token.  ``from_env`` accepts aliases used by
the BigModel Anthropic-compatible route, but secret values are only read at
runtime and are never included in ``repr`` or serialized metadata.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from .contracts import ProviderError
from .security import safe_url


def _first_env(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return default


def _optional_float(name: str) -> Optional[float]:
    raw = os.getenv(name, "").strip()
    return None if not raw else float(raw)


@dataclass(frozen=True)
class ProviderConfig:
    provider: str = "offline"
    api_style: str = "offline"
    base_url: str = ""
    model: str = "fixture"
    api_key: str = ""
    timeout_s: float = 60.0
    max_retries: int = 2
    retry_backoff_s: float = 0.25
    max_tokens: int = 2048
    temperature: float = 0.0
    input_usd_per_1m: Optional[float] = None
    output_usd_per_1m: Optional[float] = None
    json_mode: bool = True
    auth_header: str = "x-api-key"

    def public_dict(self) -> dict[str, object]:
        """Return config suitable for logs; ``api_key`` is intentionally absent."""

        return {
            "provider": self.provider,
            "api_style": self.api_style,
            "base_url": safe_url(self.base_url),
            "model": self.model,
            "timeout_s": self.timeout_s,
            "max_retries": self.max_retries,
            "retry_backoff_s": self.retry_backoff_s,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "input_usd_per_1m": self.input_usd_per_1m,
            "output_usd_per_1m": self.output_usd_per_1m,
            "json_mode": self.json_mode,
            "auth_header": self.auth_header,
        }

    @classmethod
    def from_env(cls) -> "ProviderConfig":
        provider = _first_env("LLM_PROVIDER", default="offline").lower()
        style = _first_env("LLM_API_STYLE", default="")
        if not style:
            style = "anthropic" if provider.startswith("anthropic") else ("offline" if provider == "offline" else "openai")
        base_url = _first_env("LLM_BASE_URL", "ANTHROPIC_BASE_URL" if style == "anthropic" else "OPENAI_BASE_URL")
        model = _first_env(
            "LLM_MODEL",
            "ANTHROPIC_MODEL" if style == "anthropic" else "OPENAI_MODEL",
            "ANTHROPIC_DEFAULT_SONNET_MODEL" if style == "anthropic" else "",
            default="fixture" if provider == "offline" else "",
        )
        api_key = _first_env(
            "LLM_API_KEY",
            "ANTHROPIC_AUTH_TOKEN" if style == "anthropic" else "OPENAI_API_KEY",
        )
        if provider != "offline" and (not base_url or not model):
            raise ProviderError("configured remote provider requires LLM_BASE_URL and LLM_MODEL")
        return cls(
            provider=provider,
            api_style=style,
            base_url=base_url,
            model=model,
            api_key=api_key,
            timeout_s=float(_first_env("LLM_TIMEOUT_S", default="60")),
            max_retries=int(_first_env("LLM_MAX_RETRIES", default="2")),
            retry_backoff_s=float(_first_env("LLM_RETRY_BACKOFF_S", default="0.25")),
            max_tokens=int(_first_env("LLM_MAX_TOKENS", default="2048")),
            temperature=float(_first_env("LLM_TEMPERATURE", default="0")),
            input_usd_per_1m=_optional_float("LLM_INPUT_USD_PER_1M"),
            output_usd_per_1m=_optional_float("LLM_OUTPUT_USD_PER_1M"),
            json_mode=_first_env("LLM_JSON_MODE", default="1").lower() not in {"0", "false", "no"},
            auth_header=_first_env("LLM_AUTH_HEADER", default="x-api-key" if style == "anthropic" else "authorization"),
        )
