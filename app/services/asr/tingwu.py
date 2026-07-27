from __future__ import annotations

import asyncio
from typing import Any

from app.services.normalizer import normalize_tingwu
from app.services.tingwu import TingwuClient


class TingwuASRProvider:
    name = "tingwu"

    async def submit(
        self,
        *,
        audio_url: str,
        task_key: str,
        source_language: str,
    ) -> str:
        client = TingwuClient()
        return await asyncio.to_thread(
            client.create_offline_task,
            audio_url=audio_url,
            task_key=task_key,
            source_language=source_language,
        )

    async def wait(self, task_id: str) -> dict[str, Any]:
        return await TingwuClient().wait_and_download(task_id)

    def normalize(self, raw_result: dict[str, Any]) -> dict[str, Any]:
        return normalize_tingwu(raw_result)
