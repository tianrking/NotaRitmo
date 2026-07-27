from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class MeetingCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    audio_url: HttpUrl
    project_id: str | None = None
    source_language: str = "cn"


class ImportedMeetingCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    project_id: str | None = None
    audio_uri: str | None = None
    source_language: str = "cn"
    raw_result: dict[str, Any]


class MeetingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    project_id: str | None
    status: str
    source_provider: str
    source_task_id: str | None
    source_language: str
    audio_uri: str | None
    duration_ms: int | None
    error: dict | None
    graph_status: str
    graph_indexed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    meeting_ids: list[UUID] = Field(default_factory=list)
    project_id: str | None = None
    limit: int = Field(default=20, ge=1, le=100)


class AgentScope(BaseModel):
    mode: Literal["current_meeting", "selected_meetings", "all_meetings"] = "all_meetings"
    meeting_id: UUID | None = None
    meeting_ids: list[UUID] = Field(default_factory=list)
    project_id: str | None = None
    time_from: datetime | None = None
    time_to: datetime | None = None


class AgentQuery(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    scope: AgentScope = Field(default_factory=AgentScope)
    limit: int = Field(default=16, ge=1, le=50)
    history: list[dict[str, str]] = Field(default_factory=list, max_length=20)


class AnalysisRequest(BaseModel):
    scope: AgentScope = Field(default_factory=AgentScope)
    focus: str | None = Field(default=None, max_length=1000)


class MemorySearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    scope: AgentScope = Field(default_factory=AgentScope)
    kinds: list[str] = Field(default_factory=list)
    limit: int = Field(default=30, ge=1, le=100)


class ConversationCreate(BaseModel):
    title: str = Field(default="新会议对话", min_length=1, max_length=500)
    scope: AgentScope = Field(default_factory=AgentScope)


class ConversationAsk(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    limit: int = Field(default=16, ge=1, le=50)


class TingwuCallback(BaseModel):
    model_config = ConfigDict(extra="allow")

    Code: str | int = "0"
    Data: dict[str, Any]
    Message: str | None = None
    RequestId: str | None = None
