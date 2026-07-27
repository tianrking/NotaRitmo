#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE = os.getenv("MEETING_API_BASE", "http://127.0.0.1:4200").rstrip("/")
ROOT = Path(__file__).resolve().parents[1]
REQUIRED_ARTIFACTS = {
    "summary",
    "detailed_summary",
    "chapters",
    "action_items",
    "decisions",
    "risks",
    "open_questions",
    "keywords",
    "wordcloud",
    "mindmap",
    "speaker_stats",
    "key_information",
}


def request(method: str, path: str, payload: dict | None = None) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=body,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=180) as response:
        return json.loads(response.read())


def wait_ready(meeting_id: str, timeout: int = 600) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        state = request("GET", f"/v1/meetings/{meeting_id}")
        if state["status"] == "READY" and state["graph_status"] == "READY":
            return state
        if state["status"] == "FAILED" or state["graph_status"] == "FAILED":
            raise RuntimeError(f"meeting processing failed: {state}")
        time.sleep(2)
    raise TimeoutError(f"meeting did not become fully READY: {meeting_id}")


def main() -> None:
    health = request("GET", "/health")
    graph_health = request("GET", "/v1/graph/health")
    assert health["status"] == "ok", health
    assert graph_health["status"] == "ready", graph_health
    print("services", health["service"], graph_health["backend"])

    meeting_ids: list[str] = []
    for index in range(1, 5):
        fixture_name = f"tingwu_meeting_{index:02d}.json"
        payload = json.loads((ROOT / "fixtures" / fixture_name).read_text(encoding="utf-8"))
        created = request("POST", "/v1/meetings/import/tingwu", payload)
        wait_ready(created["id"])
        meeting_ids.append(created["id"])
        report = request("GET", f"/v1/meetings/{created['id']}/report")
        assert report["transcript"], report
        assert all(segment["words"] for segment in report["transcript"]), report
        artifact_kinds = set(report["artifacts"])
        assert REQUIRED_ARTIFACTS <= artifact_kinds, REQUIRED_ARTIFACTS - artifact_kinds
        assert report["memories"], report
        assert all(memory["evidence_segment_ids"] for memory in report["memories"]), report
        graph = request("GET", f"/v1/meetings/{created['id']}/graph")
        assert graph["nodes"] and graph["edges"], graph
        print(
            "meeting",
            index,
            created["title"],
            len(report["transcript"]),
            "segments",
            len(report["memories"]),
            "memories",
        )

    search = request(
        "POST",
        "/v1/search",
        {
            "query": "设备掉线以后恢复连接",
            "meeting_ids": meeting_ids,
            "limit": 20,
        },
    )
    assert search["results"], search
    assert any(item["retrieval"] in {"hybrid", "semantic"} for item in search["results"]), search

    memory_search = request(
        "POST",
        "/v1/memory/search",
        {
            "query": "谁做兼容性和低电量测试",
            "scope": {"mode": "selected_meetings", "meeting_ids": meeting_ids},
            "kinds": ["action_item"],
            "limit": 30,
        },
    )
    assert memory_search["memories"], memory_search
    assert all(item["evidence"] for item in memory_search["memories"]), memory_search

    selected_analysis = request(
        "POST",
        "/v1/analysis",
        {"scope": {"mode": "selected_meetings", "meeting_ids": meeting_ids}},
    )
    assert selected_analysis["meeting_count"] == 4, selected_analysis
    assert selected_analysis["decisions"], selected_analysis
    assert selected_analysis["action_items"], selected_analysis
    assert selected_analysis["risks"], selected_analysis
    assert selected_analysis["open_questions"], selected_analysis
    assert selected_analysis["top_topics"], selected_analysis

    k6_analysis = request(
        "POST",
        "/v1/analysis",
        {"scope": {"mode": "all_meetings", "project_id": "k6"}},
    )
    assert k6_analysis["meeting_count"] == 3, k6_analysis
    assert k6_analysis["timeline"]["links"], k6_analysis["timeline"]

    answer = request(
        "POST",
        "/v1/agent/query",
        {
            "query": "K6最终采用什么发布方案，有哪些风险和谁负责后续任务？",
            "scope": {
                "mode": "selected_meetings",
                "meeting_ids": meeting_ids[:3],
                "project_id": "k6",
            },
            "limit": 30,
        },
    )
    assert answer["citations"], answer
    assert answer["verification"]["grounded"], answer
    assert not answer["verification"]["unresolved_memory_evidence"], answer

    conversation = request(
        "POST",
        "/v1/conversations",
        {
            "title": "四会议验收对话",
            "scope": {"mode": "selected_meetings", "meeting_ids": meeting_ids},
        },
    )
    first = request(
        "POST",
        f"/v1/conversations/{conversation['id']}/messages",
        {"content": "总结全部四场会议"},
    )
    second = request(
        "POST",
        f"/v1/conversations/{conversation['id']}/messages",
        {"content": "其中Android应该直接调用谁？"},
    )
    detail = request("GET", f"/v1/conversations/{conversation['id']}")
    assert first["answer"] and second["answer"], (first, second)
    assert len(detail["messages"]) == 4, detail
    assert second["citations"], second

    graph_query = urllib.parse.urlencode({"query": "灰度分包", "project_id": "k6"})
    graph_results = request("GET", f"/v1/graph/search?{graph_query}")
    assert graph_results["results"], graph_results

    ready = request("GET", "/ready")
    assert ready["counts"]["words"] >= 24, ready
    assert ready["counts"]["memories"] >= 20, ready
    print(
        "ACCEPTANCE_OK",
        json.dumps(
            {
                "meeting_ids": meeting_ids,
                "counts": ready["counts"],
                "cross_meeting_links": len(k6_analysis["timeline"]["links"]),
                "conversation_id": conversation["id"],
            },
            ensure_ascii=False,
        ),
    )


if __name__ == "__main__":
    try:
        main()
    except urllib.error.HTTPError as exc:
        print(exc.read().decode())
        raise
