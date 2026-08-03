"""Run the fixed ten-meeting fixture through the HTTP boundary.

This is intentionally a small, dependency-free acceptance harness.  It
measures the public API and storage/query behavior, not an external LLM's
language quality.  Run from ``04-meeting-memory`` with:

    python3 evaluation/run_http_dynamic.py
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api_server import MeetingMemoryHTTPServer, create_app  # noqa: E402


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((p / 100) * (len(ordered) - 1)))))
    return round(ordered[index], 3)


class Client:
    def __init__(self, server: MeetingMemoryHTTPServer) -> None:
        host, port = server.server_address
        self.base = f"http://{host}:{port}"

    def request(self, path: str, method: str = "GET", value: Any | None = None) -> tuple[int, dict[str, Any]]:
        raw = None if value is None else json.dumps(value, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.base + path,
            data=raw,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="dynamic HTTP evaluation for ten meeting fixture")
    parser.add_argument("--fixture-dir", type=Path, default=ROOT / "fixtures" / "meeting-memory-fixture-10")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    fixture_dir = args.fixture_dir.resolve()
    meetings = read_jsonl(fixture_dir / "meetings.jsonl")
    segments = read_jsonl(fixture_dir / "segments.jsonl")
    queries = read_jsonl(fixture_dir / "queries.jsonl")
    by_meeting: dict[str, list[dict[str, Any]]] = {}
    for segment in segments:
        by_meeting.setdefault(segment["meeting_id"], []).append(segment)

    with tempfile.TemporaryDirectory(prefix="meeting-memory-http-") as temporary:
        db_path = str(Path(temporary) / "meeting-memory.sqlite3")
        app = create_app(db_path)
        server = MeetingMemoryHTTPServer(("127.0.0.1", 0), app=app)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        client = Client(server)
        submit_ms: list[float] = []
        job_ms: list[float] = []
        query_ms: list[float] = []
        failed_jobs: list[str] = []
        try:
            health_status, health = client.request("/healthz")
            for meeting in meetings:
                bundle = {"meeting": meeting, "segments": by_meeting.get(meeting["meeting_id"], [])}
                started = time.perf_counter()
                status, created = client.request("/v1/meetings", "POST", bundle)
                submit_ms.append((time.perf_counter() - started) * 1000)
                if status != 202:
                    failed_jobs.append(f"{meeting['meeting_id']}:submit:{status}")
                    continue
                job_id = created["job_id"]
                started = time.perf_counter()
                while True:
                    job_status, job = client.request(
                        f"/v1/jobs/{job_id}?tenant_id={meeting['tenant_id']}"
                    )
                    if job_status != 200 or job.get("status") in {"completed", "failed"}:
                        break
                    time.sleep(0.01)
                job_ms.append((time.perf_counter() - started) * 1000)
                if job.get("status") != "completed":
                    failed_jobs.append(f"{meeting['meeting_id']}:{job.get('status')}:{job.get('error')}")

            query_rows: list[dict[str, Any]] = []
            for query in queries:
                started = time.perf_counter()
                status, result = client.request(
                    "/v1/query",
                    "POST",
                    {
                        "tenant_id": query["tenant_id"],
                        "question": query["question"],
                        "query_type": query["query_type"],
                        "top_k": 10,
                    },
                )
                query_ms.append((time.perf_counter() - started) * 1000)
                actual_meetings = set(result.get("meetings", []))
                expected_meetings = set(query.get("expected_meetings", []))
                actual_evidence = {row.get("segment_id") for row in result.get("citations", [])}
                expected_evidence = set(query.get("expected_evidence", []))
                citations_playable = all(
                    isinstance(row.get("meeting_id"), str)
                    and isinstance(row.get("segment_id"), str)
                    and isinstance(row.get("speaker_id"), str)
                    and isinstance(row.get("start_ms"), int)
                    and isinstance(row.get("end_ms"), int)
                    and row["end_ms"] > row["start_ms"]
                    for row in result.get("citations", [])
                )
                query_rows.append(
                    {
                        "query_id": query["query_id"],
                        "status": status,
                        "no_answer_correct": result.get("no_answer") == query.get("no_answer"),
                        "meeting_recall": (
                            len(actual_meetings & expected_meetings) / len(expected_meetings)
                            if expected_meetings else (1.0 if not actual_meetings else 0.0)
                        ),
                        "evidence_recall": (
                            len(actual_evidence & expected_evidence) / len(expected_evidence)
                            if expected_evidence else (1.0 if not actual_evidence else 0.0)
                        ),
                        "citations_playable": citations_playable,
                    }
                )

            # Deliberately query a different tenant with a known term.  Any
            # returned meeting/citation is a hard isolation failure.
            leak_status, leak = client.request(
                "/v1/query", "POST", {"tenant_id": "tenant_not_in_fixture", "question": "PostgreSQL"}
            )
            tenant_leak = bool(leak.get("meetings") or leak.get("citations") or leak.get("claims"))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

        # Reopen the same SQLite file in a fresh application to test durable
        # meeting/evidence state (the TemporaryDirectory remains alive).
        app2 = create_app(db_path)
        server2 = MeetingMemoryHTTPServer(("127.0.0.1", 0), app=app2)
        thread2 = threading.Thread(target=server2.serve_forever, daemon=True)
        thread2.start()
        try:
            restored_status, restored = Client(server2).request(
                "/v1/query",
                "POST",
                {"tenant_id": queries[0]["tenant_id"], "question": queries[0]["question"]},
            )
            restart_query_ok = restored_status == 200 and not restored.get("no_answer", True)
        finally:
            server2.shutdown()
            server2.server_close()
            thread2.join(timeout=3)

    no_answer_accuracy = sum(row["no_answer_correct"] for row in query_rows) / len(query_rows) if query_rows else 0.0
    meeting_recall = sum(row["meeting_recall"] for row in query_rows) / len(query_rows) if query_rows else 0.0
    evidence_recall = sum(row["evidence_recall"] for row in query_rows) / len(query_rows) if query_rows else 0.0
    report = {
        "mode": "http_dynamic_fixture",
        "fixture_meetings": len(meetings),
        "fixture_segments": len(segments),
        "fixture_queries": len(queries),
        "health": {"status": health_status, **health},
        "jobs": {"submitted": len(meetings), "completed": len(meetings) - len(failed_jobs), "failed": failed_jobs},
        "latency_ms": {
            "submit_p50": percentile(submit_ms, 50),
            "submit_p95": percentile(submit_ms, 95),
            "job_p50": percentile(job_ms, 50),
            "job_p95": percentile(job_ms, 95),
            "query_p50": percentile(query_ms, 50),
            "query_p95": percentile(query_ms, 95),
        },
        "quality": {
            "no_answer_accuracy": round(no_answer_accuracy, 6),
            "meeting_recall": round(meeting_recall, 6),
            "evidence_recall": round(evidence_recall, 6),
            "citation_playable_rate": round(
                sum(row["citations_playable"] for row in query_rows) / len(query_rows), 6
                if query_rows else 0.0
            ),
            "tenant_leak": tenant_leak,
            "tenant_probe_status": leak_status,
            "restart_query_ok": restart_query_ok,
        },
        "queries": query_rows,
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0 if not failed_jobs and not tenant_leak and restart_query_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
