from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from app.db import SessionLocal
    from app.models import PipelineRun, PipelineStage
    from app.repository import (
        canonical_payload,
        get_meeting,
        meeting_report,
        memory_timeline,
        replace_canonical,
        replace_intelligence,
    )
    from app.services.asr import asr_registry
    from app.services.embeddings import embedding_service
    from app.services.extraction import extract_with_cache
    from app.services.graph_memory import ingest_episode
    from app.services.storage import provider_audio_url


def _stage_start(db: Any, meeting: Any, stage_name: str) -> tuple[Any, Any]:
    info = activity.info()
    pipeline = db.scalar(
        select(PipelineRun).where(PipelineRun.workflow_id == info.workflow_id)
    )
    if pipeline is None:
        pipeline = PipelineRun(
            tenant_id=meeting.tenant_id,
            meeting_id=meeting.id,
            workflow_id=info.workflow_id,
            workflow_run_id=info.workflow_run_id,
            status="RUNNING",
        )
        db.add(pipeline)
        db.flush()
    stage = db.scalar(
        select(PipelineStage).where(
            PipelineStage.pipeline_run_id == pipeline.id,
            PipelineStage.stage == stage_name,
        )
    )
    if stage is None:
        stage = PipelineStage(
            pipeline_run_id=pipeline.id,
            stage=stage_name,
            status="RUNNING",
            attempt_count=info.attempt,
            output={},
        )
        db.add(stage)
    else:
        stage.status = "RUNNING"
        stage.attempt_count = max(stage.attempt_count, info.attempt)
        stage.error = None
        stage.completed_at = None
    pipeline.status = "RUNNING"
    db.commit()
    return pipeline, stage


def _stage_finish(db: Any, stage: Any, output: dict[str, Any]) -> None:
    stage.status = "COMPLETED"
    stage.output = output
    stage.error = None
    stage.completed_at = datetime.now(UTC)
    db.commit()


def _stage_fail(db: Any, meeting: Any, stage: Any, exc: Exception) -> None:
    error = {
        "stage": stage.stage,
        "type": type(exc).__name__,
        "message": str(exc)[:2000],
    }
    stage.status = "FAILED"
    stage.error = error
    stage.completed_at = datetime.now(UTC)
    meeting.status = "FAILED"
    meeting.error = error
    db.commit()


@activity.defn
async def prepare_audio_activity(meeting_id: str) -> dict[str, Any]:
    """Audio preflight is a separate durable stage; implementation lives in audio.py."""

    meeting_uuid = UUID(meeting_id)
    with SessionLocal() as db:
        meeting = get_meeting(db, meeting_uuid)
        if not meeting:
            raise ValueError(f"meeting not found: {meeting_id}")
        _, stage = _stage_start(db, meeting, "audio_preflight")
        try:
            # Imported provider fixtures already contain ASR output and intentionally
            # skip audio processing. Normal audio meetings are handled by audio.py;
            # the call is imported lazily so fixture-only deployments stay lightweight.
            if meeting.raw_result:
                output = {"status": "SKIPPED", "reason": "raw_result_import"}
            else:
                from app.services.audio import prepare_meeting_audio

                output = await asyncio.to_thread(prepare_meeting_audio, db, meeting)
            _stage_finish(db, stage, output)
            return output
        except Exception as exc:
            _stage_fail(db, meeting, stage, exc)
            raise


@activity.defn
async def transcribe_activity(meeting_id: str) -> dict[str, Any]:
    meeting_uuid = UUID(meeting_id)
    with SessionLocal() as db:
        meeting = get_meeting(db, meeting_uuid)
        if not meeting:
            raise ValueError(f"meeting not found: {meeting_id}")
        _, stage = _stage_start(db, meeting, "transcription")
        try:
            if meeting.raw_result:
                output = {"status": "SKIPPED", "reason": "raw_result_import"}
                _stage_finish(db, stage, output)
                return output
            provider = asr_registry.get(meeting.source_provider)
            if meeting.source_task_id:
                task_id = meeting.source_task_id
            else:
                audio_url = getattr(meeting, "normalized_audio_uri", None) or meeting.audio_uri
                if audio_url and audio_url.startswith("minio://"):
                    audio_url = provider_audio_url(meeting.id, audio_url)
                task_id = await provider.submit(
                    audio_url=audio_url,
                    task_key=str(meeting.id),
                    source_language=meeting.source_language,
                )
                meeting.source_task_id = task_id
                meeting.status = "TRANSCRIBING"
                db.commit()
            raw = await provider.wait(task_id)
            meeting.raw_result = raw
            meeting.status = "TRANSCRIBED"
            db.commit()
            output = {"status": "COMPLETED", "provider": provider.name, "task_id": task_id}
            _stage_finish(db, stage, output)
            return output
        except Exception as exc:
            _stage_fail(db, meeting, stage, exc)
            raise


@activity.defn
async def normalize_activity(meeting_id: str) -> dict[str, Any]:
    meeting_uuid = UUID(meeting_id)
    with SessionLocal() as db:
        meeting = get_meeting(db, meeting_uuid)
        if not meeting:
            raise ValueError(f"meeting not found: {meeting_id}")
        _, stage = _stage_start(db, meeting, "canonical_normalization")
        try:
            if not meeting.raw_result:
                raise ValueError("transcription result is missing")
            canonical = asr_registry.get(meeting.source_provider).normalize(
                meeting.raw_result
            )
            vectors = await asyncio.to_thread(
                embedding_service().documents,
                [item["text"] for item in canonical["segments"]],
            )
            for item, vector in zip(canonical["segments"], vectors, strict=True):
                item["embedding"] = vector or None
            replace_canonical(db, meeting, canonical)
            output = {
                "status": "COMPLETED",
                "speakers": len(canonical["speakers"]),
                "segments": len(canonical["segments"]),
                "words": len(canonical["words"]),
            }
            _stage_finish(db, stage, output)
            return output
        except Exception as exc:
            _stage_fail(db, meeting, stage, exc)
            raise


@activity.defn
async def extract_activity(meeting_id: str) -> dict[str, Any]:
    meeting_uuid = UUID(meeting_id)
    with SessionLocal() as db:
        meeting = get_meeting(db, meeting_uuid)
        if not meeting:
            raise ValueError(f"meeting not found: {meeting_id}")
        _, stage = _stage_start(db, meeting, "unified_extraction")
        try:
            canonical = canonical_payload(db, meeting)
            intelligence = await extract_with_cache(db, meeting, canonical)
            vectors = await asyncio.to_thread(
                embedding_service().documents,
                [item["content"] for item in intelligence["memories"]],
            )
            for item, vector in zip(intelligence["memories"], vectors, strict=True):
                item["embedding"] = vector or None
            replace_intelligence(db, meeting, intelligence)
            output = {
                "status": "COMPLETED",
                "artifacts": len(intelligence["artifacts"]),
                "memories": len(intelligence["memories"]),
                "canonical_hash": meeting.canonical_hash,
            }
            _stage_finish(db, stage, output)
            return output
        except Exception as exc:
            _stage_fail(db, meeting, stage, exc)
            raise


@activity.defn
async def graph_activity(meeting_id: str) -> dict[str, Any]:
    meeting_uuid = UUID(meeting_id)
    with SessionLocal() as db:
        meeting = get_meeting(db, meeting_uuid)
        if not meeting:
            raise ValueError(f"meeting not found: {meeting_id}")
        pipeline, stage = _stage_start(db, meeting, "graph_projection")
        try:
            project_id = meeting.project_id
            payload = meeting_report(db, meeting_uuid)
            if payload is None:
                raise RuntimeError("meeting report unavailable after extraction")
            payload["memory_links"] = memory_timeline(
                db, project_id=project_id
            )["links"]
            result = await ingest_episode(meeting_id, project_id, payload)
            meeting.graph_status = "READY" if result.get("indexed") else "DISABLED"
            meeting.graph_indexed_at = (
                datetime.now(UTC) if result.get("indexed") else None
            )
            meeting.status = "READY"
            meeting.error = None
            pipeline.status = "COMPLETED"
            pipeline.completed_at = datetime.now(UTC)
            db.commit()
            output = {"status": "COMPLETED", **result}
            _stage_finish(db, stage, output)
            return output
        except Exception as exc:
            meeting.graph_status = "FAILED"
            _stage_fail(db, meeting, stage, exc)
            pipeline.status = "FAILED"
            pipeline.completed_at = datetime.now(UTC)
            db.commit()
            raise


@workflow.defn
class MeetingIngestWorkflow:
    @workflow.run
    async def run(self, meeting_id: str) -> dict[str, Any]:
        short_retry = RetryPolicy(
            initial_interval=timedelta(seconds=3),
            maximum_interval=timedelta(minutes=1),
            maximum_attempts=3,
        )
        network_retry = RetryPolicy(
            initial_interval=timedelta(seconds=10),
            maximum_interval=timedelta(minutes=5),
            maximum_attempts=5,
        )
        audio = await workflow.execute_activity(
            prepare_audio_activity,
            meeting_id,
            start_to_close_timeout=timedelta(hours=1),
            retry_policy=short_retry,
        )
        transcription = await workflow.execute_activity(
            transcribe_activity,
            meeting_id,
            start_to_close_timeout=timedelta(hours=6),
            retry_policy=network_retry,
        )
        canonical = await workflow.execute_activity(
            normalize_activity,
            meeting_id,
            start_to_close_timeout=timedelta(hours=1),
            retry_policy=short_retry,
        )
        extraction = await workflow.execute_activity(
            extract_activity,
            meeting_id,
            start_to_close_timeout=timedelta(hours=1),
            retry_policy=network_retry,
        )
        graph = await workflow.execute_activity(
            graph_activity,
            meeting_id,
            start_to_close_timeout=timedelta(hours=1),
            retry_policy=short_retry,
        )
        return {
            "meeting_id": meeting_id,
            "status": "READY",
            "audio": audio,
            "transcription": transcription,
            "canonical": canonical,
            "extraction": extraction,
            "graph": graph,
        }
