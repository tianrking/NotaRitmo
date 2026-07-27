from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.orm import Session
from temporalio.client import Client

from app.config import settings
from app.auth import (
    current_tenant_id,
    current_user_id,
    hera_request_context,
)
from app.db import SessionLocal, get_db
from app.repository import (
    append_conversation_exchange,
    artifacts,
    conversation_messages,
    counts,
    create_conversation,
    create_meeting,
    create_upload_session,
    get_conversation,
    get_meeting,
    get_meeting_by_task_id,
    get_upload_session,
    list_conversations,
    list_meetings,
    meeting_memories,
    meeting_pipeline_runs,
    meeting_report,
    memory_timeline,
    overview,
    scoped_analysis,
    search_memories,
    search_segments,
    transcript,
    words,
)
from app.schemas import (
    AgentQuery,
    AnalysisRequest,
    CandidateReview,
    ConversationAsk,
    ConversationCreate,
    ImportedMeetingCreate,
    MeetingCreate,
    MeetingResponse,
    MemorySearchRequest,
    SearchRequest,
    TingwuCallback,
    UploadComplete,
    UploadInitiate,
    VoiceprintEnroll,
)
from app.services.agent import run_agent, scope_meeting_ids
from app.services.embeddings import embedding_service
from app.services.extraction import extraction_stats
from app.services.graph_memory import graph_for_meeting, graph_health, graph_search
from app.services.hera import acknowledge_event, pending_events
from app.services.storage import (
    ensure_bucket,
    parse_minio_uri,
    object_stat,
    presigned_get,
    presigned_put,
    put_bytes,
    stream_object,
    verify_provider_audio_token,
)
from app.services.voiceprint import (
    delete_person,
    delete_voiceprint_profile,
    enroll_voiceprint,
    list_candidates,
    list_people,
    match_tenant_speakers,
    review_candidate,
)
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
    dependencies=[Depends(hera_request_context)],
)


async def start_ingest(meeting_id: UUID) -> str:
    client = await Client.connect(
        settings.temporal_address,
        namespace=settings.temporal_namespace,
    )
    workflow_id = f"meeting-ingest-{meeting_id}-{uuid.uuid4().hex[:8]}"
    await client.start_workflow(
        MeetingIngestWorkflow.run,
        {
            "meeting_id": str(meeting_id),
            "tenant_id": str(current_tenant_id()),
            "user_id": str(current_user_id()),
        },
        id=workflow_id,
        task_queue=settings.temporal_task_queue,
    )
    return workflow_id


@app.post("/v1/uploads", status_code=status.HTTP_201_CREATED)
def initiate_direct_upload(
    payload: UploadInitiate,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    if payload.size_bytes > settings.audio_max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"file exceeds AUDIO_MAX_BYTES={settings.audio_max_bytes}",
        )
    upload = create_upload_session(
        db,
        filename=payload.filename,
        content_type=payload.content_type,
        expected_size=payload.size_bytes,
        expected_sha256=payload.sha256.lower() if payload.sha256 else None,
        title=payload.title,
        project_id=payload.project_id,
        source_language=payload.source_language,
        denoise_enabled=payload.denoise_enabled,
    )
    return {
        "upload_id": str(upload.id),
        "method": "PUT",
        "url": presigned_put(upload.object_name),
        "headers": {"Content-Type": payload.content_type},
        "expires_at": upload.expires_at.isoformat(),
        "max_bytes": settings.audio_max_bytes,
    }


@app.post(
    "/v1/uploads/{upload_id}/complete",
    response_model=MeetingResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def complete_direct_upload(
    upload_id: UUID,
    payload: UploadComplete,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> MeetingResponse:
    upload = get_upload_session(db, upload_id)
    if not upload:
        raise HTTPException(status_code=404, detail="upload session not found")
    if upload.status == "COMPLETED" and upload.meeting_id:
        meeting = get_meeting(db, upload.meeting_id)
        if meeting:
            return MeetingResponse.model_validate(meeting)
    if upload.expires_at < datetime.now(UTC):
        upload.status = "EXPIRED"
        db.commit()
        raise HTTPException(status_code=410, detail="upload session expired")
    if payload.sha256 and upload.expected_sha256:
        if payload.sha256.lower() != upload.expected_sha256.lower():
            raise HTTPException(status_code=422, detail="declared SHA-256 mismatch")
    try:
        stat_value = object_stat(upload.object_name)
    except Exception as exc:
        raise HTTPException(status_code=409, detail="object upload is not complete") from exc
    if stat_value["size"] != upload.expected_size:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "uploaded object size mismatch",
                "expected": upload.expected_size,
                "actual": stat_value["size"],
            },
        )
    meeting = create_meeting(
        db,
        title=upload.title,
        audio_uri=f"minio://{settings.minio_bucket}/{upload.object_name}",
        project_id=upload.project_id,
        source_language=upload.source_language,
        denoise_enabled=upload.denoise_enabled,
    )
    upload.meeting_id = meeting.id
    upload.status = "COMPLETED"
    upload.completed_at = datetime.now(UTC)
    db.commit()
    response.headers["X-Workflow-Id"] = await start_ingest(meeting.id)
    return MeetingResponse.model_validate(meeting)


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
    object_name = f"{current_tenant_id()}/{temporary_id}/{safe_name}"
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
    if public_audio_url or settings.tingwu_enabled:
        try:
            response.headers["X-Workflow-Id"] = await start_ingest(meeting.id)
        except Exception as exc:
            meeting.status = "QUEUED"
            meeting.error = {"stage": "workflow_start", "message": str(exc)}
            db.commit()
    else:
        meeting.status = "UPLOADED"
        meeting.error = {
            "stage": "awaiting_provider",
            "message": "音频已保存；启用并配置听悟后可直接重新处理。",
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


@app.get("/v1/meetings/{meeting_id}/report")
def complete_meeting_report(
    meeting_id: UUID,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    report = meeting_report(db, meeting_id)
    if not report:
        raise HTTPException(status_code=404, detail="meeting not found")
    return report


@app.get("/v1/meetings/{meeting_id}/memories")
def memories_for_meeting(
    meeting_id: UUID,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    if not get_meeting(db, meeting_id):
        raise HTTPException(status_code=404, detail="meeting not found")
    return {"meeting_id": str(meeting_id), "memories": meeting_memories(db, meeting_id)}


@app.post("/v1/search")
async def search(
    payload: SearchRequest,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    query_embedding = await asyncio.to_thread(embedding_service().query, payload.query)
    results = search_segments(
        db,
        query=payload.query,
        meeting_ids=payload.meeting_ids,
        project_id=payload.project_id,
        limit=payload.limit,
        query_embedding=query_embedding,
    )
    return {
        "query": payload.query,
        "meeting_count": len({item["meeting_id"] for item in results}),
        "results": results,
    }


@app.post("/v1/agent/query")
async def agent_query(payload: AgentQuery) -> dict[str, Any]:
    return await run_agent(payload)


@app.post("/v1/analysis")
def analyze_meetings(
    payload: AnalysisRequest,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    scope = payload.scope.model_dump(mode="json")
    return scoped_analysis(
        db,
        meeting_ids=scope_meeting_ids(scope),
        project_id=scope.get("project_id"),
        time_from=payload.scope.time_from,
        time_to=payload.scope.time_to,
    )


@app.post("/v1/memory/search")
async def memory_search(
    payload: MemorySearchRequest,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    scope = payload.scope.model_dump(mode="json")
    vector = await asyncio.to_thread(embedding_service().query, payload.query)
    values = search_memories(
        db,
        query=payload.query,
        meeting_ids=scope_meeting_ids(scope),
        project_id=scope.get("project_id"),
        time_from=payload.scope.time_from,
        time_to=payload.scope.time_to,
        kinds=payload.kinds,
        limit=payload.limit,
        query_embedding=vector,
    )
    return {"query": payload.query, "count": len(values), "memories": values}


@app.get("/v1/memory/timeline")
def cross_meeting_memory_timeline(
    db: Annotated[Session, Depends(get_db)],
    project_id: str | None = None,
    meeting_ids: list[UUID] | None = None,
) -> dict[str, Any]:
    return memory_timeline(db, meeting_ids=meeting_ids, project_id=project_id)


@app.get("/v1/graph/health")
async def graph_memory_health() -> dict[str, Any]:
    try:
        return await graph_health()
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={"status": "unavailable", "message": str(exc)},
        ) from exc


@app.get("/v1/graph/search")
async def search_memory_graph(
    query: str,
    project_id: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    if not query.strip():
        raise HTTPException(status_code=422, detail="query must not be blank")
    values = await graph_search(query, project_id=project_id, limit=min(max(limit, 1), 200))
    return {"query": query, "count": len(values), "results": values}


@app.get("/v1/meetings/{meeting_id}/graph")
async def meeting_memory_graph(
    meeting_id: UUID,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    if not get_meeting(db, meeting_id):
        raise HTTPException(status_code=404, detail="meeting not found")
    return await graph_for_meeting(str(meeting_id))


@app.post("/v1/conversations", status_code=status.HTTP_201_CREATED)
def new_conversation(
    payload: ConversationCreate,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    value = create_conversation(
        db,
        title=payload.title,
        scope=payload.scope.model_dump(mode="json"),
    )
    return {
        "id": str(value.id),
        "title": value.title,
        "scope": value.scope,
        "created_at": value.created_at.isoformat(),
    }


@app.get("/v1/conversations")
def conversations(db: Annotated[Session, Depends(get_db)]) -> list[dict[str, Any]]:
    return list_conversations(db)


@app.get("/v1/conversations/{conversation_id}")
def conversation_detail(
    conversation_id: UUID,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    value = get_conversation(db, conversation_id)
    if not value:
        raise HTTPException(status_code=404, detail="conversation not found")
    return {
        "id": str(value.id),
        "title": value.title,
        "scope": value.scope,
        "messages": conversation_messages(db, value.id),
    }


@app.post("/v1/conversations/{conversation_id}/messages")
async def ask_in_conversation(
    conversation_id: UUID,
    payload: ConversationAsk,
) -> dict[str, Any]:
    with SessionLocal() as db:
        conversation = get_conversation(db, conversation_id)
        if not conversation:
            raise HTTPException(status_code=404, detail="conversation not found")
        scope = conversation.scope
        history = conversation_messages(db, conversation.id)[-12:]
    request = AgentQuery(
        query=payload.content,
        scope=scope,
        limit=payload.limit,
        history=[
            {"role": item["role"], "content": item["content"]} for item in history
        ],
    )
    result = await run_agent(request)
    with SessionLocal() as db:
        conversation = get_conversation(db, conversation_id)
        if not conversation:
            raise HTTPException(status_code=404, detail="conversation not found")
        append_conversation_exchange(
            db,
            conversation,
            question=payload.content,
            response=result,
        )
    return {"conversation_id": str(conversation_id), **result}


@app.get("/v1/analytics/overview")
def analytics_overview(
    db: Annotated[Session, Depends(get_db)],
    project_id: str | None = None,
) -> dict[str, Any]:
    return overview(db, project_id)


@app.get("/v1/analytics/extractions")
def all_extraction_usage(
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    return extraction_stats(db)


@app.get("/v1/hera/outbox")
def hera_outbox_events(
    db: Annotated[Session, Depends(get_db)],
    limit: int = 100,
) -> dict[str, Any]:
    values = pending_events(
        db,
        tenant_id=current_tenant_id(),
        limit=min(max(limit, 1), 500),
    )
    return {"count": len(values), "events": values}


@app.post("/v1/hera/outbox/{event_id}/ack", status_code=status.HTTP_204_NO_CONTENT)
def acknowledge_hera_outbox_event(
    event_id: UUID,
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    if not acknowledge_event(
        db,
        event_id=event_id,
        tenant_id=current_tenant_id(),
        user_id=current_user_id(),
    ):
        raise HTTPException(status_code=404, detail="outbox event not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/v1/people")
def voiceprint_people(
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    values = list_people(db, tenant_id=current_tenant_id())
    return {"count": len(values), "people": values}


@app.post("/v1/voiceprints/enroll", status_code=status.HTTP_201_CREATED)
def enroll_speaker_voiceprint(
    payload: VoiceprintEnroll,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    try:
        return enroll_voiceprint(
            db,
            meeting_id=payload.meeting_id,
            speaker_id=payload.speaker_id,
            person_id=payload.person_id,
            display_name=payload.display_name,
            tenant_id=current_tenant_id(),
            user_id=current_user_id(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/v1/voiceprints/scan")
def scan_cross_meeting_voiceprints(
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    return match_tenant_speakers(db, tenant_id=current_tenant_id())


@app.get("/v1/voiceprints/candidates")
def voiceprint_candidates(
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    values = list_candidates(db, tenant_id=current_tenant_id())
    return {"count": len(values), "candidates": values}


@app.post("/v1/voiceprints/candidates/{candidate_id}/review")
def confirm_voiceprint_candidate(
    candidate_id: UUID,
    payload: CandidateReview,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    try:
        return review_candidate(
            db,
            candidate_id=candidate_id,
            accept=payload.accept,
            tenant_id=current_tenant_id(),
            user_id=current_user_id(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.delete("/v1/voiceprints/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_voiceprint_profile(
    profile_id: UUID,
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    if not delete_voiceprint_profile(
        db, profile_id=profile_id, tenant_id=current_tenant_id()
    ):
        raise HTTPException(status_code=404, detail="voiceprint profile not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.delete("/v1/people/{person_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_person_and_voiceprints(
    person_id: UUID,
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    if not delete_person(db, person_id=person_id, tenant_id=current_tenant_id()):
        raise HTTPException(status_code=404, detail="person not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/v1/meetings/{meeting_id}/extractions")
def meeting_extraction_usage(
    meeting_id: UUID,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    if not get_meeting(db, meeting_id):
        raise HTTPException(status_code=404, detail="meeting not found")
    return extraction_stats(db, meeting_id)


@app.get("/v1/meetings/{meeting_id}/pipeline-runs")
def pipeline_runs_for_meeting(
    meeting_id: UUID,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    if not get_meeting(db, meeting_id):
        raise HTTPException(status_code=404, detail="meeting not found")
    return {"meeting_id": str(meeting_id), "runs": meeting_pipeline_runs(db, meeting_id)}


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


@app.get("/v1/providers/audio/{meeting_id}", include_in_schema=False)
def provider_audio_download(
    meeting_id: UUID,
    expires: int,
    token: str,
    db: Annotated[Session, Depends(get_db)],
) -> StreamingResponse:
    if not verify_provider_audio_token(meeting_id, expires, token):
        raise HTTPException(status_code=403, detail="invalid or expired download token")
    meeting = get_meeting(db, meeting_id)
    selected_uri = (
        meeting.normalized_audio_uri if meeting else None
    ) or (meeting.audio_uri if meeting else None)
    if not meeting or not selected_uri or not selected_uri.startswith("minio://"):
        raise HTTPException(status_code=404, detail="audio not found")
    iterator, content_type, size = stream_object(parse_minio_uri(selected_uri))
    headers = {"Content-Length": str(size)} if size is not None else {}
    return StreamingResponse(
        iterator,
        media_type=content_type or "application/octet-stream",
        headers=headers,
    )
