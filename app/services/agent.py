from __future__ import annotations

from typing import Any, TypedDict
from uuid import UUID

from langgraph.graph import END, START, StateGraph

from app.db import SessionLocal
from app.repository import save_query_audit, search_segments
from app.schemas import AgentQuery
from app.services.llm import LLMClient


class AgentState(TypedDict, total=False):
    query: str
    scope: dict[str, Any]
    limit: int
    evidence: list[dict[str, Any]]
    answer: str


def _scope_meeting_ids(scope: dict[str, Any]) -> list[UUID]:
    values: list[UUID] = []
    if scope.get("meeting_id"):
        values.append(UUID(str(scope["meeting_id"])))
    values.extend(UUID(str(value)) for value in scope.get("meeting_ids") or [])
    return list(dict.fromkeys(values))


async def run_agent(request: AgentQuery) -> dict[str, Any]:
    llm = LLMClient()

    def retrieve(state: AgentState) -> AgentState:
        scope = state["scope"]
        with SessionLocal() as db:
            evidence = search_segments(
                db,
                query=state["query"],
                meeting_ids=_scope_meeting_ids(scope),
                project_id=scope.get("project_id"),
                time_from=scope.get("time_from"),
                time_to=scope.get("time_to"),
                limit=state["limit"],
            )
        return {"evidence": evidence}

    async def answer(state: AgentState) -> AgentState:
        evidence = state.get("evidence", [])
        generated = await llm.answer(state["query"], evidence)
        if generated:
            return {"answer": generated}
        meeting_count = len({item["meeting_id"] for item in evidence})
        if not evidence:
            text = "在当前权限和查询范围内没有找到可验证的会议原文。"
        else:
            excerpts = "；".join(item["text"] for item in evidence[:5])
            text = (
                f"找到 {len(evidence)} 条原文证据，涉及 {meeting_count} 场会议。"
                f"当前未配置通用文本模型，先返回证据摘要：{excerpts}"
            )
        return {"answer": text}

    graph = StateGraph(AgentState)
    graph.add_node("retrieve", retrieve)
    graph.add_node("answer", answer)
    graph.add_edge(START, "retrieve")
    graph.add_edge("retrieve", "answer")
    graph.add_edge("answer", END)
    compiled = graph.compile()

    initial: AgentState = {
        "query": request.query,
        "scope": request.scope.model_dump(mode="json"),
        "limit": request.limit,
    }
    result = await compiled.ainvoke(initial)
    citations = [
        {
            "meeting_id": item["meeting_id"],
            "meeting_title": item["meeting_title"],
            "segment_id": item["segment_id"],
            "speaker_id": item["speaker_id"],
            "speaker_name": item["speaker_name"],
            "start_ms": item["start_ms"],
            "end_ms": item["end_ms"],
            "quote": item["text"],
            "score": item["score"],
        }
        for item in result.get("evidence", [])
    ]
    response = {
        "answer": result["answer"],
        "meeting_count": len({item["meeting_id"] for item in citations}),
        "citations": citations,
        "mode": request.scope.mode,
        "llm_used": llm.enabled,
    }
    with SessionLocal() as db:
        save_query_audit(
            db,
            request.query,
            request.scope.model_dump(mode="json"),
            response,
        )
    return response

