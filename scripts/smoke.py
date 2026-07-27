#!/usr/bin/env python3
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:4200"
ROOT = Path(__file__).resolve().parents[1]


def request(method: str, path: str, payload: dict | None = None) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode() if payload else None
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=body,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read())


def main() -> None:
    print("health", request("GET", "/health"))
    meeting_ids = []
    for fixture_name in ("tingwu_meeting_01.json", "tingwu_meeting_02.json"):
        payload = json.loads((ROOT / "fixtures" / fixture_name).read_text(encoding="utf-8"))
        created = request("POST", "/v1/meetings/import/tingwu", payload)
        meeting_ids.append(created["id"])
        print("created", created["id"], created["title"])

    deadline = time.time() + 120
    while time.time() < deadline:
        states = [request("GET", f"/v1/meetings/{meeting_id}") for meeting_id in meeting_ids]
        if all(item["status"] == "READY" for item in states):
            break
        if any(item["status"] == "FAILED" for item in states):
            raise RuntimeError(states)
        time.sleep(2)
    else:
        raise TimeoutError("meetings did not become READY")

    search = request(
        "POST",
        "/v1/search",
        {
            "query": "OTA自动回滚",
            "meeting_ids": meeting_ids,
            "project_id": "k6",
            "limit": 20,
        },
    )
    assert search["meeting_count"] == 2, search
    print("search meetings", search["meeting_count"], "evidence", len(search["results"]))

    answer = request(
        "POST",
        "/v1/agent/query",
        {
            "query": "OTA发布日期为什么修改，谁负责后续任务？",
            "scope": {
                "mode": "selected_meetings",
                "meeting_ids": meeting_ids,
                "project_id": "k6",
            },
            "limit": 20,
        },
    )
    assert answer["meeting_count"] >= 1, answer
    assert answer["citations"], answer
    print("agent", answer["answer"])

    overview = request("GET", "/v1/analytics/overview?project_id=k6")
    assert overview["meeting_count"] >= 2, overview
    assert overview["top_keywords"], overview
    print("overview meetings", overview["meeting_count"])
    print("SMOKE_OK")


if __name__ == "__main__":
    try:
        main()
    except urllib.error.HTTPError as exc:
        print(exc.read().decode())
        raise
