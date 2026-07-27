from __future__ import annotations

import asyncio
from typing import Any, TypedDict
from uuid import UUID

from langgraph.graph import END, START, StateGraph

from app.db import SessionLocal
from app.repository import (
    save_query_audit,
    scoped_analysis,
    search_memories,
    search_segments,
)
from app.schemas import AgentQuery
from app.services.embeddings import embedding_service
from app.services.llm import LLMClient


class AgentState(TypedDict, total=False):
    query: str
    scope: dict[str, Any]
    limit: int
    history: list[dict[str, str]]
    intent: str
    segment_evidence: list[dict[str, Any]]
    memory_evidence: list[dict[str, Any]]
    analysis: dict[str, Any]
    answer: str
    verification: dict[str, Any]


def scope_meeting_ids(scope: dict[str, Any]) -> list[UUID]:
    values: list[UUID] = []
    if scope.get("meeting_id"):
        values.append(UUID(str(scope["meeting_id"])))
    values.extend(UUID(str(value)) for value in scope.get("meeting_ids") or [])
    return list(dict.fromkeys(values))


def _intent(query: str) -> str:
    rules = (
        ("overall_summary", ("所有会议", "全部会议", "整体总结", "跨会议总结", "几场会议总结")),
        ("meeting_summary", ("总结", "摘要", "讲了什么", "说了什么")),
        ("action_items", ("待办", "行动项", "谁负责", "任务", "截止")),
        ("decisions", ("决定", "决策", "结论", "最终方案")),
        ("risks", ("风险", "阻塞", "隐患")),
        ("open_questions", ("未决", "待确认", "问题", "还没定")),
        ("locate", ("哪场会议", "哪个会议", "找到会议", "定位会议")),
        ("timeline", ("变化", "时间线", "后来", "之前", "改为", "演进")),
    )
    for intent, markers in rules:
        if any(marker in query for marker in markers):
            return intent
    return "evidence_answer"


def _memory_citations(
    memories: list[dict[str, Any]], segments: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    segment_by_id = {item["segment_id"]: item for item in segments}
    citations = []
    seen = set()
    for memory in memories:
        for evidence in memory.get("evidence", []):
            segment_id = evidence["segment_id"]
            segment = segment_by_id.get(segment_id) or evidence
            if not segment or segment_id in seen:
                continue
            seen.add(segment_id)
            citations.append(
                {
                    "meeting_id": segment["meeting_id"],
                    "meeting_title": segment["meeting_title"],
                    "segment_id": segment_id,
                    "speaker_id": segment["speaker_id"],
                    "speaker_name": segment["speaker_name"],
                    "start_ms": segment["start_ms"],
                    "end_ms": segment["end_ms"],
                    "quote": segment["text"],
                    "score": memory.get("score", 0),
                    "source": f"memory:{memory['kind']}",
                }
            )
    return citations


def _deterministic_answer(state: AgentState) -> str:
    intent = state["intent"]
    analysis = state["analysis"]
    memories = state["memory_evidence"]
    segments = state["segment_evidence"]
    if intent in {"overall_summary", "meeting_summary"}:
        summaries = analysis["meetings"]
        if not summaries:
            return "当前范围内没有已完成的会议。"
        return "\n".join(
            f"{index + 1}. {item['title']}：{item['summary'] or '暂无摘要'}"
            for index, item in enumerate(summaries)
        )
    kind_by_intent = {
        "action_items": "action_item",
        "decisions": "decision",
        "risks": "risk",
        "open_questions": "open_question",
    }
    if intent in kind_by_intent:
        items = [item for item in memories if item["kind"] == kind_by_intent[intent]]
        if not items:
            items = analysis[intent]
        if not items:
            return "当前范围内没有找到对应的结构化会议记忆。"
        return "\n".join(
            f"{index + 1}. [{item['meeting_title']}] {item['content']}"
            + (f"（负责人：{item['subject']}）" if item.get("subject") else "")
            + f"；状态：{item['status']}"
            for index, item in enumerate(items[:30])
        )
    if intent == "timeline":
        events = analysis["timeline"]["events"]
        links = analysis["timeline"]["links"]
        if not events:
            return "当前范围内没有可用的会议记忆时间线。"
        return (
            "\n".join(
                f"{index + 1}. {item['meeting_created_at']} [{item['meeting_title']}] "
                f"{item['kind']}：{item['content']}（{item['status']}）"
                for index, item in enumerate(events[:40])
            )
            + f"\n共识别 {len(links)} 条跨会议关联。"
        )
    if intent == "locate":
        if not segments:
            return "没有找到包含相关内容的会议。"
        best: dict[str, dict[str, Any]] = {}
        for item in segments:
            current = best.get(item["meeting_id"])
            if current is None or item["score"] > current["score"]:
                best[item["meeting_id"]] = item
        return "\n".join(
            f"{index + 1}. {item['meeting_title']}，{item['speaker_name']} "
            f"在 {item['start_ms']}–{item['end_ms']}ms 提到：{item['text']}"
            for index, item in enumerate(best.values())
        )
    if not segments:
        return "在当前权限和查询范围内没有找到可验证的会议原文。"
    return "\n".join(
        f"{index + 1}. [{item['meeting_title']} · {item['speaker_name']} · "
        f"{item['start_ms']}–{item['end_ms']}ms] {item['text']}"
        for index, item in enumerate(segments[:12])
    )


async def run_agent(request: AgentQuery) -> dict[str, Any]:
    llm = LLMClient()

    def plan(state: AgentState) -> AgentState:
        return {"intent": _intent(state["query"])}

    async def retrieve(state: AgentState) -> AgentState:
        scope = state["scope"]
        prior_user = [
            item.get("content", "")
            for item in state.get("history", [])
            if item.get("role") == "user"
        ][-3:]
        retrieval_query = " ".join([*prior_user, state["query"]])
        vector = await asyncio.to_thread(embedding_service().query, retrieval_query)
        meeting_ids = scope_meeting_ids(scope)
        with SessionLocal() as db:
            segment_evidence = search_segments(
                db,
                query=retrieval_query,
                meeting_ids=meeting_ids,
                project_id=scope.get("project_id"),
                time_from=scope.get("time_from"),
                time_to=scope.get("time_to"),
                limit=state["limit"],
                query_embedding=vector,
            )
            memory_evidence = search_memories(
                db,
                query=retrieval_query,
                meeting_ids=meeting_ids,
                project_id=scope.get("project_id"),
                time_from=scope.get("time_from"),
                time_to=scope.get("time_to"),
                limit=state["limit"],
                query_embedding=vector,
            )
            analysis = scoped_analysis(
                db,
                meeting_ids=meeting_ids,
                project_id=scope.get("project_id"),
                time_from=scope.get("time_from"),
                time_to=scope.get("time_to"),
            )
        return {
            "segment_evidence": segment_evidence,
            "memory_evidence": memory_evidence,
            "analysis": analysis,
        }

    async def answer(state: AgentState) -> AgentState:
        deterministic = _deterministic_answer(state)
        context = {
            "intent": state["intent"],
            "analysis": state["analysis"],
            "memories": state["memory_evidence"],
            "segments": state["segment_evidence"],
            "conversation_history": state.get("history", []),
        }
        generated = await llm.answer_with_context(state["query"], context)
        return {"answer": generated or deterministic}

    def verify(state: AgentState) -> AgentState:
        segment_ids = {item["segment_id"] for item in state["segment_evidence"]}
        referenced = {
            segment_id
            for memory in state["memory_evidence"]
            for segment_id in memory["evidence_segment_ids"]
        }
        hydrated = {
            evidence["segment_id"]
            for memory in state["memory_evidence"]
            for evidence in memory.get("evidence", [])
        }
        grounded = not state["answer"] or bool(segment_ids or referenced or state["analysis"]["meetings"])
        return {
            "verification": {
                "grounded": grounded,
                "segment_evidence_count": len(segment_ids),
                "memory_evidence_count": len(state["memory_evidence"]),
                "unresolved_memory_evidence": sorted(referenced - segment_ids - hydrated),
                "policy": "answer-from-authorized-canonical-evidence-only",
            }
        }

    graph = StateGraph(AgentState)
    graph.add_node("plan", plan)
    graph.add_node("retrieve", retrieve)
    graph.add_node("answer", answer)
    graph.add_node("verify", verify)
    graph.add_edge(START, "plan")
    graph.add_edge("plan", "retrieve")
    graph.add_edge("retrieve", "answer")
    graph.add_edge("answer", "verify")
    graph.add_edge("verify", END)
    compiled = graph.compile()
    initial: AgentState = {
        "query": request.query,
        "scope": request.scope.model_dump(mode="json"),
        "limit": request.limit,
        "history": request.history,
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
            "source": "transcript",
        }
        for item in result["segment_evidence"]
    ]
    memory_citations = _memory_citations(
        result["memory_evidence"], result["segment_evidence"]
    )
    seen = {item["segment_id"] for item in citations}
    citations.extend(item for item in memory_citations if item["segment_id"] not in seen)
    response = {
        "answer": result["answer"],
        "intent": result["intent"],
        "meeting_count": len({item["meeting_id"] for item in citations}),
        "citations": citations,
        "memories": result["memory_evidence"],
        "verification": result["verification"],
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
