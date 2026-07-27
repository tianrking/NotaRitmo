from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import IntegrationOutbox, Meeting
from app.repository import artifacts


def enqueue_meeting_intelligence(db: Session, meeting: Meeting) -> dict[str, Any]:
    values = artifacts(db, meeting.id)
    summary = ((values.get("summary") or {}).get("data") or {})
    actions = ((values.get("action_items") or {}).get("data") or {}).get("items", [])
    idempotency_key = (
        f"meeting.intelligence.ready:{meeting.id}:"
        f"{meeting.canonical_hash}:{settings.hera_outbox_schema_version}"
    )
    existing = db.scalar(
        select(IntegrationOutbox).where(
            IntegrationOutbox.idempotency_key == idempotency_key
        )
    )
    if existing:
        return {
            "event_id": str(existing.id),
            "status": existing.status,
            "cached": True,
        }
    payload = {
        "meeting": {
            "id": str(meeting.id),
            "tenant_id": str(meeting.tenant_id),
            "title": meeting.title,
            "project_id": meeting.project_id,
            "duration_ms": meeting.duration_ms,
            "canonical_hash": meeting.canonical_hash,
        },
        "cards": {
            kind: value
            for kind, value in values.items()
            if kind
            in {
                "summary",
                "detailed_summary",
                "facts",
                "decisions",
                "risks",
                "open_questions",
                "chapters",
                "keywords",
                "mindmap",
                "speaker_stats",
            }
        },
        # These are evidence-bound suggestions. Hera remains the only system that
        # decides whether and how to materialize product Todo records.
        "todo_candidates": actions,
        "summary": summary,
        "ownership": {
            "permissions": "hera",
            "cards": "hera",
            "todo_materialization": "hera",
            "meeting_intelligence": "notaritmo",
        },
    }
    event = IntegrationOutbox(
        tenant_id=meeting.tenant_id,
        meeting_id=meeting.id,
        event_type="meeting.intelligence.ready",
        schema_version=settings.hera_outbox_schema_version,
        idempotency_key=idempotency_key,
        payload=payload,
        status="PENDING",
        delivery_attempts=0,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return {"event_id": str(event.id), "status": event.status, "cached": False}


def pending_events(
    db: Session, *, tenant_id: UUID, limit: int
) -> list[dict[str, Any]]:
    rows = list(
        db.scalars(
            select(IntegrationOutbox)
            .where(
                IntegrationOutbox.tenant_id == tenant_id,
                IntegrationOutbox.status == "PENDING",
            )
            .order_by(IntegrationOutbox.created_at)
            .limit(limit)
        ).all()
    )
    for row in rows:
        row.delivery_attempts += 1
    db.commit()
    return [
        {
            "id": str(row.id),
            "event_type": row.event_type,
            "schema_version": row.schema_version,
            "idempotency_key": row.idempotency_key,
            "payload": row.payload,
            "delivery_attempts": row.delivery_attempts,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]


def acknowledge_event(
    db: Session, *, event_id: UUID, tenant_id: UUID, user_id: UUID
) -> bool:
    event = db.scalar(
        select(IntegrationOutbox).where(
            IntegrationOutbox.id == event_id,
            IntegrationOutbox.tenant_id == tenant_id,
        )
    )
    if not event:
        return False
    event.status = "ACKNOWLEDGED"
    event.acknowledged_at = datetime.now(UTC)
    event.acknowledged_by = user_id
    db.commit()
    return True
