from __future__ import annotations

from app.services.asr.base import ASRProvider
from app.services.asr.tingwu import TingwuASRProvider


class ASRProviderRegistry:
    def __init__(self) -> None:
        # Multi-ASR routing is intentionally not implemented yet. The registry and
        # protocol make the Tingwu dependency replaceable without leaking it upward.
        self._providers: dict[str, ASRProvider] = {"tingwu": TingwuASRProvider()}

    def get(self, name: str) -> ASRProvider:
        try:
            return self._providers[name]
        except KeyError as exc:
            raise ValueError(
                f"ASR provider {name!r} is not registered; available={self.names()}"
            ) from exc

    def names(self) -> list[str]:
        return sorted(self._providers)


asr_registry = ASRProviderRegistry()
