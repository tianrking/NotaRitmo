from __future__ import annotations

import uuid
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from app.auth import current_tenant_id, current_user_id
from app.config import settings
from app.models import (
    Artifact,
    Conversation,
    ConversationMessage,
    Meeting,
    MeetingAccess,
    MemoryLink,
    MemoryRecord,
    PipelineRun,
    PipelineStage,
    QueryAudit,
    Segment,
    Speaker,
    UploadSession,
    Word,
)
from app.services.normalizer import tokenize


def create_meeting(
    db: Session,
    *,
    title: str,
    audio_uri: str | None,
    project_id: str | None,
    source_language: str,
    raw_result: dict | None = None,
    tenant_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    denoise_enabled: bool | None = None,
) -> Meeting:
    tenant_id = tenant_id or current_tenant_id()
    user_id = user_id or current_user_id()
    meeting = Meeting(
        tenant_id=tenant_id,
        created_by=user_id,
        title=title,
        project_id=project_id,
        source_language=source_language,
        audio_uri=audio_uri,
        raw_result=raw_result,
        status="IMPORTED" if raw_result else "CREATED",
        denoise_enabled=(
            settings.audio_denoise_default
            if denoise_enabled is None
            else denoise_enabled
        ),
    )
    db.add(meeting)
    db.flush()
    db.add(
        MeetingAccess(
            meeting_id=meeting.id,
            user_id=user_id,
            role="owner",
        )
    )
    db.commit()
    db.refresh(meeting)
    return meeting


def create_upload_session(
    db: Session,
    *,
    filename: str,
    content_type: str,
    expected_size: int,
    expected_sha256: str | None,
    title: str,
    project_id: str | None,
    source_language: str,
    denoise_enabled: bool,
    tenant_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
) -> UploadSession:
    tenant_id = tenant_id or current_tenant_id()
    user_id = user_id or current_user_id()
    upload_id = uuid.uuid4()
    safe_name = filename.replace("/", "_").replace("\\", "_")[:500] or "audio.bin"
    value = UploadSession(
        id=upload_id,
        tenant_id=tenant_id,
        user_id=user_id,
        object_name=f"{tenant_id}/uploads/{upload_id}/{safe_name}",
        filename=safe_name,
        content_type=content_type,
        expected_size=expected_size,
        expected_sha256=expected_sha256,
        title=title,
        project_id=project_id,
        source_language=source_language,
        denoise_enabled=denoise_enabled,
        status="PENDING",
        expires_at=datetime.now(UTC)
        + timedelta(seconds=settings.upload_url_ttl_seconds),
    )
    db.add(value)
    db.commit()
    db.refresh(value)
    return value


def get_upload_session(db: Session, upload_id: uuid.UUID) -> UploadSession | None:
    return db.scalar(
        select(UploadSession).where(
            UploadSession.id == upload_id,
            UploadSession.tenant_id == current_tenant_id(),
            UploadSession.user_id == current_user_id(),
        )
    )


def get_meeting(db: Session, meeting_id: uuid.UUID) -> Meeting | None:
    return db.scalar(
        select(Meeting).where(
            Meeting.id == meeting_id,
            Meeting.tenant_id == current_tenant_id(),
        )
    )


def get_meeting_for_provider(db: Session, meeting_id: uuid.UUID) -> Meeting | None:
    """Provider-only lookup used after the per-meeting HMAC download token is verified."""

    return db.get(Meeting, meeting_id)


def get_meeting_by_task_id(db: Session, task_id: str) -> Meeting | None:
    return db.scalar(
        select(Meeting).where(
            Meeting.source_task_id == task_id,
            Meeting.tenant_id == current_tenant_id(),
        )
    )


def list_meetings(db: Session, project_id: str | None = None) -> list[Meeting]:
    statement = select(Meeting).where(Meeting.tenant_id == current_tenant_id())
    if project_id:
        statement = statement.where(Meeting.project_id == project_id)
    return list(db.scalars(statement.order_by(Meeting.created_at.desc())).all())


def meeting_pipeline_runs(db: Session, meeting_id: uuid.UUID) -> list[dict[str, Any]]:
    runs = list(
        db.scalars(
            select(PipelineRun)
            .where(
                PipelineRun.meeting_id == meeting_id,
                PipelineRun.tenant_id == current_tenant_id(),
            )
            .order_by(PipelineRun.started_at.desc())
        ).all()
    )
    stages_by_run: dict[uuid.UUID, list[PipelineStage]] = {}
    if runs:
        for stage in db.scalars(
            select(PipelineStage)
            .where(PipelineStage.pipeline_run_id.in_([run.id for run in runs]))
            .order_by(PipelineStage.started_at)
        ).all():
            stages_by_run.setdefault(stage.pipeline_run_id, []).append(stage)
    return [
        {
            "id": str(run.id),
            "workflow_id": run.workflow_id,
            "workflow_run_id": run.workflow_run_id,
            "status": run.status,
            "started_at": run.started_at.isoformat(),
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            "stages": [
                {
                    "stage": stage.stage,
                    "status": stage.status,
                    "attempt_count": stage.attempt_count,
                    "output": stage.output,
                    "error": stage.error,
                    "started_at": stage.started_at.isoformat(),
                    "completed_at": (
                        stage.completed_at.isoformat() if stage.completed_at else None
                    ),
                }
                for stage in stages_by_run.get(run.id, [])
            ],
        }
        for run in runs
    ]


def replace_canonical(db: Session, meeting: Meeting, canonical: dict[str, Any]) -> None:
    """Atomically replace ASR canonical data and invalidate all downstream products."""

    db.execute(delete(MemoryRecord).where(MemoryRecord.meeting_id == meeting.id))
    db.execute(delete(Artifact).where(Artifact.meeting_id == meeting.id))
    db.execute(delete(Segment).where(Segment.meeting_id == meeting.id))
    db.execute(delete(Speaker).where(Speaker.meeting_id == meeting.id))
    db.flush()

    speakers: dict[str, Speaker] = {}
    for item in canonical["speakers"]:
        speaker = Speaker(
            meeting_id=meeting.id,
            provider_speaker_id=item["provider_speaker_id"],
            display_name=item["display_name"],
        )
        db.add(speaker)
        db.flush()
        speakers[item["provider_speaker_id"]] = speaker

    segments: dict[int, Segment] = {}
    for item in canonical["segments"]:
        speaker = speakers.get(item["provider_speaker_id"])
        segment = Segment(
            tenant_id=meeting.tenant_id,
            meeting_id=meeting.id,
            speaker_id=speaker.id if speaker else None,
            paragraph_id=item["paragraph_id"],
            sentence_id=item["sentence_id"],
            ordinal=item["ordinal"],
            start_ms=item["start_ms"],
            end_ms=item["end_ms"],
            text=item["text"],
            confidence=item["confidence"],
            overlap=item["overlap"],
            embedding=item.get("embedding"),
        )
        db.add(segment)
        db.flush()
        segments[item["ordinal"]] = segment

    for item in canonical.get("words", []):
        segment = segments.get(item["segment_ordinal"])
        if not segment:
            continue
        speaker = speakers.get(item["provider_speaker_id"])
        db.add(
            Word(
                tenant_id=meeting.tenant_id,
                meeting_id=meeting.id,
                segment_id=segment.id,
                speaker_id=speaker.id if speaker else None,
                provider_word_id=item["provider_word_id"],
                ordinal=item["ordinal"],
                start_ms=item["start_ms"],
                end_ms=item["end_ms"],
                text=item["text"],
                confidence=item["confidence"],
            )
        )
    meeting.duration_ms = canonical.get("duration_ms")
    meeting.status = "CANONICAL_READY"
    meeting.error = None
    db.commit()


def canonical_payload(db: Session, meeting: Meeting) -> dict[str, Any]:
    speaker_rows = list(
        db.scalars(
            select(Speaker)
            .where(Speaker.meeting_id == meeting.id)
            .order_by(Speaker.provider_speaker_id)
        ).all()
    )
    speaker_by_id = {speaker.id: speaker for speaker in speaker_rows}
    segment_rows = list(
        db.scalars(
            select(Segment)
            .where(Segment.meeting_id == meeting.id)
            .order_by(Segment.ordinal)
        ).all()
    )
    segment_by_id = {segment.id: segment for segment in segment_rows}
    return {
        "duration_ms": meeting.duration_ms,
        "speakers": [
            {
                "provider_speaker_id": speaker.provider_speaker_id,
                "display_name": speaker.display_name,
            }
            for speaker in speaker_rows
        ],
        "segments": [
            {
                "provider_speaker_id": (
                    speaker_by_id[segment.speaker_id].provider_speaker_id
                    if segment.speaker_id in speaker_by_id
                    else "unknown"
                ),
                "paragraph_id": segment.paragraph_id,
                "sentence_id": segment.sentence_id,
                "ordinal": segment.ordinal,
                "start_ms": segment.start_ms,
                "end_ms": segment.end_ms,
                "text": segment.text,
                "confidence": segment.confidence,
                "overlap": segment.overlap,
                "embedding": list(segment.embedding) if segment.embedding is not None else None,
            }
            for segment in segment_rows
        ],
        "words": [
            {
                "segment_ordinal": segment_by_id[word.segment_id].ordinal,
                "provider_speaker_id": (
                    speaker_by_id[word.speaker_id].provider_speaker_id
                    if word.speaker_id in speaker_by_id
                    else "unknown"
                ),
                "provider_word_id": word.provider_word_id,
                "ordinal": word.ordinal,
                "start_ms": word.start_ms,
                "end_ms": word.end_ms,
                "text": word.text,
                "confidence": word.confidence,
            }
            for word in db.scalars(
                select(Word)
                .where(Word.meeting_id == meeting.id)
                .order_by(Word.ordinal)
            ).all()
            if word.segment_id in segment_by_id
        ],
    }


def replace_intelligence(
    db: Session, meeting: Meeting, intelligence: dict[str, Any]
) -> None:
    db.execute(delete(MemoryRecord).where(MemoryRecord.meeting_id == meeting.id))
    db.execute(delete(Artifact).where(Artifact.meeting_id == meeting.id))
    db.flush()
    segment_by_ordinal = {
        segment.ordinal: segment
        for segment in db.scalars(
            select(Segment).where(Segment.meeting_id == meeting.id)
        ).all()
    }

    def materialize(value: Any) -> Any:
        if isinstance(value, dict):
            result = {key: materialize(child) for key, child in value.items()}
            ordinals = result.pop("evidence_ordinals", None)
            if isinstance(ordinals, list):
                result["evidence"] = [
                    {
                        "segment_id": str(segment_by_ordinal[ordinal].id),
                        "ordinal": ordinal,
                        "start_ms": segment_by_ordinal[ordinal].start_ms,
                        "end_ms": segment_by_ordinal[ordinal].end_ms,
                    }
                    for ordinal in ordinals
                    if ordinal in segment_by_ordinal
                ]
            return result
        if isinstance(value, list):
            return [materialize(child) for child in value]
        return value

    for item in intelligence["artifacts"]:
        db.add(
            Artifact(
                tenant_id=meeting.tenant_id,
                meeting_id=meeting.id,
                kind=item["kind"],
                version=1,
                source=item["source"],
                data=materialize(item["data"]),
            )
        )

    inserted: list[MemoryRecord] = []
    for item in intelligence["memories"]:
        evidence_ids = [
            str(segment_by_ordinal[ordinal].id)
            for ordinal in item["evidence_ordinals"]
            if ordinal in segment_by_ordinal
        ]
        memory = MemoryRecord(
            tenant_id=meeting.tenant_id,
            meeting_id=meeting.id,
            project_id=meeting.project_id,
            kind=item["kind"],
            subject=item["subject"],
            content=item["content"],
            status=item["status"],
            evidence_segment_ids=evidence_ids,
            extractor=item["extractor"],
            embedding=item.get("embedding"),
        )
        db.add(memory)
        db.flush()
        inserted.append(memory)
    _link_cross_meeting_memories(db, meeting, inserted)
    meeting.status = "INTELLIGENCE_READY"
    meeting.error = None
    db.commit()


def replace_normalized(db: Session, meeting: Meeting, normalized: dict[str, Any]) -> None:
    db.execute(delete(MemoryRecord).where(MemoryRecord.meeting_id == meeting.id))
    db.execute(delete(Artifact).where(Artifact.meeting_id == meeting.id))
    db.execute(delete(Segment).where(Segment.meeting_id == meeting.id))
    db.execute(delete(Speaker).where(Speaker.meeting_id == meeting.id))
    db.flush()

    speakers: dict[str, Speaker] = {}
    for item in normalized["speakers"]:
        speaker = Speaker(
            meeting_id=meeting.id,
            provider_speaker_id=item["provider_speaker_id"],
            display_name=item["display_name"],
        )
        db.add(speaker)
        db.flush()
        speakers[item["provider_speaker_id"]] = speaker

    segment_by_ordinal: dict[int, Segment] = {}
    for item in normalized["segments"]:
        speaker = speakers.get(item["provider_speaker_id"])
        segment = Segment(
            tenant_id=meeting.tenant_id,
            meeting_id=meeting.id,
            speaker_id=speaker.id if speaker else None,
            paragraph_id=item["paragraph_id"],
            sentence_id=item["sentence_id"],
            ordinal=item["ordinal"],
            start_ms=item["start_ms"],
            end_ms=item["end_ms"],
            text=item["text"],
            confidence=item["confidence"],
            overlap=item["overlap"],
            embedding=item.get("embedding"),
        )
        db.add(segment)
        db.flush()
        segment_by_ordinal[item["ordinal"]] = segment

    for item in normalized.get("words", []):
        segment = segment_by_ordinal.get(item["segment_ordinal"])
        if not segment:
            continue
        speaker = speakers.get(item["provider_speaker_id"])
        db.add(
            Word(
                tenant_id=meeting.tenant_id,
                meeting_id=meeting.id,
                segment_id=segment.id,
                speaker_id=speaker.id if speaker else None,
                provider_word_id=item["provider_word_id"],
                ordinal=item["ordinal"],
                start_ms=item["start_ms"],
                end_ms=item["end_ms"],
                text=item["text"],
                confidence=item["confidence"],
            )
        )

    def materialize(value: Any) -> Any:
        if isinstance(value, dict):
            result = {key: materialize(child) for key, child in value.items()}
            ordinals = result.pop("evidence_ordinals", None)
            if isinstance(ordinals, list):
                result["evidence"] = [
                    {
                        "segment_id": str(segment_by_ordinal[ordinal].id),
                        "ordinal": ordinal,
                        "start_ms": segment_by_ordinal[ordinal].start_ms,
                        "end_ms": segment_by_ordinal[ordinal].end_ms,
                    }
                    for ordinal in ordinals
                    if ordinal in segment_by_ordinal
                ]
            return result
        if isinstance(value, list):
            return [materialize(child) for child in value]
        return value

    for item in normalized["artifacts"]:
        db.add(
            Artifact(
                tenant_id=meeting.tenant_id,
                meeting_id=meeting.id,
                kind=item["kind"],
                version=1,
                source=item["source"],
                data=materialize(item["data"]),
            )
        )

    inserted_memories: list[MemoryRecord] = []
    for item in normalized["memories"]:
        evidence_ids = [
            str(segment_by_ordinal[ordinal].id)
            for ordinal in item["evidence_ordinals"]
            if ordinal in segment_by_ordinal
        ]
        memory = MemoryRecord(
                tenant_id=meeting.tenant_id,
                meeting_id=meeting.id,
                project_id=meeting.project_id,
                kind=item["kind"],
                subject=item["subject"],
                content=item["content"],
                status=item["status"],
                evidence_segment_ids=evidence_ids,
                extractor=item["extractor"],
                embedding=item.get("embedding"),
            )
        db.add(memory)
        db.flush()
        inserted_memories.append(memory)

    _link_cross_meeting_memories(db, meeting, inserted_memories)

    meeting.duration_ms = normalized.get("duration_ms")
    meeting.status = "READY"
    meeting.error = None
    db.commit()


def _token_set(text: str) -> set[str]:
    return set(tokenize(text))


def _link_cross_meeting_memories(
    db: Session, meeting: Meeting, inserted: list[MemoryRecord]
) -> None:
    if not inserted:
        return
    previous = list(
        db.scalars(
            select(MemoryRecord)
            .join(Meeting, MemoryRecord.meeting_id == Meeting.id)
            .where(
                MemoryRecord.tenant_id == meeting.tenant_id,
                MemoryRecord.meeting_id != meeting.id,
                Meeting.status == "READY",
                MemoryRecord.project_id == meeting.project_id
                if meeting.project_id
                else MemoryRecord.project_id.is_(None),
            )
            .order_by(MemoryRecord.created_at.desc())
            .limit(1000)
        ).all()
    )
    for current in inserted:
        current_terms = _token_set(current.content)
        best: tuple[float, MemoryRecord] | None = None
        for older in previous:
            if older.kind != current.kind:
                continue
            older_terms = _token_set(older.content)
            union = current_terms | older_terms
            similarity = len(current_terms & older_terms) / len(union) if union else 0.0
            if current.subject and current.subject == older.subject:
                similarity = max(similarity, 0.65)
            if best is None or similarity > best[0]:
                best = (similarity, older)
        if not best or best[0] < 0.2:
            continue
        score, older = best
        superseding = current.kind == "decision" and any(
            marker in current.content for marker in ("改为", "调整为", "不再", "替代", "取代")
        )
        relation = (
            "supersedes"
            if superseding
            else "follows_up"
            if current.kind == "action_item"
            else "related_to"
        )
        if relation == "supersedes":
            current.supersedes_id = older.id
            older.status = "superseded"
            older.valid_to = func.now()
        db.add(
            MemoryLink(
                tenant_id=meeting.tenant_id,
                source_memory_id=current.id,
                target_memory_id=older.id,
                relation=relation,
                confidence=round(score, 4),
                rationale=f"同项目同类型记忆，词项相似度 {score:.2f}",
            )
        )


def transcript(db: Session, meeting_id: uuid.UUID) -> list[dict[str, Any]]:
    statement = (
        select(Segment, Speaker)
        .outerjoin(Speaker, Segment.speaker_id == Speaker.id)
        .where(
            Segment.tenant_id == current_tenant_id(),
            Segment.meeting_id == meeting_id,
        )
        .order_by(Segment.ordinal)
    )
    values = [
        {
            "segment_id": str(segment.id),
            "meeting_id": str(segment.meeting_id),
            "speaker_id": str(speaker.id) if speaker else None,
            "speaker_name": speaker.display_name if speaker else "Unknown",
            "start_ms": segment.start_ms,
            "end_ms": segment.end_ms,
            "text": segment.text,
            "ordinal": segment.ordinal,
            "overlap": segment.overlap,
        }
        for segment, speaker in db.execute(statement).all()
    ]
    words_by_segment: dict[str, list[dict[str, Any]]] = {}
    word_rows = db.execute(
        select(Word, Speaker)
        .outerjoin(Speaker, Word.speaker_id == Speaker.id)
        .where(
            Word.tenant_id == current_tenant_id(),
            Word.meeting_id == meeting_id,
        )
        .order_by(Word.ordinal)
    ).all()
    for word, speaker in word_rows:
        words_by_segment.setdefault(str(word.segment_id), []).append(
            {
                "word_id": str(word.id),
                "provider_word_id": word.provider_word_id,
                "speaker_name": speaker.display_name if speaker else "Unknown",
                "start_ms": word.start_ms,
                "end_ms": word.end_ms,
                "text": word.text,
                "confidence": word.confidence,
                "ordinal": word.ordinal,
            }
        )
    for item in values:
        item["words"] = words_by_segment.get(item["segment_id"], [])
    return values


def words(db: Session, meeting_id: uuid.UUID) -> list[dict[str, Any]]:
    statement = (
        select(Word, Speaker)
        .outerjoin(Speaker, Word.speaker_id == Speaker.id)
        .where(
            Word.tenant_id == current_tenant_id(),
            Word.meeting_id == meeting_id,
        )
        .order_by(Word.ordinal)
    )
    return [
        {
            "word_id": str(word.id),
            "segment_id": str(word.segment_id),
            "speaker_id": str(speaker.id) if speaker else None,
            "speaker_name": speaker.display_name if speaker else "Unknown",
            "provider_word_id": word.provider_word_id,
            "start_ms": word.start_ms,
            "end_ms": word.end_ms,
            "text": word.text,
            "confidence": word.confidence,
            "ordinal": word.ordinal,
        }
        for word, speaker in db.execute(statement).all()
    ]


def artifacts(db: Session, meeting_id: uuid.UUID) -> dict[str, Any]:
    rows = db.scalars(
        select(Artifact)
        .where(
            Artifact.tenant_id == current_tenant_id(),
            Artifact.meeting_id == meeting_id,
        )
        .order_by(Artifact.kind)
    ).all()
    return {
        row.kind: {
            "source": row.source,
            "version": row.version,
            "data": row.data,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    }


def meeting_memories(db: Session, meeting_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = db.execute(
        select(MemoryRecord, Meeting)
        .join(Meeting, MemoryRecord.meeting_id == Meeting.id)
        .where(
            MemoryRecord.tenant_id == current_tenant_id(),
            MemoryRecord.meeting_id == meeting_id,
        )
        .order_by(MemoryRecord.created_at, MemoryRecord.kind)
    ).all()
    return [_memory_dict(memory, meeting) for memory, meeting in rows]


def _memory_dict(memory: MemoryRecord, meeting: Meeting) -> dict[str, Any]:
    return {
        "memory_id": str(memory.id),
        "meeting_id": str(memory.meeting_id),
        "meeting_title": meeting.title,
        "project_id": memory.project_id,
        "kind": memory.kind,
        "subject": memory.subject,
        "content": memory.content,
        "status": memory.status,
        "valid_from": memory.valid_from.isoformat() if memory.valid_from else None,
        "valid_to": memory.valid_to.isoformat() if memory.valid_to else None,
        "supersedes_id": str(memory.supersedes_id) if memory.supersedes_id else None,
        "evidence_segment_ids": memory.evidence_segment_ids,
        "extractor": memory.extractor,
        "meeting_created_at": meeting.created_at.isoformat(),
    }


def _apply_scope(
    statement: Any,
    *,
    meeting_ids: list[uuid.UUID] | None = None,
    project_id: str | None = None,
    time_from: datetime | None = None,
    time_to: datetime | None = None,
) -> Any:
    if meeting_ids:
        statement = statement.where(Meeting.id.in_(meeting_ids))
    if project_id:
        statement = statement.where(Meeting.project_id == project_id)
    if time_from:
        statement = statement.where(Meeting.created_at >= time_from)
    if time_to:
        statement = statement.where(Meeting.created_at <= time_to)
    return statement


def search_memories(
    db: Session,
    *,
    query: str,
    meeting_ids: list[uuid.UUID] | None = None,
    project_id: str | None = None,
    time_from: datetime | None = None,
    time_to: datetime | None = None,
    kinds: list[str] | None = None,
    limit: int = 30,
    query_embedding: list[float] | None = None,
) -> list[dict[str, Any]]:
    terms = tokenize(query) or [query.strip()]
    base = (
        select(MemoryRecord, Meeting)
        .join(Meeting, MemoryRecord.meeting_id == Meeting.id)
        .where(
            MemoryRecord.tenant_id == current_tenant_id(),
            Meeting.tenant_id == current_tenant_id(),
            Meeting.status == "READY",
        )
    )
    base = _apply_scope(
        base,
        meeting_ids=meeting_ids,
        project_id=project_id,
        time_from=time_from,
        time_to=time_to,
    )
    if kinds:
        base = base.where(MemoryRecord.kind.in_(kinds))
    conditions = [
        or_(
            MemoryRecord.content.ilike(f"%{term}%"),
            MemoryRecord.subject.ilike(f"%{term}%"),
        )
        for term in terms[:12]
        if term
    ]
    lexical_rows = db.execute(
        base.where(or_(*conditions)).limit(max(limit * 4, 50))
        if conditions
        else base.limit(max(limit * 4, 50))
    ).all()
    semantic_rows = []
    if query_embedding:
        semantic_rows = db.execute(
            base.where(MemoryRecord.embedding.is_not(None))
            .order_by(MemoryRecord.embedding.cosine_distance(query_embedding))
            .limit(max(limit * 4, 50))
        ).all()
    candidates: dict[str, tuple[MemoryRecord, Meeting]] = {}
    lexical_rank: dict[str, int] = {}
    semantic_rank: dict[str, int] = {}
    for rank, row in enumerate(lexical_rows, 1):
        key = str(row[0].id)
        candidates[key] = row
        lexical_rank[key] = rank
    for rank, row in enumerate(semantic_rows, 1):
        key = str(row[0].id)
        candidates[key] = row
        semantic_rank[key] = rank
    values = []
    for key, (memory, meeting) in candidates.items():
        value = _memory_dict(memory, meeting)
        rrf = (1 / (60 + lexical_rank[key]) if key in lexical_rank else 0) + (
            1 / (60 + semantic_rank[key]) if key in semantic_rank else 0
        )
        value["score"] = round(rrf, 6)
        value["retrieval"] = (
            "hybrid"
            if key in lexical_rank and key in semantic_rank
            else "semantic"
            if key in semantic_rank
            else "lexical"
        )
        values.append(value)
    evidence_ids = {
        uuid.UUID(segment_id)
        for value in values
        for segment_id in value["evidence_segment_ids"]
        if segment_id
    }
    evidence_by_id: dict[str, dict[str, Any]] = {}
    if evidence_ids:
        for segment, speaker, meeting in db.execute(
            select(Segment, Speaker, Meeting)
            .join(Meeting, Segment.meeting_id == Meeting.id)
            .outerjoin(Speaker, Segment.speaker_id == Speaker.id)
            .where(Segment.id.in_(evidence_ids))
        ).all():
            evidence_by_id[str(segment.id)] = {
                "segment_id": str(segment.id),
                "meeting_id": str(meeting.id),
                "meeting_title": meeting.title,
                "speaker_id": str(speaker.id) if speaker else None,
                "speaker_name": speaker.display_name if speaker else "Unknown",
                "start_ms": segment.start_ms,
                "end_ms": segment.end_ms,
                "text": segment.text,
            }
    for value in values:
        value["evidence"] = [
            evidence_by_id[segment_id]
            for segment_id in value["evidence_segment_ids"]
            if segment_id in evidence_by_id
        ]
    values.sort(key=lambda item: (-item["score"], item["meeting_created_at"]))
    return values[:limit]


def memory_timeline(
    db: Session,
    *,
    meeting_ids: list[uuid.UUID] | None = None,
    project_id: str | None = None,
) -> dict[str, Any]:
    statement = (
        select(MemoryRecord, Meeting)
        .join(Meeting, MemoryRecord.meeting_id == Meeting.id)
        .where(
            MemoryRecord.tenant_id == current_tenant_id(),
            Meeting.status == "READY",
        )
    )
    statement = _apply_scope(statement, meeting_ids=meeting_ids, project_id=project_id)
    rows = db.execute(statement.order_by(Meeting.created_at, MemoryRecord.created_at)).all()
    ids = [memory.id for memory, _ in rows]
    links = []
    if ids:
        links = [
            {
                "source_memory_id": str(link.source_memory_id),
                "target_memory_id": str(link.target_memory_id),
                "relation": link.relation,
                "confidence": link.confidence,
                "rationale": link.rationale,
            }
            for link in db.scalars(
                select(MemoryLink).where(
                    or_(
                        MemoryLink.source_memory_id.in_(ids),
                        MemoryLink.target_memory_id.in_(ids),
                    )
                )
            ).all()
        ]
    return {
        "events": [_memory_dict(memory, meeting) for memory, meeting in rows],
        "links": links,
    }


def meeting_report(db: Session, meeting_id: uuid.UUID) -> dict[str, Any] | None:
    meeting = get_meeting(db, meeting_id)
    if not meeting:
        return None
    return {
        "meeting": {
            "id": str(meeting.id),
            "tenant_id": str(meeting.tenant_id),
            "title": meeting.title,
            "project_id": meeting.project_id,
            "status": meeting.status,
            "source_provider": meeting.source_provider,
            "duration_ms": meeting.duration_ms,
            "audio_uri": meeting.audio_uri,
            "created_at": meeting.created_at.isoformat(),
        },
        "transcript": transcript(db, meeting_id),
        "artifacts": artifacts(db, meeting_id),
        "memories": meeting_memories(db, meeting_id),
    }


def scoped_analysis(
    db: Session,
    *,
    meeting_ids: list[uuid.UUID] | None = None,
    project_id: str | None = None,
    time_from: datetime | None = None,
    time_to: datetime | None = None,
) -> dict[str, Any]:
    statement = select(Meeting).where(
        Meeting.tenant_id == current_tenant_id(),
        Meeting.status == "READY",
    )
    statement = _apply_scope(
        statement,
        meeting_ids=meeting_ids,
        project_id=project_id,
        time_from=time_from,
        time_to=time_to,
    )
    meetings = list(db.scalars(statement.order_by(Meeting.created_at)).all())
    grouped: dict[str, list[dict[str, Any]]] = {
        "decisions": [],
        "action_items": [],
        "risks": [],
        "open_questions": [],
        "topics": [],
    }
    summaries = []
    kind_groups = {
        "decision": "decisions",
        "action_item": "action_items",
        "risk": "risks",
        "open_question": "open_questions",
        "topic": "topics",
    }
    for meeting in meetings:
        values = artifacts(db, meeting.id)
        summary = ((values.get("summary") or {}).get("data") or {}).get("text")
        summaries.append(
            {
                "meeting_id": str(meeting.id),
                "title": meeting.title,
                "project_id": meeting.project_id,
                "created_at": meeting.created_at.isoformat(),
                "summary": summary,
            }
        )
        for memory in meeting_memories(db, meeting.id):
            destination = kind_groups.get(memory["kind"])
            if destination:
                grouped[destination].append(memory)
    keyword_counter: Counter[str] = Counter(
        item["subject"] or item["content"] for item in grouped["topics"]
    )
    return {
        "scope": {
            "meeting_ids": [str(item.id) for item in meetings],
            "project_id": project_id,
        },
        "meeting_count": len(meetings),
        "meetings": summaries,
        "overall_summary": "\n".join(
            f"{index + 1}. {item['title']}：{item['summary'] or '暂无摘要'}"
            for index, item in enumerate(summaries)
        ),
        **grouped,
        "top_topics": [
            {"text": text, "meeting_mentions": count}
            for text, count in keyword_counter.most_common(30)
        ],
        "timeline": memory_timeline(
            db, meeting_ids=[item.id for item in meetings], project_id=project_id
        ),
    }


def create_conversation(
    db: Session, *, title: str, scope: dict[str, Any]
) -> Conversation:
    conversation = Conversation(
        tenant_id=current_tenant_id(),
        user_id=current_user_id(),
        title=title,
        scope=scope,
    )
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation


def list_conversations(db: Session) -> list[dict[str, Any]]:
    conversations = db.scalars(
        select(Conversation)
        .where(
            Conversation.tenant_id == current_tenant_id(),
            Conversation.user_id == current_user_id(),
        )
        .order_by(Conversation.updated_at.desc())
    ).all()
    return [
        {
            "id": str(item.id),
            "title": item.title,
            "scope": item.scope,
            "created_at": item.created_at.isoformat(),
            "updated_at": item.updated_at.isoformat(),
        }
        for item in conversations
    ]


def get_conversation(db: Session, conversation_id: uuid.UUID) -> Conversation | None:
    return db.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.tenant_id == current_tenant_id(),
            Conversation.user_id == current_user_id(),
        )
    )


def conversation_messages(
    db: Session, conversation_id: uuid.UUID
) -> list[dict[str, Any]]:
    return [
        {
            "id": str(item.id),
            "role": item.role,
            "content": item.content,
            "payload": item.payload,
            "created_at": item.created_at.isoformat(),
        }
        for item in db.scalars(
            select(ConversationMessage)
            .where(ConversationMessage.conversation_id == conversation_id)
            .order_by(ConversationMessage.created_at)
        ).all()
    ]


def append_conversation_exchange(
    db: Session,
    conversation: Conversation,
    *,
    question: str,
    response: dict[str, Any],
) -> None:
    db.add(
        ConversationMessage(
            conversation_id=conversation.id,
            role="user",
            content=question,
            payload={},
        )
    )
    db.add(
        ConversationMessage(
            conversation_id=conversation.id,
            role="assistant",
            content=response["answer"],
            payload=response,
        )
    )
    conversation.updated_at = func.now()
    db.commit()


def search_segments(
    db: Session,
    *,
    query: str,
    meeting_ids: list[uuid.UUID] | None = None,
    project_id: str | None = None,
    time_from: datetime | None = None,
    time_to: datetime | None = None,
    limit: int = 20,
    query_embedding: list[float] | None = None,
) -> list[dict[str, Any]]:
    terms = tokenize(query)
    if not terms:
        terms = [query.strip()]

    statement = (
        select(Segment, Speaker, Meeting)
        .join(Meeting, Segment.meeting_id == Meeting.id)
        .outerjoin(Speaker, Segment.speaker_id == Speaker.id)
        .where(
            Segment.tenant_id == current_tenant_id(),
            Meeting.tenant_id == current_tenant_id(),
            Meeting.status == "READY",
        )
    )
    if meeting_ids:
        statement = statement.where(Meeting.id.in_(meeting_ids))
    if project_id:
        statement = statement.where(Meeting.project_id == project_id)
    if time_from:
        statement = statement.where(Meeting.created_at >= time_from)
    if time_to:
        statement = statement.where(Meeting.created_at <= time_to)

    base_statement = statement
    conditions = [Segment.text.ilike(f"%{term}%") for term in terms[:12] if term]
    lexical_rows = (
        db.execute(
            statement.where(or_(*conditions)).limit(max(limit * 5, 50))
            if conditions
            else statement.limit(max(limit * 5, 50))
        ).all()
    )
    semantic_rows = []
    if query_embedding:
        semantic_rows = db.execute(
            base_statement.where(Segment.embedding.is_not(None))
            .order_by(Segment.embedding.cosine_distance(query_embedding))
            .limit(max(limit * 5, 50))
        ).all()

    candidates: dict[str, tuple[Any, Any, Any]] = {}
    lexical_rank: dict[str, int] = {}
    semantic_rank: dict[str, int] = {}
    for rank, row in enumerate(lexical_rows, 1):
        key = str(row[0].id)
        candidates[key] = row
        lexical_rank[key] = rank
    for rank, row in enumerate(semantic_rows, 1):
        key = str(row[0].id)
        candidates[key] = row
        semantic_rank[key] = rank

    ranked = []
    for key, (segment, speaker, meeting) in candidates.items():
        lowered = segment.text.lower()
        matched = sum(1 for term in terms if term.lower() in lowered)
        lexical_score = matched / max(len(terms), 1)
        rrf = 0.0
        if key in lexical_rank:
            rrf += 1.0 / (60 + lexical_rank[key])
        if key in semantic_rank:
            rrf += 1.0 / (60 + semantic_rank[key])
        semantic_score = (
            round(1.0 / semantic_rank[key], 6) if key in semantic_rank else 0.0
        )
        ranked.append(
            {
                "segment_id": str(segment.id),
                "meeting_id": str(meeting.id),
                "meeting_title": meeting.title,
                "project_id": meeting.project_id,
                "meeting_created_at": meeting.created_at.isoformat(),
                "speaker_id": str(speaker.id) if speaker else None,
                "speaker_name": speaker.display_name if speaker else "Unknown",
                "start_ms": segment.start_ms,
                "end_ms": segment.end_ms,
                "text": segment.text,
                "score": round(rrf, 6),
                "lexical_score": round(lexical_score, 4),
                "semantic_score": semantic_score,
                "retrieval": (
                    "hybrid"
                    if key in lexical_rank and key in semantic_rank
                    else "semantic"
                    if key in semantic_rank
                    else "lexical"
                ),
            }
        )
    ranked.sort(
        key=lambda item: (
            -item["score"],
            -item["lexical_score"],
            item["meeting_created_at"],
        )
    )
    return ranked[:limit]


def overview(db: Session, project_id: str | None = None) -> dict[str, Any]:
    meetings = list_meetings(db, project_id)
    summaries = []
    keyword_counter: Counter[str] = Counter()

    for meeting in meetings:
        meeting_artifacts = artifacts(db, meeting.id)
        summary = ((meeting_artifacts.get("summary") or {}).get("data") or {}).get("text")
        keywords = (
            ((meeting_artifacts.get("keywords") or {}).get("data") or {}).get("items") or []
        )
        for item in keywords:
            if isinstance(item, dict) and item.get("text"):
                keyword_counter[item["text"]] += int(item.get("count", 1))
        summaries.append(
            {
                "meeting_id": str(meeting.id),
                "title": meeting.title,
                "project_id": meeting.project_id,
                "status": meeting.status,
                "summary": summary,
                "created_at": meeting.created_at.isoformat(),
            }
        )
    return {
        "meeting_count": len(meetings),
        "meetings": summaries,
        "top_keywords": [
            {"text": text, "count": count} for text, count in keyword_counter.most_common(30)
        ],
    }


def save_query_audit(
    db: Session, query: str, scope: dict[str, Any], response: dict[str, Any]
) -> None:
    db.add(
        QueryAudit(
            tenant_id=current_tenant_id(),
            user_id=current_user_id(),
            query=query,
            scope=scope,
            response=response,
        )
    )
    db.commit()


def counts(db: Session) -> dict[str, int]:
    return {
        "meetings": db.scalar(select(func.count(Meeting.id))) or 0,
        "segments": db.scalar(select(func.count(Segment.id))) or 0,
        "words": db.scalar(select(func.count(Word.id))) or 0,
        "artifacts": db.scalar(select(func.count(Artifact.id))) or 0,
        "memories": db.scalar(select(func.count(MemoryRecord.id))) or 0,
    }
