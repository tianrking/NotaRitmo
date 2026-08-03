"""可插拔的单会议结构化抽取器。

抽取器负责 Prompt、Provider 调用、重试和硬校验；它不写 PostgreSQL、不改变
Claim 状态，也不负责回答用户问题。失败结果必须进入人工审核或重试队列，不能
静默当作有效 Artifact。
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence

from llm_providers.contracts import JsonProvider, ProviderResponse

try:
    from .prompts import build_meeting_artifact_request
    from .schema import ArtifactValidationError, require_valid_artifact
except ImportError:  # unittest discover -s intelligence imports this module top-level
    from prompts import build_meeting_artifact_request  # type: ignore
    from schema import ArtifactValidationError, require_valid_artifact  # type: ignore


class ExtractionStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    NEEDS_REVIEW = "needs_review"


class ExtractionFailed(RuntimeError):
    """调用兼容 ``baseline.ports.Extractor`` 时的最终失败。"""


@dataclass(frozen=True)
class Attempt:
    number: int
    status: str
    error: str | None = None
    provider: str | None = None
    model: str | None = None
    latency_ms: float | None = None


@dataclass
class ExtractionOutcome:
    status: ExtractionStatus
    meeting_id: str
    tenant_id: str
    artifact: dict[str, Any] | None = None
    attempts: list[Attempt] = field(default_factory=list)
    provider: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    retryable: bool = False
    review_reasons: list[str] = field(default_factory=list)

    @property
    def succeeded(self) -> bool:
        return self.status is ExtractionStatus.SUCCEEDED and self.artifact is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "meeting_id": self.meeting_id,
            "tenant_id": self.tenant_id,
            "artifact": self.artifact,
            "attempts": [asdict(attempt) for attempt in self.attempts],
            "provider": dict(self.provider),
            "error": self.error,
            "retryable": self.retryable,
            "review_reasons": list(self.review_reasons),
        }


class MeetingArtifactExtractor:
    """使用任意 ``JsonProvider`` 的单会议 Artifact 抽取器。"""

    def __init__(
        self,
        provider: JsonProvider,
        *,
        prompt_version: str = "meeting-artifact-v1",
        max_attempts: int = 2,
        retry_delay_s: float = 0.0,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        self.provider = provider
        self.prompt_version = prompt_version
        self.max_attempts = int(max_attempts)
        self.retry_delay_s = max(0.0, float(retry_delay_s))

    def extract_result(
        self,
        meeting: Mapping[str, Any],
        segments: Sequence[Mapping[str, Any]],
    ) -> ExtractionOutcome:
        meeting_id = str(meeting.get("meeting_id", ""))
        tenant_id = str(meeting.get("tenant_id", ""))
        request = build_meeting_artifact_request(meeting, segments, prompt_version=self.prompt_version)
        attempts: list[Attempt] = []
        last_error: str | None = None
        last_validation: list[str] = []
        provider_meta: dict[str, Any] = {
            "name": getattr(self.provider, "name", self.provider.__class__.__name__),
            "prompt_version": self.prompt_version,
            "input_hash": request.input_hash,
        }
        for number in range(1, self.max_attempts + 1):
            if number > 1 and self.retry_delay_s:
                time.sleep(self.retry_delay_s)
            try:
                response = self.provider.complete_json(request)
                provider_meta.update(
                    {
                        "provider": response.provider,
                        "model": response.model,
                        "input_hash": response.input_hash,
                        "usage": asdict(response.usage),
                        "cost_usd": response.cost_usd,
                        "latency_ms": response.latency_ms,
                        "cached": response.cached,
                        "raw_metadata": dict(response.raw_metadata),
                    }
                )
            except Exception as exc:
                last_error = str(exc)
                attempts.append(Attempt(number, "provider_error", error=last_error))
                continue

            if not isinstance(response.data, Mapping):
                last_error = "provider data must be a JSON object"
                attempts.append(
                    Attempt(number, "validation_error", error=last_error, provider=response.provider, model=response.model, latency_ms=response.latency_ms)
                )
                continue
            try:
                artifact = require_valid_artifact(response.data, meeting=meeting, segments=segments)
            except ArtifactValidationError as exc:
                last_error = str(exc)
                last_validation = list(exc.issues)
                attempts.append(
                    Attempt(number, "validation_error", error=last_error, provider=response.provider, model=response.model, latency_ms=response.latency_ms)
                )
                continue
            attempts.append(
                Attempt(number, "succeeded", provider=response.provider, model=response.model, latency_ms=response.latency_ms)
            )
            return ExtractionOutcome(
                status=ExtractionStatus.SUCCEEDED,
                meeting_id=meeting_id,
                tenant_id=tenant_id,
                artifact=artifact,
                attempts=attempts,
                provider=provider_meta,
            )

        validation_failure = bool(last_validation)
        return ExtractionOutcome(
            status=ExtractionStatus.NEEDS_REVIEW if validation_failure else ExtractionStatus.FAILED,
            meeting_id=meeting_id,
            tenant_id=tenant_id,
            attempts=attempts,
            provider=provider_meta,
            error=last_error,
            retryable=not validation_failure,
            review_reasons=last_validation if validation_failure else [],
        )

    def extract(
        self,
        meeting: Mapping[str, Any],
        segments: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        """适配现有 Extractor 协议；失败时不返回不可信部分结果。"""

        outcome = self.extract_result(meeting, segments)
        if not outcome.succeeded:
            raise ExtractionFailed(outcome.error or f"meeting extraction {outcome.status.value}")
        assert outcome.artifact is not None
        return outcome.artifact
