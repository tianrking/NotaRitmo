from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import ExtractionCache, ExtractionRun, Meeting
from app.services.intelligence import COMPONENT_KINDS, build_intelligence
from app.services.llm import LLMClient

SYSTEM_PROMPT = """你是 NotaRitmo 的会议语义提取器。输入是一份紧凑的规范化逐句转写，
每句格式为 [ordinal,start_ms,end_ms,speaker_id,text]。仅依据输入原文，一次性输出严格 JSON：
{
  "summary":{"text":"...","evidence_ordinals":[0]},
  "facts":[{"text":"...","status":"observed","confidence":0.0,"evidence_ordinals":[0]}],
  "decisions":[{"text":"...","status":"confirmed|candidate","confidence":0.0,"evidence_ordinals":[0]}],
  "action_items":[{"task":"...","owner":null,"due_date":null,"status":"open","confidence":0.0,"evidence_ordinals":[0]}],
  "risks":[{"text":"...","status":"open","confidence":0.0,"evidence_ordinals":[0]}],
  "open_questions":[{"text":"...","status":"open","confidence":0.0,"evidence_ordinals":[0]}],
  "topics":[{"text":"...","count":1,"weight":1.0,"evidence_ordinals":[0]}]
}
必须同时返回上述七个键。每条内容必须绑定真实 ordinal；没有证据就不要输出。
不得补造负责人、日期、决定或风险。摘要也必须提供覆盖其内容的证据 ordinal。"""


def canonical_input_hash(canonical: dict[str, Any]) -> str:
    stable = {
        "duration_ms": canonical.get("duration_ms"),
        "segments": [
            [
                item["ordinal"],
                item["start_ms"],
                item["end_ms"],
                item["provider_speaker_id"],
                item["text"],
            ]
            for item in canonical["segments"]
        ],
    }
    encoded = json.dumps(
        stable, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _prompt_hash() -> str:
    return hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest()


def _identity() -> dict[str, str]:
    enabled = bool(settings.llm_enabled and settings.llm_model)
    return {
        "provider": settings.llm_provider if enabled else "local-rules",
        "model": settings.llm_model if enabled else "rules-v3",
        "prompt_version": settings.llm_prompt_version if enabled else "rules-v3",
        "schema_version": settings.llm_schema_version,
        "prompt_hash": _prompt_hash() if enabled else hashlib.sha256(b"rules-v3").hexdigest(),
    }


def _cache_key(input_hash: str, identity: dict[str, str]) -> str:
    raw = "|".join(
        [
            input_hash,
            identity["provider"],
            identity["model"],
            identity["prompt_version"],
            identity["schema_version"],
            identity["prompt_hash"],
        ]
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def _compact_transcript(canonical: dict[str, Any]) -> str:
    compact = [
        [
            item["ordinal"],
            item["start_ms"],
            item["end_ms"],
            item["provider_speaker_id"],
            item["text"],
        ]
        for item in canonical["segments"]
    ]
    serialized = json.dumps(compact, ensure_ascii=False, separators=(",", ":"))
    if len(serialized) > settings.llm_max_transcript_characters:
        raise ValueError(
            "canonical transcript exceeds LLM_MAX_TRANSCRIPT_CHARACTERS; "
            "configure a long-context model or split the source before extraction"
        )
    return serialized


def _ordinals(value: Any, valid: set[int]) -> list[int]:
    if not isinstance(value, list):
        return []
    result = []
    for item in value:
        try:
            ordinal = int(item)
        except (TypeError, ValueError):
            continue
        if ordinal in valid and ordinal not in result:
            result.append(ordinal)
    return result


def _validate_components(
    raw: dict[str, Any], canonical: dict[str, Any]
) -> dict[str, Any]:
    valid = {item["ordinal"] for item in canonical["segments"]}
    output: dict[str, Any] = {}
    summary = raw.get("summary")
    if isinstance(summary, str):
        summary = {"text": summary, "evidence_ordinals": []}
    summary = summary if isinstance(summary, dict) else {}
    summary_evidence = _ordinals(summary.get("evidence_ordinals"), valid)
    output["summary"] = {
        "text": str(summary.get("text") or "暂无可用摘要。").strip(),
        "evidence_ordinals": summary_evidence,
    }
    field_by_kind = {
        "facts": "text",
        "decisions": "text",
        "action_items": "task",
        "risks": "text",
        "open_questions": "text",
        "topics": "text",
    }
    for kind, field in field_by_kind.items():
        items = raw.get(kind)
        output[kind] = []
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict) or not str(item.get(field) or "").strip():
                continue
            evidence = _ordinals(item.get("evidence_ordinals"), valid)
            if not evidence:
                continue
            normalized = dict(item)
            normalized[field] = str(item[field]).strip()
            normalized["evidence_ordinals"] = evidence
            try:
                normalized["confidence"] = min(
                    max(float(item.get("confidence", 0.5)), 0.0), 1.0
                )
            except (TypeError, ValueError):
                normalized["confidence"] = 0.5
            output[kind].append(normalized)
    if not output["summary"]["evidence_ordinals"] and valid:
        output["summary"]["evidence_ordinals"] = sorted(valid)[:8]
    if set(output) != set(COMPONENT_KINDS):
        raise ValueError("unified extraction did not produce all seven components")
    return output


def _cost(usage: dict[str, int]) -> Decimal:
    value = (
        Decimal(usage["input_tokens"])
        * Decimal(str(settings.llm_input_cost_per_million))
        + Decimal(usage["output_tokens"])
        * Decimal(str(settings.llm_output_cost_per_million))
    ) / Decimal(1_000_000)
    return value.quantize(Decimal("0.00000001"))


async def extract_with_cache(
    db: Session,
    meeting: Meeting,
    canonical: dict[str, Any],
) -> dict[str, Any]:
    input_hash = canonical_input_hash(canonical)
    identity = _identity()
    cache_key = _cache_key(input_hash, identity)
    request_metadata = {
        "segment_count": len(canonical["segments"]),
        "character_count": sum(len(item["text"]) for item in canonical["segments"]),
        "component_kinds": list(COMPONENT_KINDS),
        "single_pass": True,
    }
    run = ExtractionRun(
        tenant_id=meeting.tenant_id,
        meeting_id=meeting.id,
        cache_key=cache_key,
        input_hash=input_hash,
        status="RUNNING",
        cache_hit=False,
        request_metadata=request_metadata,
        **identity,
    )
    db.add(run)
    meeting.canonical_hash = input_hash
    db.commit()
    db.refresh(run)

    try:
        cached = db.scalar(
            select(ExtractionCache).where(
                ExtractionCache.tenant_id == meeting.tenant_id,
                ExtractionCache.cache_key == cache_key,
            )
        )
        if cached:
            cached.last_used_at = func.now()
            run.status = "COMPLETED"
            run.cache_hit = True
            run.input_tokens = 0
            run.output_tokens = 0
            run.total_tokens = 0
            run.estimated_cost = Decimal("0")
            run.completed_at = datetime.now(UTC)
            db.commit()
            return build_intelligence(
                canonical,
                components=cached.result,
                source=f"{cached.provider}:{cached.model}",
                extractor={
                    "name": cached.provider,
                    "model": cached.model,
                    "prompt_version": cached.prompt_version,
                    "schema_version": cached.schema_version,
                    "input_hash": input_hash,
                    "cache_hit": True,
                    "extraction_run_id": str(run.id),
                },
            )

        llm = LLMClient()
        if llm.enabled:
            raw, usage = await llm.complete_json(
                system=SYSTEM_PROMPT,
                user="规范化会议逐句转写：\n" + _compact_transcript(canonical),
            )
            components = _validate_components(raw, canonical)
        else:
            deterministic = build_intelligence(canonical)
            components = deterministic["components"]
            usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        estimated_cost = _cost(usage)
        cached = ExtractionCache(
            tenant_id=meeting.tenant_id,
            cache_key=cache_key,
            input_hash=input_hash,
            result=components,
            input_tokens=usage["input_tokens"],
            output_tokens=usage["output_tokens"],
            total_tokens=usage["total_tokens"],
            estimated_cost=estimated_cost,
            **identity,
        )
        db.add(cached)
        run.status = "COMPLETED"
        run.input_tokens = usage["input_tokens"]
        run.output_tokens = usage["output_tokens"]
        run.total_tokens = usage["total_tokens"]
        run.estimated_cost = estimated_cost
        run.completed_at = datetime.now(UTC)
        db.commit()
        return build_intelligence(
            canonical,
            components=components,
            source=f"{identity['provider']}:{identity['model']}",
            extractor={
                "name": identity["provider"],
                "model": identity["model"],
                "prompt_version": identity["prompt_version"],
                "schema_version": identity["schema_version"],
                "input_hash": input_hash,
                "cache_hit": False,
                "extraction_run_id": str(run.id),
            },
        )
    except Exception as exc:
        run.status = "FAILED"
        run.error = {"type": type(exc).__name__, "message": str(exc)[:2000]}
        run.completed_at = datetime.now(UTC)
        db.commit()
        raise


def extraction_stats(db: Session, meeting_id: Any | None = None) -> dict[str, Any]:
    statement = select(ExtractionRun)
    if meeting_id:
        statement = statement.where(ExtractionRun.meeting_id == meeting_id)
    rows = list(db.scalars(statement.order_by(ExtractionRun.started_at.desc())).all())
    return {
        "run_count": len(rows),
        "cache_hits": sum(1 for row in rows if row.cache_hit),
        "input_tokens": sum(row.input_tokens for row in rows),
        "output_tokens": sum(row.output_tokens for row in rows),
        "total_tokens": sum(row.total_tokens for row in rows),
        "estimated_cost": str(sum((row.estimated_cost for row in rows), Decimal("0"))),
        "runs": [
            {
                "id": str(row.id),
                "meeting_id": str(row.meeting_id),
                "status": row.status,
                "cache_hit": row.cache_hit,
                "provider": row.provider,
                "model": row.model,
                "prompt_version": row.prompt_version,
                "schema_version": row.schema_version,
                "input_hash": row.input_hash,
                "input_tokens": row.input_tokens,
                "output_tokens": row.output_tokens,
                "total_tokens": row.total_tokens,
                "estimated_cost": str(row.estimated_cost),
                "started_at": row.started_at.isoformat(),
                "completed_at": (
                    row.completed_at.isoformat() if row.completed_at else None
                ),
                "error": row.error,
            }
            for row in rows
        ],
    }
