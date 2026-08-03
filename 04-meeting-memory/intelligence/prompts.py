"""单会议结构化抽取 Prompt 和 JSON schema。"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from llm_providers.contracts import ProviderRequest

try:
    from .schema import SCHEMA_VERSION
except ImportError:  # unittest discover -s intelligence imports this module top-level
    from schema import SCHEMA_VERSION  # type: ignore


MEETING_ARTIFACT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["schema_version", "meeting_id", "tenant_id", "summary", "topics", "chapters", "facts", "decisions", "action_items", "risks", "open_questions", "keywords", "claims", "evidence"],
    "properties": {
        "schema_version": {"type": "string", "const": SCHEMA_VERSION},
        "meeting_id": {"type": "string"},
        "tenant_id": {"type": "string"},
        "summary": {"type": "string"},
        "topics": {"type": "array"},
        "chapters": {"type": "array"},
        "facts": {"type": "array"},
        "decisions": {"type": "array"},
        "action_items": {"type": "array"},
        "risks": {"type": "array"},
        "open_questions": {"type": "array"},
        "keywords": {"type": "array"},
        "claims": {"type": "array"},
        "evidence": {"type": "array"},
    },
}


SYSTEM_PROMPT = (
    "你是严谨的会议理解抽取器。只根据输入的 TranscriptBundle 输出结构化 JSON；"
    "不编造事实、Speaker、时间、负责人或截止日期。每个章节、事实、决策、行动项、风险、"
    "开放问题和 Claim 必须带 evidence_segment_ids，且只能使用输入里的 segment_id。"
    "没有证据就返回空数组或进入候选，不得把推测写成事实。summary/topics/keywords 也只能"
    "概括输入内容。只返回 JSON，不要 Markdown、解释或额外字段。"
)


def build_meeting_artifact_request(
    meeting: Mapping[str, Any],
    segments: Sequence[Mapping[str, Any]],
    *,
    prompt_version: str = "meeting-artifact-v1",
) -> ProviderRequest:
    return ProviderRequest(
        operation="meeting.extract",
        system_prompt=SYSTEM_PROMPT,
        user_payload={
            "meeting": dict(meeting),
            "segments": [dict(segment) for segment in segments],
            "output_contract": SCHEMA_VERSION,
        },
        prompt_version=prompt_version,
        response_schema=MEETING_ARTIFACT_SCHEMA,
        metadata={"tenant_id": meeting.get("tenant_id"), "meeting_id": meeting.get("meeting_id")},
    )
