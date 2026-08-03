from __future__ import annotations

import json
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from tempfile import TemporaryDirectory

from api_server import MeetingMemoryHTTPServer, create_app


class HTTPAPITests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.db = Path(self.tmp.name) / "memory.sqlite3"
        self.app = create_app(self.db)
        self.server = MeetingMemoryHTTPServer(("127.0.0.1", 0), app=self.app)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = "http://127.0.0.1:%d" % self.server.server_port

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def request(self, path, method="GET", value=None, headers=None):
        data = None if value is None else json.dumps(value, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.base + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json", **(headers or {})},
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def bundle(self):
        return {
            "meeting_id": "meeting_http_1",
            "tenant_id": "tenant_http",
            "title": "HTTP smoke",
            "segments": [
                {
                    "segment_id": "segment_http_1",
                    "speaker_id": "speaker_1",
                    "start_ms": 0,
                    "end_ms": 1000,
                    "text": "offline evidence",
                    "confidence": 1.0,
                }
            ],
        }

    def test_health_ingest_job_get_and_query(self):
        status, body = self.request("/healthz")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ok")
        status, created = self.request(
            "/v1/meetings", "POST", self.bundle(), {"Idempotency-Key": "http-test-1"}
        )
        self.assertEqual(status, 202)
        self.assertEqual(created["status"], "queued")
        job_id = created["job_id"]
        deadline = time.time() + 5
        while True:
            status, job = self.request("/v1/jobs/" + job_id + "?tenant_id=tenant_http")
            if job.get("status") in {"completed", "failed"} or time.time() >= deadline:
                break
            time.sleep(0.02)
        self.assertEqual(status, 200)
        self.assertEqual(job["status"], "completed")
        status, meeting = self.request("/v1/meetings/meeting_http_1?tenant_id=tenant_http")
        self.assertEqual(status, 200)
        self.assertEqual(meeting["tenant_id"], "tenant_http")
        self.assertEqual(len(meeting["segments"]), 1)
        status, answer = self.request(
            "/v1/query", "POST", {"tenant_id": "tenant_http", "question": "offline"}
        )
        self.assertEqual(status, 200)
        self.assertFalse(answer["no_answer"])
        self.assertTrue(answer["citations"])

    def test_idempotency_duplicate_and_validation(self):
        status, first = self.request(
            "/v1/meetings", "POST", self.bundle(), {"Idempotency-Key": "same"}
        )
        self.assertEqual(status, 202)
        status, second = self.request(
            "/v1/meetings", "POST", self.bundle(), {"Idempotency-Key": "same"}
        )
        self.assertEqual(status, 202)
        self.assertEqual(first["job_id"], second["job_id"])
        self.assertTrue(second["duplicate"])
        bad = self.bundle()
        bad["segments"].append(dict(bad["segments"][0]))
        status, error = self.request("/v1/meetings", "POST", bad)
        self.assertEqual(status, 422)
        self.assertIn("duplicate segment_id", error["error"])
        status, missing = self.request(
            "/v1/query", "POST", {"tenant_id": "another", "question": "offline"}
        )
        self.assertEqual(status, 200)
        self.assertTrue(missing["no_answer"])

    def test_scope_overlap_tenant_and_restart(self):
        first = self.bundle()
        first["meeting_id"] = "meeting_scope_1"
        first["segments"][0]["segment_id"] = "segment_scope_1"
        second = self.bundle()
        second["meeting_id"] = "meeting_scope_2"
        second["segments"][0]["segment_id"] = "segment_scope_2"
        second["segments"][0]["text"] = "offline evidence from the second meeting"
        for value in (first, second):
            status, created = self.request("/v1/meetings", "POST", value)
            self.assertEqual(status, 202)
            deadline = time.time() + 5
            while time.time() < deadline:
                _, job = self.request(
                    "/v1/jobs/" + created["job_id"] + "?tenant_id=tenant_http"
                )
                if job.get("status") in {"completed", "failed"}:
                    break
                time.sleep(0.02)
            self.assertEqual(job.get("status"), "completed")
        status, scoped = self.request(
            "/v1/query",
            "POST",
            {
                "tenant_id": "tenant_http",
                "meeting_scope": "meeting_scope_2",
                "question": "second meeting",
            },
        )
        self.assertEqual(status, 200)
        self.assertTrue(all(item["meeting_id"] == "meeting_scope_2" for item in scoped["citations"]))
        status, hidden = self.request(
            "/v1/meetings/meeting_scope_1?tenant_id=another_tenant"
        )
        self.assertEqual(status, 404)
        status, missing_tenant = self.request("/v1/meetings/meeting_scope_1")
        self.assertEqual(status, 400)

        # A diarizer may emit overlapping speaker segments; the API must not
        # reject that valid evidence shape.
        overlap = self.bundle()
        overlap["meeting_id"] = "meeting_overlap"
        overlap["segments"] = [
            {"segment_id": "overlap_a", "speaker_id": "speaker_1", "start_ms": 0,
             "end_ms": 1200, "text": "first voice"},
            {"segment_id": "overlap_b", "speaker_id": "speaker_2", "start_ms": 500,
             "end_ms": 1500, "text": "second voice"},
        ]
        status, _ = self.request("/v1/meetings", "POST", overlap)
        self.assertEqual(status, 202)

        # Restarting with the same DB keeps both evidence and queryability.
        db = self.db
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.app = create_app(db)
        self.server = MeetingMemoryHTTPServer(("127.0.0.1", 0), app=self.app)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = "http://127.0.0.1:%d" % self.server.server_port
        status, restored = self.request(
            "/v1/query", "POST", {"tenant_id": "tenant_http", "question": "offline evidence"}
        )
        self.assertEqual(status, 200)
        self.assertFalse(restored["no_answer"])


if __name__ == "__main__":
    unittest.main()
