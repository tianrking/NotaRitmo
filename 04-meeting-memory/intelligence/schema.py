"""单会议理解 Artifact 的固定结构和证据校验。

LLM 输出只是候选；只有通过这里的结构、租户、会议和 segment_id 校验后，才
能交给下游 Claim/Memory。校验器不比较自然语言是否“像正确答案”，只负责
硬约束和证据完整性。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping


SCHEMA_VERSION = "meeting-artifact-v1"
ITEM_FIELDS = (
    "chapters",
    "facts",
    "decisions",
    "action_items",
    "risks",
    "open_questions",
)
ARRAY_FIELDS = ITEM_FIELDS + ("topics", "keywords", "claims", "evidence")


class ArtifactValidationError(ValueError):
    """模型输出不满足固定 schema 或引用了不存在证据。"""

    def __init__(self, issues: Iterable[str]) -> None:
        self.issues = tuple(str(issue) for issue in issues)
        super().__init__("; ".join(self.issues) or "invalid meeting artifact")


@dataclass(frozen=True)
class ValidationReport:
    valid: bool
    issues: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {"valid": self.valid, "issues": list(self.issues)}


def normalize_artifact(value: Mapping[str, Any]) -> dict[str, Any]:
    """填充兼容性默认值，不替模型编造内容。"""

    result = dict(value)
    result.setdefault("schema_version", SCHEMA_VERSION)
    for field_name in ARRAY_FIELDS:
        if field_name not in result or result[field_name] is None:
            result[field_name] = []
    result.setdefault("summary", "")
    result.setdefault("topics", [])
    return result


def _evidence_ids(item: Mapping[str, Any]) -> list[str]:
    # Accept the compact single-reference shape emitted by some structured
    # providers in addition to the canonical array form.
    values = item.get("evidence_segment_ids", item.get("evidence_ids", item.get("segment_id", [])))
    if isinstance(values, str):
        return [values]
    if not isinstance(values, (list, tuple)):
        return []
    return [str(value) for value in values if value not in (None, "")]


def validate_artifact(
    artifact: Mapping[str, Any],
    *,
    meeting: Mapping[str, Any] | None = None,
    segments: Iterable[Mapping[str, Any]] = (),
) -> ValidationReport:
    """校验 Artifact；返回报告而不是隐式修复错误。

    ``decisions/action_items/risks/facts/chapters/open_questions/claims`` 中的
    每个非空对象必须有证据。摘要和 topic 可以是会议级派生文本，但不能绕过
    Claim 的证据门禁。
    """

    issues: list[str] = []
    if not isinstance(artifact, Mapping):
        return ValidationReport(False, ("artifact must be an object",))
    meeting_id = str(artifact.get("meeting_id", ""))
    tenant_id = str(artifact.get("tenant_id", ""))
    if not meeting_id:
        issues.append("meeting_id is required")
    if not tenant_id:
        issues.append("tenant_id is required")
    if meeting is not None:
        if str(meeting.get("meeting_id", "")) != meeting_id:
            issues.append("meeting_id does not match input meeting")
        if str(meeting.get("tenant_id", "")) != tenant_id:
            issues.append("tenant_id does not match input meeting")
    if artifact.get("schema_version") not in (None, SCHEMA_VERSION):
        issues.append("unsupported schema_version")
    if not isinstance(artifact.get("summary", ""), str):
        issues.append("summary must be a string")
    segment_ids = {str(segment.get("segment_id", "")) for segment in segments if isinstance(segment, Mapping)}
    if not segment_ids:
        issues.append("input must contain at least one segment")
    for field_name in ARRAY_FIELDS:
        value = artifact.get(field_name, [])
        if not isinstance(value, list):
            issues.append(f"{field_name} must be an array")
            continue
        if field_name in ("topics", "keywords"):
            for index, item in enumerate(value):
                if not isinstance(item, (str, Mapping)):
                    issues.append(f"{field_name}[{index}] must be string or object")
            continue
        for index, item in enumerate(value):
            if not isinstance(item, Mapping):
                issues.append(f"{field_name}[{index}] must be an object")
                continue
            if field_name == "evidence":
                segment_id = str(item.get("segment_id", ""))
                if not segment_id:
                    issues.append(f"evidence[{index}] requires segment_id")
                elif segment_id not in segment_ids:
                    issues.append(f"evidence[{index}] references unknown segment_id {segment_id}")
                continue
            evidence = _evidence_ids(item)
            if not evidence:
                issues.append(f"{field_name}[{index}] requires evidence_segment_ids")
            for evidence_id in evidence:
                if evidence_id not in segment_ids:
                    issues.append(f"{field_name}[{index}] references unknown segment_id {evidence_id}")
            # Claims have a stable subject/predicate/object shape. Other items need
            # content/title/task/text, but accepting aliases keeps SaaS adapters loose.
            if field_name == "claims":
                for required in ("subject", "predicate", "object"):
                    if item.get(required) in (None, ""):
                        issues.append(f"claims[{index}] requires {required}")
            elif field_name == "chapters":
                if not any(item.get(key) not in (None, "") for key in ("title", "content", "text")):
                    issues.append(f"chapters[{index}] requires title or content")
            elif field_name == "action_items":
                if not any(item.get(key) not in (None, "") for key in ("task", "content", "text")):
                    issues.append(f"action_items[{index}] requires task or content")
            elif field_name in ("facts", "decisions", "risks", "open_questions"):
                if not any(item.get(key) not in (None, "") for key in ("content", "text", "question")):
                    issues.append(f"{field_name}[{index}] requires content/text")
    return ValidationReport(not issues, tuple(issues))


def require_valid_artifact(
    artifact: Mapping[str, Any],
    *,
    meeting: Mapping[str, Any] | None = None,
    segments: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    normalized = normalize_artifact(artifact)
    report = validate_artifact(normalized, meeting=meeting, segments=segments)
    if not report.valid:
        raise ArtifactValidationError(report.issues)
    return normalized
