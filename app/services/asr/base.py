from __future__ import annotations

from typing import Any, Protocol


class ASRProvider(Protocol):
    """Provider boundary for transcription-only engines."""

    name: str

    async def submit(
        self,
        *,
        audio_url: str,
        task_key: str,
        source_language: str,
    ) -> str: ...

    async def wait(self, task_id: str) -> dict[str, Any]: ...

    def normalize(self, raw_result: dict[str, Any]) -> dict[str, Any]: ...
