from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
from aliyunsdkcore.auth.credentials import AccessKeyCredential
from aliyunsdkcore.client import AcsClient
from aliyunsdkcore.request import CommonRequest

from app.config import settings


class TingwuError(RuntimeError):
    pass


class TingwuClient:
    def __init__(self) -> None:
        if not settings.tingwu_enabled:
            raise TingwuError("TINGWU_ENABLED=false；请配置凭证或使用样本导入接口。")
        if not (
            settings.tingwu_app_key
            and settings.alibaba_cloud_access_key_id
            and settings.alibaba_cloud_access_key_secret
        ):
            raise TingwuError("缺少 TINGWU_APP_KEY 或阿里云 AccessKey。")
        credentials = AccessKeyCredential(
            settings.alibaba_cloud_access_key_id,
            settings.alibaba_cloud_access_key_secret,
        )
        self.client = AcsClient(region_id=settings.tingwu_region, credential=credentials)

    def _request(self, method: str, uri: str, body: dict | None = None) -> dict[str, Any]:
        request = CommonRequest()
        request.set_accept_format("json")
        request.set_domain(settings.tingwu_domain)
        request.set_version("2023-09-30")
        request.set_protocol_type("https")
        request.set_method(method)
        request.set_uri_pattern(uri)
        request.add_header("Content-Type", "application/json")
        if body is not None:
            request.set_content(json.dumps(body, ensure_ascii=False).encode())
        response = self.client.do_action_with_exception(request)
        payload = json.loads(response)
        if str(payload.get("Code", "0")) != "0":
            raise TingwuError(f"听悟请求失败：{payload}")
        return payload

    def create_offline_task(
        self,
        *,
        audio_url: str,
        task_key: str,
        source_language: str,
    ) -> str:
        body = {
            "AppKey": settings.tingwu_app_key,
            "Input": {
                "FileUrl": audio_url,
                "SourceLanguage": source_language,
                "TaskKey": task_key,
            },
            "Parameters": {
                "Transcription": {
                    "DiarizationEnabled": True,
                    "Diarization": {"SpeakerCount": 0},
                },
                "AutoChaptersEnabled": True,
                "MeetingAssistanceEnabled": True,
                "MeetingAssistance": {"Types": ["Actions", "KeyInformation"]},
                "SummarizationEnabled": True,
                "Summarization": {
                    "Types": [
                        "Paragraph",
                        "Conversational",
                        "QuestionsAnswering",
                        "MindMap",
                    ]
                },
                "TextPolishEnabled": True,
                "Model": settings.tingwu_llm_model,
            },
        }
        request = CommonRequest()
        request.set_accept_format("json")
        request.set_domain(settings.tingwu_domain)
        request.set_version("2023-09-30")
        request.set_protocol_type("https")
        request.set_method("PUT")
        request.set_uri_pattern("/openapi/tingwu/v2/tasks")
        request.add_query_param("type", "offline")
        request.add_header("Content-Type", "application/json")
        request.set_content(json.dumps(body, ensure_ascii=False).encode())
        payload = json.loads(self.client.do_action_with_exception(request))
        if str(payload.get("Code", "0")) != "0":
            raise TingwuError(f"创建听悟任务失败：{payload}")
        task_id = (payload.get("Data") or {}).get("TaskId")
        if not task_id:
            raise TingwuError(f"听悟未返回 TaskId：{payload}")
        return task_id

    def get_task(self, task_id: str) -> dict[str, Any]:
        return self._request("GET", f"/openapi/tingwu/v2/tasks/{task_id}")

    async def download_results(self, result_urls: dict[str, str]) -> dict[str, Any]:
        bundle: dict[str, Any] = {}
        async with httpx.AsyncClient(timeout=180, follow_redirects=True) as client:
            for name, url in result_urls.items():
                response = await client.get(url)
                response.raise_for_status()
                bundle[name] = response.json()
        return bundle

    async def wait_and_download(self, task_id: str) -> dict[str, Any]:
        while True:
            response = await asyncio.to_thread(self.get_task, task_id)
            data = response.get("Data") or {}
            status = data.get("TaskStatus")
            if status == "COMPLETED":
                bundle = await self.download_results(data.get("Result") or {})
                bundle["_TaskInfo"] = response
                return bundle
            if status in {"FAILED", "INVALID"}:
                raise TingwuError(f"听悟任务失败：{data}")
            await asyncio.sleep(settings.tingwu_poll_seconds)

