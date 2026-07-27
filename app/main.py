from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, FastAPI, File, Form, HTTPException, Response, UploadFile, status
from sqlalchemy import text
from sqlalchemy.orm import Session
from temporalio.client import Client

from app.config import settings
from app.db import get_db
from app.repository import (
    artifacts,
    counts,
    create_meeting,
    get_meeting,
    get_meeting_by_task_id,
    list_meetings,
    overview,
    search_segments,
    transcript,
    words,
)
from app.schemas import (
    AgentQuery,
    ImportedMeetingCreate,
    MeetingCreate,
    MeetingResponse,
    SearchRequest,
    TingwuCallback,
)
from app.services.agent import run_agent
from app.services.storage import ensure_bucket, presigned_get, put_bytes
from app.workflows.ingest import MeetingIngestWorkflow


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_bucket()
    yield


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Evidence-first single- and cross-meeting memory API.",
    lifespan=lifespan,
)


async def start_ingest(meeting_id: UUID) -> str:
    client = await Client.connect(
        settings.temporal_address,
        namespace=settings.temporal_namespace,
    )
    workflow_id = f"meeting-ingest-{meeting_id}-{uuid.uuid4().hex[:8]}"
    await client.start_workflow(
        MeetingIngestWorkflow.run,
        str(meeting_id),
        id=workflow_id,
        task_queue=settings.temporal_task_queue,
    )
    return workflow_id


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": settings.app_name, "version": settings.app_version}


@app.get("/ready")
def ready(db: Annotated[Session, Depends(get_db)]) -> dict[str, Any]:
    db.execute(text("select 1"))
    return {"status": "ready", "counts": counts(db)}


@app.post(
    "/v1/meetings",
    response_model=MeetingResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_from_url(
    payload: MeetingCreate,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> MeetingResponse:
    meeting = create_meeting(
        db,
        title=payload.title,
        audio_uri=str(payload.audio_url),
        project_id=payload.project_id,
        source_language=payload.source_language,
    )
    try:
        response.headers["X-Workflow-Id"] = await start_ingest(meeting.id)
    except Exception as exc:
        meeting.status = "QUEUED"
        meeting.error = {"stage": "workflow_start", "message": str(exc)}
        db.commit()
    return MeetingResponse.model_validate(meeting)


@app.post(
    "/v1/meetings/upload",
    response_model=MeetingResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_audio(
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    file: Annotated[UploadFile, File()],
    title: Annotated[str, Form()],
    project_id: Annotated[str | None, Form()] = None,
    source_language: Annotated[str, Form()] = "cn",
    public_audio_url: Annotated[str | None, Form()] = None,
) -> MeetingResponse:
    content = await file.read()
    temporary_id = uuid.uuid4()
    safe_name = (file.filename or "audio.bin").replace("/", "_").replace("\\", "_")
    object_name = f"{settings.default_tenant_id}/{temporary_id}/{safe_name}"
    internal_uri = put_bytes(
        object_name,
        content,
        file.content_type or "application/octet-stream",
    )
    meeting = create_meeting(
        db,
        title=title,
        audio_uri=public_audio_url or internal_uri,
        project_id=project_id,
        source_language=source_language,
    )
    if public_audio_url:
        try:
            response.headers["X-Workflow-Id"] = await start_ingest(meeting.id)
        except Exception as exc:
            meeting.status = "QUEUED"
            meeting.error = {"stage": "workflow_start", "message": str(exc)}
            db.commit()
    else:
        meeting.status = "UPLOADED"
        meeting.error = {
            "stage": "awaiting_public_url",
            "message": "听悟必须能从公网访问音频；请提供 public_audio_url 后提交。",
            "stored_uri": internal_uri,
        }
        db.commit()
    return MeetingResponse.model_validate(meeting)


@app.post(
    "/v1/meetings/import/tingwu",
    response_model=MeetingResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def import_tingwu(
    payload: ImportedMeetingCreate,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> MeetingResponse:
    meeting = create_meeting(
        db,
        title=payload.title,
        audio_uri=payload.audio_uri,
        project_id=payload.project_id,
        source_language=payload.source_language,
        raw_result=payload.raw_result,
    )
    try:
        response.headers["X-Workflow-Id"] = await start_ingest(meeting.id)
    except Exception as exc:
        meeting.status = "QUEUED"
        meeting.error = {"stage": "workflow_start", "message": str(exc)}
        db.commit()
    return MeetingResponse.model_validate(meeting)


@app.post("/v1/meetings/{meeting_id}/reprocess", status_code=status.HTTP_202_ACCEPTED)
async def reprocess(
    meeting_id: UUID,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, str]:
    meeting = get_meeting(db, meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="meeting not found")
    workflow_id = await start_ingest(meeting_id)
    return {"meeting_id": str(meeting_id), "workflow_id": workflow_id}


@app.get("/v1/meetings", response_model=list[MeetingResponse])
def meetings(
    db: Annotated[Session, Depends(get_db)],
    project_id: str | None = None,
) -> list[MeetingResponse]:
    return [MeetingResponse.model_validate(item) for item in list_meetings(db, project_id)]


@app.get("/v1/meetings/{meeting_id}", response_model=MeetingResponse)
def meeting_detail(
    meeting_id: UUID,
    db: Annotated[Session, Depends(get_db)],
) -> MeetingResponse:
    meeting = get_meeting(db, meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="meeting not found")
    return MeetingResponse.model_validate(meeting)


@app.get("/v1/meetings/{meeting_id}/transcript")
def meeting_transcript(
    meeting_id: UUID,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    meeting = get_meeting(db, meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="meeting not found")
    return {"meeting_id": str(meeting_id), "segments": transcript(db, meeting_id)}


@app.get("/v1/meetings/{meeting_id}/artifacts")
def meeting_artifacts(
    meeting_id: UUID,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    meeting = get_meeting(db, meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="meeting not found")
    return {"meeting_id": str(meeting_id), "artifacts": artifacts(db, meeting_id)}


@app.get("/v1/meetings/{meeting_id}/words")
def meeting_words(
    meeting_id: UUID,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    meeting = get_meeting(db, meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="meeting not found")
    return {"meeting_id": str(meeting_id), "words": words(db, meeting_id)}


@app.get("/v1/meetings/{meeting_id}/summary")
def meeting_summary(
    meeting_id: UUID,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    values = artifacts(db, meeting_id)
    if "summary" not in values:
        raise HTTPException(status_code=404, detail="summary not ready")
    return {"meeting_id": str(meeting_id), **values["summary"]}


@app.get("/v1/meetings/{meeting_id}/audio-url")
def meeting_audio_url(
    meeting_id: UUID,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, str | None]:
    meeting = get_meeting(db, meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="meeting not found")
    if meeting.audio_uri and meeting.audio_uri.startswith("minio://"):
        _, path = meeting.audio_uri.split("minio://", 1)
        _, object_name = path.split("/", 1)
        return {"meeting_id": str(meeting_id), "url": presigned_get(object_name)}
    return {"meeting_id": str(meeting_id), "url": meeting.audio_uri}


@app.post("/v1/search")
def search(
    payload: SearchRequest,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    results = search_segments(
        db,
        query=payload.query,
        meeting_ids=payload.meeting_ids,
        project_id=payload.project_id,
        limit=payload.limit,
    )
    return {
        "query": payload.query,
        "meeting_count": len({item["meeting_id"] for item in results}),
        "results": results,
    }


@app.post("/v1/agent/query")
async def agent_query(payload: AgentQuery) -> dict[str, Any]:
    return await run_agent(payload)


@app.get("/v1/analytics/overview")
def analytics_overview(
    db: Annotated[Session, Depends(get_db)],
    project_id: str | None = None,
) -> dict[str, Any]:
    return overview(db, project_id)


@app.post("/v1/providers/tingwu/callback", status_code=status.HTTP_202_ACCEPTED)
async def tingwu_callback(
    payload: TingwuCallback,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, str]:
    task_id = str(payload.Data.get("TaskId", ""))
    if not task_id:
        raise HTTPException(status_code=400, detail="missing Data.TaskId")
    meeting = get_meeting_by_task_id(db, task_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="unknown Tingwu TaskId")
    workflow_id = await start_ingest(meeting.id)
    return {"status": "accepted", "meeting_id": str(meeting.id), "workflow_id": workflow_id}
