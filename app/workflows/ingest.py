from __future__ import annotations

import asyncio
from datetime import timedelta
from uuid import UUID

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from app.db import SessionLocal
    from app.repository import get_meeting, replace_normalized
    from app.services.graph_memory import ingest_episode
    from app.services.embeddings import embedding_service
    from app.services.normalizer import normalize_tingwu
    from app.services.tingwu import TingwuClient


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
                client = TingwuClient()
                if meeting.source_task_id:
                    task_id = meeting.source_task_id
                else:
                    task_id = await asyncio.to_thread(
                        client.create_offline_task,
                        audio_url=meeting.audio_uri,
                        task_key=str(meeting.id),
                        source_language=meeting.source_language,
                    )
                    meeting.source_task_id = task_id
                    meeting.status = "SUBMITTED"
                    db.commit()
                raw = await client.wait_and_download(task_id)
                meeting.raw_result = raw
                meeting.status = "NORMALIZING"
                db.commit()

            normalized = normalize_tingwu(raw)
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
            graph_payload = {
                "meeting_id": meeting_id,
                "title": meeting.title,
                "project_id": project_id,
                "memories": normalized["memories"],
            }

        graph_indexed = False
        try:
            graph_indexed = await ingest_episode(meeting_id, project_id, graph_payload)
        except Exception as graph_exc:
            activity.logger.warning(
                "Graph index failed for meeting %s: %s",
                meeting_id,
                graph_exc,
            )
        return {
            "meeting_id": meeting_id,
            "status": "READY",
            "segments": len(normalized["segments"]),
            "artifacts": len(normalized["artifacts"]),
            "memories": len(normalized["memories"]),
            "graph_indexed": graph_indexed,
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
