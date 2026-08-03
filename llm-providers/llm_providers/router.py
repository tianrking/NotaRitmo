"""Provider factory, routing and opt-in in-process response cache."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping, Optional

from .config import ProviderConfig
from .contracts import LLMProvider, LLMRequest, LLMResponse, ProviderError
from .providers import AnthropicCompatibleProvider, OfflineFixtureProvider, OpenAICompatibleProvider


class InMemoryResponseCache:
    """Small deterministic cache for tests and a single worker.

    Production deployments should put the same key/value contract behind a
    shared cache owned by the Go control plane; this class is not a distributed
    cache and has no eviction policy.
    """

    def __init__(self) -> None:
        self._values: dict[str, LLMResponse] = {}

    def get(self, key: str) -> Optional[LLMResponse]:
        value = self._values.get(key)
        return None if value is None else replace(value, cached=True)

    def put(self, key: str, value: LLMResponse) -> None:
        self._values[key] = value

    def clear(self) -> None:
        self._values.clear()


class CachedProvider(LLMProvider):
    """Wrap any provider without changing its request/response contract."""

    def __init__(self, provider: LLMProvider, cache: InMemoryResponseCache):
        self.provider = provider
        self.cache = cache
        self.name = getattr(provider, "name", provider.__class__.__name__)

    def complete_json(self, request: LLMRequest) -> LLMResponse:
        key = request.input_hash
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        response = self.provider.complete_json(request)
        self.cache.put(key, response)
        return response


class ProviderRouter:
    """Explicit registry; no provider is contacted unless selected."""

    def __init__(self, providers: Mapping[str, LLMProvider], default: str, *, cache: Optional[InMemoryResponseCache] = None):
        self.providers = dict(providers)
        self.default = default
        self.cache = cache

    @classmethod
    def from_env(cls, config: Optional[ProviderConfig] = None, *, cache: Optional[InMemoryResponseCache] = None) -> "ProviderRouter":
        cfg = config or ProviderConfig.from_env()
        provider_name = cfg.provider
        if provider_name in {"offline", "fixture", "offline-fixture"}:
            provider: LLMProvider = OfflineFixtureProvider(model=cfg.model)
            key = "offline"
        elif provider_name in {"openai", "openai-compatible"} or cfg.api_style == "openai":
            provider = OpenAICompatibleProvider(cfg)
            key = "openai-compatible"
        elif provider_name in {"anthropic", "anthropic-compatible", "bigmodel-anthropic"} or cfg.api_style == "anthropic":
            provider = AnthropicCompatibleProvider(cfg)
            key = "anthropic-compatible"
        else:
            raise ProviderError("unsupported LLM_PROVIDER: " + provider_name)
        return cls({key: provider}, key, cache=cache)

    def register(self, name: str, provider: LLMProvider) -> None:
        self.providers[name] = provider

    def complete_json(self, request: LLMRequest, *, provider: Optional[str] = None) -> LLMResponse:
        name = provider or self.default
        selected = self.providers.get(name)
        if selected is None:
            raise ProviderError("LLM provider is not registered: " + name)
        if self.cache is None:
            return selected.complete_json(request)
        return CachedProvider(selected, self.cache).complete_json(request)
