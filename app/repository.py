from __future__ import annotations

import uuid
from collections import Counter
from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import (
    Artifact,
    Meeting,
    MeetingAccess,
    MemoryRecord,
    QueryAudit,
    Segment,
    Speaker,
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
) -> Meeting:
    meeting = Meeting(
        tenant_id=settings.default_tenant_id,
        created_by=settings.default_user_id,
        title=title,
        project_id=project_id,
        source_language=source_language,
        audio_uri=audio_uri,
        raw_result=raw_result,
        status="IMPORTED" if raw_result else "CREATED",
    )
    db.add(meeting)
    db.flush()
    db.add(
        MeetingAccess(
            meeting_id=meeting.id,
            user_id=settings.default_user_id,
            role="owner",
        )
    )
    db.commit()
    db.refresh(meeting)
    return meeting


def get_meeting(db: Session, meeting_id: uuid.UUID) -> Meeting | None:
    return db.scalar(
        select(Meeting).where(
            Meeting.id == meeting_id,
            Meeting.tenant_id == settings.default_tenant_id,
        )
    )


def get_meeting_by_task_id(db: Session, task_id: str) -> Meeting | None:
    return db.scalar(
        select(Meeting).where(
            Meeting.source_task_id == task_id,
            Meeting.tenant_id == settings.default_tenant_id,
        )
    )


def list_meetings(db: Session, project_id: str | None = None) -> list[Meeting]:
    statement = select(Meeting).where(Meeting.tenant_id == settings.default_tenant_id)
    if project_id:
        statement = statement.where(Meeting.project_id == project_id)
    return list(db.scalars(statement.order_by(Meeting.created_at.desc())).all())


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

    for item in normalized["artifacts"]:
        db.add(
            Artifact(
                tenant_id=meeting.tenant_id,
                meeting_id=meeting.id,
                kind=item["kind"],
                version=1,
                source=item["source"],
                data=item["data"],
            )
        )

    for item in normalized["memories"]:
        evidence_ids = [
            str(segment_by_ordinal[ordinal].id)
            for ordinal in item["evidence_ordinals"]
            if ordinal in segment_by_ordinal
        ]
        db.add(
            MemoryRecord(
                tenant_id=meeting.tenant_id,
                meeting_id=meeting.id,
                project_id=meeting.project_id,
                kind=item["kind"],
                subject=item["subject"],
                content=item["content"],
                status=item["status"],
                evidence_segment_ids=evidence_ids,
                extractor=item["extractor"],
            )
        )

    meeting.duration_ms = normalized.get("duration_ms")
    meeting.status = "READY"
    meeting.error = None
    db.commit()


def transcript(db: Session, meeting_id: uuid.UUID) -> list[dict[str, Any]]:
    statement = (
        select(Segment, Speaker)
        .outerjoin(Speaker, Segment.speaker_id == Speaker.id)
        .where(
            Segment.tenant_id == settings.default_tenant_id,
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
            Word.tenant_id == settings.default_tenant_id,
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
            Word.tenant_id == settings.default_tenant_id,
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
            Artifact.tenant_id == settings.default_tenant_id,
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


def search_segments(
    db: Session,
    *,
    query: str,
    meeting_ids: list[uuid.UUID] | None = None,
    project_id: str | None = None,
    time_from: datetime | None = None,
    time_to: datetime | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    terms = tokenize(query)
    if not terms:
        terms = [query.strip()]

    statement = (
        select(Segment, Speaker, Meeting)
        .join(Meeting, Segment.meeting_id == Meeting.id)
        .outerjoin(Speaker, Segment.speaker_id == Speaker.id)
        .where(
            Segment.tenant_id == settings.default_tenant_id,
            Meeting.tenant_id == settings.default_tenant_id,
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

    conditions = [Segment.text.ilike(f"%{term}%") for term in terms[:12] if term]
    if conditions:
        statement = statement.where(or_(*conditions))

    rows = db.execute(statement.limit(max(limit * 5, 50))).all()
    ranked = []
    for segment, speaker, meeting in rows:
        lowered = segment.text.lower()
        matched = sum(1 for term in terms if term.lower() in lowered)
        score = matched / max(len(terms), 1)
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
                "score": round(score, 4),
            }
        )
    ranked.sort(key=lambda item: (-item["score"], item["meeting_created_at"]))
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
            tenant_id=settings.default_tenant_id,
            user_id=settings.default_user_id,
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
