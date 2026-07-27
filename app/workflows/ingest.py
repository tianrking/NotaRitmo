from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from app.db import SessionLocal
    from app.repository import (
        get_meeting,
        meeting_report,
        memory_timeline,
        replace_normalized,
    )
    from app.services.embeddings import embedding_service
    from app.services.asr import asr_registry
    from app.services.graph_memory import ingest_episode
    from app.services.intelligence import build_intelligence
    from app.services.storage import provider_audio_url


@activity.defn
async def process_meeting_activity(meeting_id: str) -> dict:
    meeting_uuid = UUID(meeting_id)
    try:
        with SessionLocal() as db:
            meeting = get_meeting(db, meeting_uuid)
            if not meeting:
                raise ValueError(f"meeting not found: {meeting_id}")
            meeting.status = "PROCESSING"
            meeting.error = None
            db.commit()

            raw = meeting.raw_result
            if not raw:
                provider = asr_registry.get(meeting.source_provider)
                if meeting.source_task_id:
                    task_id = meeting.source_task_id
                else:
                    audio_url = meeting.audio_uri
                    if audio_url and audio_url.startswith("minio://"):
                        audio_url = provider_audio_url(meeting.id)
                    task_id = await provider.submit(
                        audio_url=audio_url,
                        task_key=str(meeting.id),
                        source_language=meeting.source_language,
                    )
                    meeting.source_task_id = task_id
                    meeting.status = "SUBMITTED"
                    db.commit()
                raw = await provider.wait(task_id)
                meeting.raw_result = raw
                meeting.status = "NORMALIZING"
                db.commit()

            normalized = asr_registry.get(meeting.source_provider).normalize(raw)
            normalized.update(build_intelligence(normalized))
            embedder = embedding_service()
            segment_vectors = await asyncio.to_thread(
                embedder.documents,
                [item["text"] for item in normalized["segments"]],
            )
            for item, vector in zip(normalized["segments"], segment_vectors, strict=True):
                item["embedding"] = vector or None
            memory_vectors = await asyncio.to_thread(
                embedder.documents,
                [item["content"] for item in normalized["memories"]],
            )
            for item, vector in zip(normalized["memories"], memory_vectors, strict=True):
                item["embedding"] = vector or None
            replace_normalized(db, meeting, normalized)
            project_id = meeting.project_id
            graph_payload = meeting_report(db, meeting_uuid)
            if graph_payload is None:
                raise RuntimeError("canonical report unavailable after normalization")
            graph_payload["memory_links"] = memory_timeline(
                db, project_id=project_id
            )["links"]

        graph_result: dict = {"indexed": False}
        try:
            graph_result = await ingest_episode(meeting_id, project_id, graph_payload)
            with SessionLocal() as db:
                meeting = get_meeting(db, meeting_uuid)
                if meeting:
                    meeting.graph_status = (
                        "READY" if graph_result.get("indexed") else "DISABLED"
                    )
                    meeting.graph_indexed_at = (
                        datetime.now(UTC) if graph_result.get("indexed") else None
                    )
                    db.commit()
        except Exception as graph_exc:
            with SessionLocal() as db:
                meeting = get_meeting(db, meeting_uuid)
                if meeting:
                    meeting.graph_status = "FAILED"
                    meeting.error = {
                        "stage": "graph_projection",
                        "type": type(graph_exc).__name__,
                        "message": str(graph_exc)[:2000],
                    }
                    db.commit()
            activity.logger.warning(
                "Graph index failed for meeting %s: %s",
                meeting_id,
                graph_exc,
            )
            raise
        return {
            "meeting_id": meeting_id,
            "status": "READY",
            "segments": len(normalized["segments"]),
            "artifacts": len(normalized["artifacts"]),
            "memories": len(normalized["memories"]),
            "graph": graph_result,
        }
    except Exception as exc:
        with SessionLocal() as db:
            meeting = get_meeting(db, meeting_uuid)
            if meeting:
                meeting.status = "FAILED"
                meeting.error = {
                    "stage": "ingest",
                    "type": type(exc).__name__,
                    "message": str(exc)[:2000],
                }
                db.commit()
        raise


@workflow.defn
class MeetingIngestWorkflow:
    @workflow.run
    async def run(self, meeting_id: str) -> dict:
        return await workflow.execute_activity(
            process_meeting_activity,
            meeting_id,
            start_to_close_timeout=timedelta(hours=4),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=5),
                maximum_interval=timedelta(minutes=5),
                maximum_attempts=3,
            ),
        )
