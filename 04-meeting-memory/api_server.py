"""Small, offline-first HTTP service for the meeting-memory research baseline.

The service deliberately uses only Python's standard library.  It can use the
repository/service implementations in this directory when they are present,
but keeps a deterministic SQLite/rule based fallback so a checkout is useful
before optional providers are installed.  No network or hosted LLM is called.

Run from this directory::

    python api_server.py --host 127.0.0.1 --port 8080

The ``MEETING_MEMORY_DB`` environment variable selects the SQLite file (the
default is ``./meeting_memory.sqlite3``).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import queue
import re
import sqlite3
import sys
import threading
import time
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence
from urllib.parse import parse_qs, unquote, urlsplit


ROOT = Path(__file__).resolve().parent
# The baseline is intentionally dependency-free.  These paths make the HTTP
# entry point usable when launched from another working directory, while not
# importing or modifying provider/adapters code.
for _path in (ROOT, ROOT / "baseline", ROOT / "../llm-providers"):
    _path = _path.resolve()
    if _path.exists() and str(_path) not in sys.path:
        sys.path.insert(0, str(_path))


JsonObject = Dict[str, Any]


class APIError(Exception):
    """An expected client-facing error."""

    def __init__(self, status: int, message: str, *, details: Any | None = None) -> None:
        super().__init__(message)
        self.status = int(status)
        self.message = message
        self.details = details


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _json_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _as_nonempty_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise APIError(422, f"{field} must be a non-empty string")
    return value.strip()


def _validate_top_k(value: Any) -> int:
    if value is None:
        return 5
    if isinstance(value, bool):
        raise APIError(422, "top_k must be an integer between 1 and 50")
    if isinstance(value, float) and not value.is_integer():
        raise APIError(422, "top_k must be an integer between 1 and 50")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise APIError(422, "top_k must be an integer between 1 and 50") from exc
    if not 1 <= result <= 50:
        raise APIError(422, "top_k must be an integer between 1 and 50")
    return result


def normalize_transcript_bundle(payload: Mapping[str, Any]) -> tuple[JsonObject, list[JsonObject]]:
    """Validate and normalize the public TranscriptBundle shape.

    Both ``{"meeting": {...}, "segments": [...]}`` and the compact shape
    ``{"meeting_id": ..., "tenant_id": ..., "segments": [...]}`` are
    accepted.  Segment tenant/meeting identifiers may be omitted because the
    bundle is authoritative; when supplied they must agree with the bundle.
    """

    if not isinstance(payload, Mapping):
        raise APIError(400, "request body must be a JSON object")
    meeting_value = payload.get("meeting")
    if meeting_value is None:
        meeting: JsonObject = {
            key: deepcopy(value)
            for key, value in payload.items()
            if key not in {"segments", "idempotency_key", "bundle_version"}
        }
    elif isinstance(meeting_value, Mapping):
        meeting = dict(meeting_value)
        # Top-level identifiers are useful in clients that send a wrapped
        # meeting but still include the canonical bundle keys.
        for key in ("meeting_id", "tenant_id"):
            if key in payload and key not in meeting:
                meeting[key] = payload[key]
    else:
        raise APIError(422, "meeting must be a JSON object")
    meeting_id = _as_nonempty_text(meeting.get("meeting_id"), "meeting_id")
    tenant_id = _as_nonempty_text(meeting.get("tenant_id"), "tenant_id")
    meeting["meeting_id"] = meeting_id
    meeting["tenant_id"] = tenant_id

    segments_value = payload.get("segments")
    if not isinstance(segments_value, list) or not segments_value:
        raise APIError(422, "segments must be a non-empty JSON array")
    segments: list[JsonObject] = []
    seen_ids: set[str] = set()
    for index, raw_segment in enumerate(segments_value):
        if not isinstance(raw_segment, Mapping):
            raise APIError(422, f"segments[{index}] must be a JSON object")
        segment = dict(raw_segment)
        segment_id = _as_nonempty_text(segment.get("segment_id"), f"segments[{index}].segment_id")
        if segment_id in seen_ids:
            raise APIError(422, f"duplicate segment_id: {segment_id}")
        seen_ids.add(segment_id)
        segment_meeting_id = segment.get("meeting_id", meeting_id)
        if segment_meeting_id != meeting_id:
            raise APIError(422, f"segments[{index}].meeting_id must equal meeting_id")
        segment_tenant_id = segment.get("tenant_id", tenant_id)
        if segment_tenant_id != tenant_id:
            raise APIError(422, f"segments[{index}].tenant_id must equal tenant_id")
        segment["segment_id"] = segment_id
        segment["meeting_id"] = meeting_id
        segment["tenant_id"] = tenant_id
        speaker_id = _as_nonempty_text(segment.get("speaker_id"), f"segments[{index}].speaker_id")
        segment["speaker_id"] = speaker_id
        text_value = segment.get("text")
        if not isinstance(text_value, str) or not text_value.strip():
            raise APIError(422, f"segments[{index}].text must be a non-empty string")
        segment["text"] = text_value.strip()
        for field in ("start_ms", "end_ms"):
            value = segment.get(field)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise APIError(422, f"segments[{index}].{field} must be a number")
            if int(value) != value or value < 0:
                raise APIError(422, f"segments[{index}].{field} must be a non-negative integer")
            segment[field] = int(value)
        if segment["end_ms"] <= segment["start_ms"]:
            raise APIError(422, f"segments[{index}].end_ms must be greater than start_ms")
        # Overlap is valid for diarized meetings (cross-talk and two speakers
        # talking at once). Ordering is not a schema invariant.
        confidence = segment.get("confidence")
        if confidence is not None:
            if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
                raise APIError(422, f"segments[{index}].confidence must be a number")
            if not 0 <= float(confidence) <= 1:
                raise APIError(422, f"segments[{index}].confidence must be between 0 and 1")
            segment["confidence"] = float(confidence)
        else:
            # Confidence is a required TranscriptBundle field in the canonical
            # protocol.  ``None`` is retained for callers with unknown ASR
            # confidence, while an omitted value remains deterministic.
            segment["confidence"] = None
        segments.append(segment)
    return meeting, segments


class _FallbackRuleExtractor:
    """Deterministic offline extractor used only when the baseline is absent."""

    def extract(self, meeting: JsonObject, segments: Sequence[JsonObject]) -> JsonObject:
        claims: list[JsonObject] = []
        for segment in segments:
            text = str(segment.get("text", "")).strip()
            if not text:
                continue
            # Keep one evidence-backed claim per non-empty segment.  This is a
            # safe research fallback, not an assertion that a model understood
            # the text; production extraction belongs behind the service port.
            claims.append(
                {
                    "claim_id": f"{meeting['meeting_id']}:{segment['segment_id']}",
                    "tenant_id": meeting["tenant_id"],
                    "subject": meeting.get("title", meeting["meeting_id"]),
                    "predicate": "transcript_evidence",
                    "object": text,
                    "status": "active",
                    "valid_from": meeting.get("started_at"),
                    "valid_to": None,
                    "source_meeting_id": meeting["meeting_id"],
                    "evidence_segment_ids": [segment["segment_id"]],
                }
            )
        return {
            "artifact_id": f"{meeting['meeting_id']}:v1",
            "version": 1,
            "meeting_id": meeting["meeting_id"],
            "tenant_id": meeting["tenant_id"],
            "summary": "离线规则抽取：保留有证据的转写片段。",
            "claims": claims,
            "decisions": [],
            "action_items": [],
            "risks": [],
            "evidence_state": "supported" if claims else "empty",
        }


class _FallbackSQLiteRepository:
    """Thread-safe stdlib repository for a standalone API checkout."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path, check_same_thread=False, timeout=30)
        self.connection.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self.connection.execute("PRAGMA busy_timeout = 30000")
            if self.path != ":memory:":
                self.connection.execute("PRAGMA journal_mode = WAL")
            self.connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS meetings (
                    meeting_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS segments (
                    segment_id TEXT PRIMARY KEY, meeting_id TEXT NOT NULL,
                    tenant_id TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS artifacts (
                    meeting_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS claims (
                    claim_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, subject TEXT NOT NULL,
                    predicate TEXT NOT NULL, object_text TEXT NOT NULL, status TEXT NOT NULL,
                    valid_from TEXT, valid_to TEXT, payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_segments_tenant ON segments(tenant_id);
                CREATE INDEX IF NOT EXISTS idx_claims_tenant ON claims(tenant_id);
                """
            )
            self.connection.commit()

    @staticmethod
    def _encode(value: Mapping[str, Any]) -> str:
        return json.dumps(dict(value), ensure_ascii=False, sort_keys=True)

    @staticmethod
    def _decode(value: str) -> JsonObject:
        decoded = json.loads(value)
        if not isinstance(decoded, dict):
            raise ValueError("repository payload must be a JSON object")
        return decoded

    def ingest_meeting(
        self,
        meeting: JsonObject,
        segments: Sequence[JsonObject],
        *,
        extractor: Any | None = None,
    ) -> JsonObject:
        extractor = extractor or _FallbackRuleExtractor()
        artifact = extractor.extract(meeting, list(segments))
        if artifact.get("meeting_id") != meeting["meeting_id"] or artifact.get("tenant_id") != meeting["tenant_id"]:
            raise ValueError("extractor artifact must preserve meeting_id and tenant_id")
        with self._lock, self.connection:
            self.connection.execute(
                "INSERT OR REPLACE INTO meetings(meeting_id, tenant_id, payload) VALUES (?, ?, ?)",
                (meeting["meeting_id"], meeting["tenant_id"], self._encode(meeting)),
            )
            for segment in segments:
                self.connection.execute(
                    "INSERT OR REPLACE INTO segments(segment_id, meeting_id, tenant_id, payload) VALUES (?, ?, ?, ?)",
                    (segment["segment_id"], segment["meeting_id"], segment["tenant_id"], self._encode(segment)),
                )
            self.connection.execute(
                "INSERT OR REPLACE INTO artifacts(meeting_id, tenant_id, payload) VALUES (?, ?, ?)",
                (artifact["meeting_id"], artifact["tenant_id"], self._encode(artifact)),
            )
            for claim in artifact.get("claims", []):
                self.connection.execute(
                    """INSERT OR REPLACE INTO claims
                    (claim_id, tenant_id, subject, predicate, object_text, status, valid_from, valid_to, payload)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        claim["claim_id"], claim["tenant_id"], claim.get("subject", ""),
                        claim.get("predicate", ""), claim.get("object", ""), claim.get("status", "active"),
                        claim.get("valid_from"), claim.get("valid_to"), self._encode(claim),
                    ),
                )
        return artifact

    def _rows(self, sql: str, params: Sequence[Any] = ()) -> list[JsonObject]:
        with self._lock:
            return [self._decode(row[0]) for row in self.connection.execute(sql, tuple(params)).fetchall()]

    @property
    def meetings(self) -> dict[str, JsonObject]:
        with self._lock:
            rows = self.connection.execute("SELECT meeting_id, payload FROM meetings").fetchall()
            return {row["meeting_id"]: self._decode(row["payload"]) for row in rows}

    @property
    def segments(self) -> dict[str, JsonObject]:
        with self._lock:
            rows = self.connection.execute("SELECT segment_id, payload FROM segments").fetchall()
            return {row["segment_id"]: self._decode(row["payload"]) for row in rows}

    @property
    def artifacts(self) -> dict[str, JsonObject]:
        with self._lock:
            rows = self.connection.execute("SELECT meeting_id, payload FROM artifacts").fetchall()
            return {row["meeting_id"]: self._decode(row["payload"]) for row in rows}

    @property
    def claims(self) -> dict[str, JsonObject]:
        with self._lock:
            rows = self.connection.execute("SELECT claim_id, payload FROM claims").fetchall()
            return {row["claim_id"]: self._decode(row["payload"]) for row in rows}

    def visible_segments(self, tenant_id: str) -> list[JsonObject]:
        return self._rows("SELECT payload FROM segments WHERE tenant_id = ? ORDER BY meeting_id, segment_id", (tenant_id,))

    def visible_claims(self, tenant_id: str) -> list[JsonObject]:
        return self._rows("SELECT payload FROM claims WHERE tenant_id = ? ORDER BY claim_id", (tenant_id,))

    def visible_meetings(self, tenant_id: str) -> list[JsonObject]:
        return self._rows("SELECT payload FROM meetings WHERE tenant_id = ? ORDER BY meeting_id", (tenant_id,))

    def get_segment(self, segment_id: str) -> JsonObject | None:
        rows = self._rows("SELECT payload FROM segments WHERE segment_id = ? LIMIT 1", (segment_id,))
        return rows[0] if rows else None

    def upsert_claim(self, claim: JsonObject) -> None:
        """Persist one evidence-backed claim for compatibility with the baseline."""

        required = ("claim_id", "tenant_id")
        if any(not str(claim.get(key, "")).strip() for key in required):
            raise ValueError("claim_id and tenant_id are required")
        with self._lock, self.connection:
            self.connection.execute(
                """INSERT OR REPLACE INTO claims
                   (claim_id, tenant_id, subject, predicate, object_text, status,
                    valid_from, valid_to, payload)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    claim["claim_id"], claim["tenant_id"], claim.get("subject", ""),
                    claim.get("predicate", ""), claim.get("object", ""), claim.get("status", "active"),
                    claim.get("valid_from"), claim.get("valid_to"), self._encode(claim),
                ),
            )

    def get_meeting(self, meeting_id: str) -> JsonObject | None:
        rows = self._rows("SELECT payload FROM meetings WHERE meeting_id = ? LIMIT 1", (meeting_id,))
        return rows[0] if rows else None

    def close(self) -> None:
        with self._lock:
            self.connection.close()

    def __enter__(self) -> "_FallbackSQLiteRepository":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()


def _load_components(
    db_path: str,
    *,
    extractor: Any | None = None,
    repository: Any | None = None,
    service: Any | None = None,
) -> tuple[Any, Any, Any]:
    """Load baseline components, falling back to deterministic local ones."""

    repository_cls: Any = None
    extractor_cls: Any = None
    service_cls: Any = None
    try:
        from sqlite_repository import SQLiteRepository as repository_cls  # type: ignore
    except (ImportError, AttributeError):
        repository_cls = None
    try:
        from engine import FixtureRuleExtractor as extractor_cls  # type: ignore
    except (ImportError, AttributeError):
        extractor_cls = None
    try:
        from service import MeetingMemoryService as service_cls  # type: ignore
    except (ImportError, AttributeError):
        service_cls = None
    repository = repository or (repository_cls or _FallbackSQLiteRepository)(db_path)
    extractor = extractor or (extractor_cls or _FallbackRuleExtractor)()
    if service is not None:
        return repository, extractor, service
    if service_cls is not None:
        try:
            from retrievers import LexicalRetriever  # type: ignore
            retriever = LexicalRetriever(repository)
        except (ImportError, AttributeError, TypeError):
            retriever = None
        try:
            service = service_cls(extractor=extractor, repository=repository, retriever=retriever)
        except TypeError:
            try:
                service = service_cls(extractor, repository, retriever)
            except TypeError:
                service = service_cls(extractor=extractor, repository=repository)
    else:
        service = _FallbackService(extractor, repository)
    return repository, extractor, service


class _FallbackService:
    def __init__(self, extractor: Any, repository: Any) -> None:
        self.extractor = extractor
        self.repository = repository

    def ingest_meeting(self, meeting: JsonObject, segments: Sequence[JsonObject]) -> JsonObject:
        return self.repository.ingest_meeting(meeting, segments, extractor=self.extractor)

    def answer(self, question: str, tenant_id: str, query_type: str = "general", top_k: int = 5) -> JsonObject:
        del query_type
        q = question.casefold()
        segments = [s for s in self.repository.visible_segments(tenant_id) if any(token in s.get("text", "").casefold() for token in q.split())]
        claims = [c for c in self.repository.visible_claims(tenant_id) if any(token in json.dumps(c, ensure_ascii=False).casefold() for token in q.split())]
        segments = segments[:top_k]
        claims = claims[:top_k]
        if not segments and not claims:
            return {"answer": None, "no_answer": True, "claims": [], "citations": [], "retrieval_mode": "offline_lexical"}
        citations = [
            {
                "meeting_id": s["meeting_id"],
                "segment_id": s["segment_id"],
                "speaker_id": s.get("speaker_id"),
                "start_ms": s.get("start_ms"),
                "end_ms": s.get("end_ms"),
                "text": s.get("text", ""),
            }
            for s in segments
        ]
        answer = "；".join(c.get("object", "") for c in claims) or "；".join(s.get("text", "") for s in segments)
        return {"answer": answer, "no_answer": False, "claims": claims, "citations": citations, "retrieval_mode": "offline_lexical"}


class _ScopedRetriever:
    """Apply an explicit meeting scope without changing the base retriever."""

    def __init__(self, base: Any, repository: Any, meeting_ids: set[str]) -> None:
        self.base = base
        self.repository = repository
        self.meeting_ids = meeting_ids
        self.retrieval_mode = f"{getattr(base, 'retrieval_mode', 'custom')}+meeting_scope"

    def retrieve(self, question: str, tenant_id: str, query_type: str, top_k: int = 5) -> dict[str, list[JsonObject]]:
        visible_segments = self.repository.visible_segments(tenant_id)
        visible_claims = self.repository.visible_claims(tenant_id)
        result = self.base.retrieve(
            question,
            tenant_id,
            query_type,
            max(top_k, len(visible_segments) + len(visible_claims) + 1),
        )
        allowed_segment_ids = {
            segment.get("segment_id")
            for segment in visible_segments
            if segment.get("meeting_id") in self.meeting_ids
        }
        segments = [
            row for row in result.get("segments", [])
            if row.get("segment", {}).get("meeting_id") in self.meeting_ids
        ][:top_k]
        claims = [
            row for row in result.get("claims", [])
            if (
                row.get("claim", {}).get("source_meeting_id") in self.meeting_ids
                or any(
                    segment_id in allowed_segment_ids
                    for segment_id in row.get("claim", {}).get("evidence_segment_ids", [])
                )
            )
        ][:top_k]
        return {"segments": segments, "claims": claims}


class _CrossMeetingSummaryRetriever:
    """Recall one evidence representative from every visible meeting.

    A lexical top-k alone cannot answer a request such as "summarize the
    formal architecture across all meetings": one late meeting containing the
    exact phrase crowds out earlier evidence.  This deterministic expansion is
    deliberately narrow to ``cross_meeting_summary``.  A production semantic
    retriever/reranker can replace it without changing the API contract.
    """

    retrieval_mode = "offline_lexical_token_baseline+cross_meeting_broad"

    def __init__(self, base: Any, repository: Any) -> None:
        self.base = base
        self.repository = repository

    def retrieve(self, question: str, tenant_id: str, query_type: str, top_k: int = 5) -> dict[str, list[JsonObject]]:
        visible_segments = self.repository.visible_segments(tenant_id)
        visible_claims = self.repository.visible_claims(tenant_id)
        result = self.base.retrieve(
            question,
            tenant_id,
            query_type,
            max(top_k, len(visible_segments) + len(visible_claims) + 1),
        )
        rows_by_id = {
            row.get("segment", {}).get("segment_id"): row
            for row in result.get("segments", [])
            if row.get("segment", {}).get("segment_id")
        }
        score_fn = getattr(self.base, "score_fn", None)
        if not callable(score_fn):
            score_fn = lambda _question, _text: 0.0
        for meeting_id in sorted({segment.get("meeting_id") for segment in visible_segments}):
            candidates = [segment for segment in visible_segments if segment.get("meeting_id") == meeting_id]
            if not candidates:
                continue
            representative = max(candidates, key=lambda segment: score_fn(question, segment.get("text", "")))
            rows_by_id.setdefault(
                representative.get("segment_id"),
                {"score": float(score_fn(question, representative.get("text", ""))), "segment": representative},
            )
        segment_rows = sorted(rows_by_id.values(), key=lambda row: row.get("score", 0.0), reverse=True)
        claim_rows = list(result.get("claims", []))
        # Claims with no lexical hit remain useful evidence in a cross-meeting
        # summary; keep them after ranked hits, bounded by the caller's top_k.
        known_claim_ids = {row.get("claim", {}).get("claim_id") for row in claim_rows}
        for claim in visible_claims:
            if claim.get("claim_id") not in known_claim_ids:
                claim_rows.append({"score": 0.0, "claim": claim})
        return {
            "segments": segment_rows[: max(top_k, len({s.get('meeting_id') for s in visible_segments}))],
            "claims": claim_rows[:top_k],
        }


class _LocalMeetingExpansionRetriever:
    """Expand evidence after locating one likely meeting.

    A transcript question often names the topic in one segment and states the
    required schema/boundary in the next segment.  Pure global top-k drops that
    second piece.  This adapter first chooses a meeting, then returns its
    local evidence window.  Security queries get a small configurable lexical
    hint so tenant/permission terms outrank unrelated equal-score rows.
    """

    retrieval_mode = "offline_lexical_token_baseline+meeting_local_expansion"

    def __init__(self, base: Any, repository: Any, query_type: str) -> None:
        self.base = base
        self.repository = repository
        self.query_type = query_type

    def retrieve(self, question: str, tenant_id: str, query_type: str, top_k: int = 5) -> dict[str, list[JsonObject]]:
        visible_segments = self.repository.visible_segments(tenant_id)
        visible_claims = self.repository.visible_claims(tenant_id)
        result = self.base.retrieve(
            question,
            tenant_id,
            query_type,
            max(top_k, len(visible_segments) + len(visible_claims) + 1),
        )
        score_fn = getattr(self.base, "score_fn", None)
        if not callable(score_fn):
            score_fn = lambda _question, _text: 0.0
        if self.query_type == "security":
            hints = ("tenant_id", "tenant", "租户", "权限", "隔离", "泄漏", "删除")

            def score(segment: JsonObject) -> float:
                text = str(segment.get("text", "")).lower()
                hint_bonus = 0.2 * sum(1 for hint in hints if hint.lower() in text)
                return float(score_fn(question, text)) + hint_bonus
        else:

            def score(segment: JsonObject) -> float:
                return float(score_fn(question, segment.get("text", "")))

        grouped: dict[str, list[JsonObject]] = {}
        for segment in visible_segments:
            grouped.setdefault(str(segment.get("meeting_id", "")), []).append(segment)
        if not grouped:
            return result
        meeting_id = max(
            grouped,
            key=lambda current_id: max((score(segment) for segment in grouped[current_id]), default=0.0),
        )
        local_rows = [
            {"score": score(segment), "segment": segment}
            for segment in grouped[meeting_id]
        ]
        local_rows.sort(key=lambda row: row["score"], reverse=True)
        local_ids = {row["segment"]["segment_id"] for row in local_rows}
        global_rows = [
            row for row in result.get("segments", [])
            if row.get("segment", {}).get("segment_id") not in local_ids
        ]
        # Keep the local evidence window intact, then add a few global
        # candidates for context.  This is bounded by the public top_k.
        segments = (local_rows + global_rows)[:top_k]
        claims = [
            row for row in result.get("claims", [])
            if row.get("claim", {}).get("source_meeting_id") == meeting_id
        ]
        claims.extend(
            row for row in result.get("claims", [])
            if row not in claims
        )
        return {"segments": segments, "claims": claims[:top_k]}


class _PersistentJobStore:
    """Tiny SQLite-backed job/idempotency table independent of repository API."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._lock = threading.RLock()
        self._memory: dict[str, JsonObject] | None = {} if path == ":memory:" else None
        self._connection: sqlite3.Connection | None = None
        if self._memory is None:
            Path(path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
            self._connection = sqlite3.connect(path, check_same_thread=False, timeout=30)
            self._connection.row_factory = sqlite3.Row
            self._connection.execute("PRAGMA busy_timeout = 30000")
            self._connection.execute("PRAGMA journal_mode = WAL")
            self._connection.execute(
                """CREATE TABLE IF NOT EXISTS http_jobs (
                   job_id TEXT PRIMARY KEY, identity TEXT NOT NULL UNIQUE,
                   payload_hash TEXT NOT NULL, request_json TEXT NOT NULL,
                   meeting_id TEXT NOT NULL, tenant_id TEXT NOT NULL,
                   status TEXT NOT NULL, result_json TEXT, error TEXT,
                   created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                )"""
            )
            self._connection.commit()

    def _row_to_dict(self, row: Any) -> JsonObject:
        if isinstance(row, sqlite3.Row):
            item = dict(row)
        else:
            item = dict(row)
        for key in ("request_json", "result_json"):
            if item.get(key):
                try:
                    item[key] = json.loads(item[key])
                except (TypeError, ValueError):
                    pass
        item["request"] = item.pop("request_json", None)
        item["result"] = item.pop("result_json", None)
        return item

    def get(self, job_id: str) -> JsonObject | None:
        with self._lock:
            if self._memory is not None:
                value = self._memory.get(job_id)
                return deepcopy(value) if value else None
            assert self._connection is not None
            row = self._connection.execute("SELECT * FROM http_jobs WHERE job_id = ?", (job_id,)).fetchone()
            return self._row_to_dict(row) if row else None

    def find_identity(self, identity: str) -> JsonObject | None:
        with self._lock:
            if self._memory is not None:
                for value in self._memory.values():
                    if value.get("identity") == identity:
                        return deepcopy(value)
                return None
            assert self._connection is not None
            row = self._connection.execute("SELECT * FROM http_jobs WHERE identity = ?", (identity,)).fetchone()
            return self._row_to_dict(row) if row else None

    def find_meeting(self, tenant_id: str, meeting_id: str) -> JsonObject | None:
        """Find the newest idempotency record for one tenant/meeting."""

        with self._lock:
            if self._memory is not None:
                values = [
                    value for value in self._memory.values()
                    if value.get("tenant_id") == tenant_id and value.get("meeting_id") == meeting_id
                ]
                return deepcopy(values[-1]) if values else None
            assert self._connection is not None
            row = self._connection.execute(
                """SELECT * FROM http_jobs
                   WHERE tenant_id = ? AND meeting_id = ?
                   ORDER BY updated_at DESC LIMIT 1""",
                (tenant_id, meeting_id),
            ).fetchone()
            return self._row_to_dict(row) if row else None

    def save(self, value: JsonObject) -> None:
        with self._lock:
            if self._memory is not None:
                self._memory[value["job_id"]] = deepcopy(value)
                return
            assert self._connection is not None
            self._connection.execute(
                """INSERT OR REPLACE INTO http_jobs
                (job_id, identity, payload_hash, request_json, meeting_id, tenant_id,
                 status, result_json, error, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    value["job_id"], value["identity"], value["payload_hash"],
                    json.dumps(value.get("request"), ensure_ascii=False, sort_keys=True),
                    value["meeting_id"], value["tenant_id"], value["status"],
                    json.dumps(value.get("result"), ensure_ascii=False, sort_keys=True) if value.get("result") is not None else None,
                    value.get("error"), value["created_at"], value["updated_at"],
                ),
            )
            self._connection.commit()

    def recoverable(self) -> list[JsonObject]:
        with self._lock:
            if self._memory is not None:
                return []
            assert self._connection is not None
            rows = self._connection.execute("SELECT * FROM http_jobs WHERE status IN ('queued','running')").fetchall()
            return [self._row_to_dict(row) for row in rows]

    def close(self) -> None:
        with self._lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None


class _JobManager:
    def __init__(self, app: "MeetingMemoryApplication") -> None:
        self.app = app
        self.store = _PersistentJobStore(app.db_path)
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._lock = threading.RLock()
        self._worker = threading.Thread(target=self._run, name="meeting-memory-ingest", daemon=True)
        self._worker.start()
        for record in self.store.recoverable():
            self._queue.put(record["job_id"])

    def submit(self, bundle: JsonObject, *, idempotency_key: str | None) -> JsonObject:
        meeting, segments = normalize_transcript_bundle(bundle)
        canonical = {"meeting": meeting, "segments": segments}
        payload_hash = _json_hash(canonical)
        # Meeting identity is always idempotent.  An explicit key adds a stable
        # client request identity and is persisted across process restarts.
        explicit = idempotency_key.strip() if isinstance(idempotency_key, str) else ""
        if explicit and len(explicit) > 256:
            raise APIError(422, "Idempotency-Key is too long")
        identity = f"{meeting['tenant_id']}:{'key:' + explicit if explicit else 'meeting:' + meeting['meeting_id']}"
        with self._lock:
            previous_meeting = self.app.get_meeting(meeting["meeting_id"])
            if previous_meeting is not None and previous_meeting.get("tenant_id") != meeting["tenant_id"]:
                raise APIError(409, "meeting_id belongs to a different tenant")
            getter = getattr(self.app.repository, "get_segment", None)
            if callable(getter):
                for incoming_segment in segments:
                    try:
                        previous_segment = getter(incoming_segment["segment_id"])
                    except TypeError:
                        previous_segment = getter(meeting["tenant_id"], incoming_segment["segment_id"])
                    if previous_segment is not None:
                        previous_hash = _json_hash(previous_segment)
                        if previous_hash != _json_hash(incoming_segment):
                            raise APIError(409, f"segment_id already exists with a different payload: {incoming_segment['segment_id']}")
            existing = self.store.find_identity(identity)
            if existing is not None:
                if existing.get("payload_hash") != payload_hash:
                    raise APIError(409, "idempotency key was already used with a different payload")
                existing["_duplicate"] = True
                return existing
            # Also collapse a same-content retry sent with a different key.
            by_meeting = self.store.find_meeting(meeting["tenant_id"], meeting["meeting_id"])
            if by_meeting is not None:
                if by_meeting.get("payload_hash") != payload_hash:
                    raise APIError(409, "meeting_id already exists with a different payload")
                by_meeting["_duplicate"] = True
                return by_meeting
            now = _now()
            value: JsonObject = {
                "job_id": str(uuid.uuid4()), "identity": identity,
                "payload_hash": payload_hash, "request": canonical,
                "meeting_id": meeting["meeting_id"], "tenant_id": meeting["tenant_id"],
                "status": "queued", "result": None, "error": None,
                "created_at": now, "updated_at": now,
            }
            self.store.save(value)
            self._queue.put(value["job_id"])
            return value

    def get(self, job_id: str) -> JsonObject | None:
        return self.store.get(job_id)

    def _update(self, value: JsonObject, **changes: Any) -> None:
        value.update(changes)
        value["updated_at"] = _now()
        self.store.save(value)

    def _run(self) -> None:
        while True:
            job_id = self._queue.get()
            if job_id is None:
                self._queue.task_done()
                return
            record = self.store.get(job_id)
            if record is None:
                self._queue.task_done()
                continue
            try:
                self._update(record, status="running", error=None)
                request = record.get("request") or {}
                meeting, segments = normalize_transcript_bundle(request)
                started = time.perf_counter()
                artifact = self.app.ingest(meeting, segments)
                result = {
                    "artifact": artifact,
                    "metadata": {
                        "run_id": record["job_id"],
                        "input_sha256": record["payload_hash"],
                        "schema_version": "transcript-bundle-v1",
                        "extractor_version": "fixture-rule-v1",
                        "counts": {
                            "segments": len(segments),
                            "claims": len(artifact.get("claims", [])) if isinstance(artifact, Mapping) else 0,
                        },
                        "latency_ms": round((time.perf_counter() - started) * 1000, 3),
                    },
                }
                self._update(record, status="completed", result=result, error=None)
            except Exception as exc:  # worker must never die on one bad bundle
                self._update(record, status="failed", error=str(exc), result=None)
            finally:
                self._queue.task_done()

    def close(self) -> None:
        self._queue.put(None)
        self._worker.join(timeout=2)
        self.store.close()


class MeetingMemoryApplication:
    """Application object shared by the HTTP handlers and tests."""

    def __init__(
        self,
        db_path: str | Path | None = None,
        *,
        extractor: Any | None = None,
        repository: Any | None = None,
        service: Any | None = None,
    ) -> None:
        configured = str(db_path or os.environ.get("MEETING_MEMORY_DB", "meeting_memory.sqlite3"))
        self.db_path = configured
        self._lock = threading.RLock()
        self.repository, self.extractor, self.service = _load_components(
            configured,
            extractor=extractor,
            repository=repository,
            service=service,
        )
        self.jobs = _JobManager(self)

    def ingest(self, meeting: JsonObject, segments: Sequence[JsonObject]) -> JsonObject:
        with self._lock:
            method = getattr(self.service, "ingest_meeting", None)
            if callable(method):
                return method(meeting, list(segments))
            return self.repository.ingest_meeting(meeting, list(segments), extractor=self.extractor)

    def query(
        self,
        question: str,
        tenant_id: str,
        query_type: str,
        top_k: int,
        meeting_scope: set[str] | None = None,
    ) -> JsonObject:
        with self._lock:
            method = getattr(self.service, "answer", None)
            if not callable(method):
                result = _FallbackService(self.extractor, self.repository).answer(question, tenant_id, query_type, top_k)
                if meeting_scope:
                    result["meetings"] = [m for m in result.get("meetings", []) if m in meeting_scope]
                    result["citations"] = [c for c in result.get("citations", []) if c.get("meeting_id") in meeting_scope]
                return result
            if meeting_scope:
                answerer = getattr(self.service, "answerer", None)
                base_retriever = getattr(self.service, "retriever", None)
                if not callable(getattr(answerer, "answer", None)) or base_retriever is None:
                    raise APIError(422, "meeting_scope is not supported by the configured answerer")
                result = answerer.answer(
                    question,
                    tenant_id,
                    query_type,
                    top_k=top_k,
                        repository=self.repository,
                        retriever=_ScopedRetriever(base_retriever, self.repository, meeting_scope),
                    )
            elif query_type == "cross_meeting_summary":
                answerer = getattr(self.service, "answerer", None)
                base_retriever = getattr(self.service, "retriever", None)
                if not callable(getattr(answerer, "answer", None)) or base_retriever is None:
                    raise APIError(422, "cross_meeting_summary is not supported by the configured answerer")
                result = answerer.answer(
                    question,
                    tenant_id,
                    query_type,
                    top_k=top_k,
                    repository=self.repository,
                    retriever=_CrossMeetingSummaryRetriever(base_retriever, self.repository),
                )
            elif query_type in {"single_meeting", "security"}:
                answerer = getattr(self.service, "answerer", None)
                base_retriever = getattr(self.service, "retriever", None)
                if not callable(getattr(answerer, "answer", None)) or base_retriever is None:
                    raise APIError(422, f"{query_type} is not supported by the configured answerer")
                result = answerer.answer(
                    question,
                    tenant_id,
                    query_type,
                    top_k=top_k,
                    repository=self.repository,
                    retriever=_LocalMeetingExpansionRetriever(base_retriever, self.repository, query_type),
                )
            else:
                try:
                    result = method(question, tenant_id, query_type, top_k)
                except TypeError:
                    result = method(question=question, tenant_id=tenant_id, query_type=query_type, top_k=top_k)
            if not isinstance(result, Mapping):
                raise RuntimeError("MeetingMemoryService.answer must return a JSON object")
            normalized = dict(result)
            normalized.setdefault("claims", [])
            normalized.setdefault("citations", [])
            normalized.setdefault("no_answer", not bool(normalized.get("answer")))
            if normalized.get("no_answer"):
                normalized["answer"] = normalized.get("answer")
            else:
                normalized.setdefault("answer", "")
            return normalized

    def get_meeting(self, meeting_id: str, tenant_id: str | None = None) -> JsonObject | None:
        with self._lock:
            meeting: JsonObject | None = None
            getter = getattr(self.repository, "get_meeting", None)
            if callable(getter):
                try:
                    meeting = getter(meeting_id)
                except TypeError:
                    if tenant_id:
                        meeting = getter(tenant_id, meeting_id)
            if meeting is None:
                meetings = getattr(self.repository, "meetings", {})
                if isinstance(meetings, Mapping):
                    meeting = deepcopy(meetings.get(meeting_id))
            if not isinstance(meeting, Mapping):
                # PostgreSQL-style repositories expose tenant-scoped listing.
                if tenant_id and callable(getattr(self.repository, "visible_meetings", None)):
                    meeting = next((m for m in self.repository.visible_meetings(tenant_id) if m.get("meeting_id") == meeting_id), None)
            if not isinstance(meeting, Mapping):
                return None
            meeting = dict(meeting)
            if tenant_id and meeting.get("tenant_id") != tenant_id:
                return None
            actual_tenant = str(meeting.get("tenant_id", tenant_id or ""))
            if callable(getattr(self.repository, "visible_segments", None)):
                segments = [s for s in self.repository.visible_segments(actual_tenant) if s.get("meeting_id") == meeting_id]
            else:
                values = getattr(self.repository, "segments", {})
                segments = [dict(s) for s in values.values() if s.get("meeting_id") == meeting_id and s.get("tenant_id") == actual_tenant]
            artifact: JsonObject | None = None
            artifacts = getattr(self.repository, "artifacts", {})
            if isinstance(artifacts, Mapping):
                candidate = artifacts.get(meeting_id)
                if isinstance(candidate, Mapping) and candidate.get("tenant_id") == actual_tenant:
                    artifact = deepcopy(dict(candidate))
            result: JsonObject = dict(meeting)
            result.update({"meeting": meeting, "segments": segments, "artifact": artifact})
            return result

    def close(self) -> None:
        self.jobs.close()
        close = getattr(self.repository, "close", None)
        if callable(close):
            close()


def create_app(
    db_path: str | Path | None = None,
    *,
    extractor: Any | None = None,
    repository: Any | None = None,
    service: Any | None = None,
) -> MeetingMemoryApplication:
    """Create the HTTP application with optional injected core components.

    The default is the offline SQLite/rule baseline.  A caller can inject a
    validated LLM extractor, PostgreSQL repository, or complete service in
    tests/production without changing the HTTP contract.
    """

    return MeetingMemoryApplication(
        db_path,
        extractor=extractor,
        repository=repository,
        service=service,
    )


def _read_json(handler: BaseHTTPRequestHandler) -> Any:
    content_length = handler.headers.get("Content-Length")
    if content_length is None:
        raise APIError(411, "Content-Length is required")
    try:
        length = int(content_length)
    except ValueError as exc:
        raise APIError(400, "Content-Length must be an integer") from exc
    if length < 0 or length > 10 * 1024 * 1024:
        raise APIError(413, "request body is too large")
    raw = handler.rfile.read(length)
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise APIError(400, "request body must be valid UTF-8 JSON") from exc


def _send_json(handler: BaseHTTPRequestHandler, status: int, body: Any) -> None:
    encoded = json.dumps(body, ensure_ascii=False, sort_keys=True).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(encoded)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    if handler.command != "HEAD":
        handler.wfile.write(encoded)


def make_handler(app: MeetingMemoryApplication) -> type[BaseHTTPRequestHandler]:
    """Build a request handler bound to one application instance."""

    class Handler(BaseHTTPRequestHandler):
        server_version = "MeetingMemoryHTTP/0.1"
        protocol_version = "HTTP/1.1"

        def log_message(self, format: str, *args: Any) -> None:  # pragma: no cover - noisy by default
            if os.environ.get("MEETING_MEMORY_HTTP_LOG"):
                super().log_message(format, *args)

        def _error(self, exc: APIError) -> None:
            body: JsonObject = {"error": exc.message}
            if exc.details is not None:
                body["details"] = exc.details
            _send_json(self, exc.status, body)

        def do_GET(self) -> None:  # noqa: N802
            try:
                parsed = urlsplit(self.path)
                path = parsed.path.rstrip("/") or "/"
                if path == "/healthz":
                    _send_json(self, HTTPStatus.OK, {"status": "ok", "service": "meeting-memory", "version": "research"})
                    return
                match = re.fullmatch(r"/v1/jobs/([^/]+)", path)
                if match:
                    job = app.jobs.get(unquote(match.group(1)))
                    if job is None:
                        raise APIError(404, "job not found")
                    params = parse_qs(parsed.query)
                    tenant_values = params.get("tenant_id", [])
                    tenant_id = tenant_values[0] if tenant_values else self.headers.get("X-Tenant-ID")
                    if not tenant_id or tenant_id != job.get("tenant_id"):
                        raise APIError(404, "job not found")
                    # request/identity are useful for debugging but are not
                    # required by the public contract; keep result/error clear.
                    _send_json(self, HTTPStatus.OK, job)
                    return
                match = re.fullmatch(r"/v1/meetings/([^/]+)", path)
                if match:
                    params = parse_qs(parsed.query)
                    tenant_values = params.get("tenant_id", [])
                    tenant_id = tenant_values[0] if tenant_values else self.headers.get("X-Tenant-ID")
                    if not tenant_id:
                        raise APIError(400, "tenant_id query parameter or X-Tenant-ID header is required")
                    meeting = app.get_meeting(unquote(match.group(1)), tenant_id)
                    if meeting is None:
                        raise APIError(404, "meeting not found")
                    _send_json(self, HTTPStatus.OK, meeting)
                    return
                raise APIError(404, "route not found")
            except APIError as exc:
                self._error(exc)
            except Exception as exc:  # pragma: no cover - defensive server boundary
                self._error(APIError(500, "internal server error", details=str(exc)))

        def do_POST(self) -> None:  # noqa: N802
            try:
                parsed = urlsplit(self.path)
                path = parsed.path.rstrip("/") or "/"
                if path == "/v1/meetings":
                    payload = _read_json(self)
                    if not isinstance(payload, Mapping):
                        raise APIError(400, "request body must be a JSON object")
                    # Validate before touching the queue so malformed bundles
                    # never create a job that can only fail later.
                    meeting, segments = normalize_transcript_bundle(payload)
                    normalized = {"meeting": meeting, "segments": segments}
                    key = self.headers.get("Idempotency-Key") or payload.get("idempotency_key")
                    record = app.jobs.submit(normalized, idempotency_key=key)
                    _send_json(
                    self,
                        HTTPStatus.ACCEPTED,
                        {
                            "job_id": record["job_id"],
                            "meeting_id": record["meeting_id"],
                            "tenant_id": record["tenant_id"],
                            "status": record["status"],
                            "duplicate": bool(record.get("_duplicate", False)),
                        },
                    )
                    return
                if path == "/v1/query":
                    payload = _read_json(self)
                    if not isinstance(payload, Mapping):
                        raise APIError(400, "request body must be a JSON object")
                    tenant_id = _as_nonempty_text(payload.get("tenant_id"), "tenant_id")
                    question = _as_nonempty_text(payload.get("question"), "question")
                    query_type = payload.get("query_type", "general")
                    if "mode" in payload and "query_type" not in payload:
                        query_type = payload.get("mode")
                    query_type = _as_nonempty_text(query_type, "query_type")
                    top_k = _validate_top_k(payload.get("top_k"))
                    raw_scope = payload.get("meeting_scope")
                    if raw_scope is None:
                        meeting_scope = None
                    elif isinstance(raw_scope, str) and raw_scope.strip():
                        meeting_scope = {raw_scope.strip()}
                    elif (
                        isinstance(raw_scope, list)
                        and raw_scope
                        and all(isinstance(value, str) and value.strip() for value in raw_scope)
                    ):
                        meeting_scope = {value.strip() for value in raw_scope}
                    else:
                        raise APIError(422, "meeting_scope must be a meeting_id or non-empty string array")
                    result = app.query(question, tenant_id, query_type, top_k, meeting_scope)
                    # Keep the contract stable even if a provider returns extra
                    # metadata or omits optional fields.
                    response = dict(result)
                    response.setdefault("answer", None if response.get("no_answer") else "")
                    response.setdefault("no_answer", not bool(response.get("answer")))
                    response.setdefault("claims", [])
                    response.setdefault("citations", [])
                    _send_json(self, HTTPStatus.OK, response)
                    return
                raise APIError(404, "route not found")
            except APIError as exc:
                self._error(exc)
            except Exception as exc:  # pragma: no cover - defensive server boundary
                self._error(APIError(500, "internal server error", details=str(exc)))

    return Handler


class MeetingMemoryHTTPServer(ThreadingHTTPServer):
    """ThreadingHTTPServer carrying the application dependency."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        server_address: tuple[str, int],
        handler_cls: type[BaseHTTPRequestHandler] | None = None,
        *,
        app: MeetingMemoryApplication | None = None,
    ) -> None:
        self.app = app or create_app()
        super().__init__(server_address, handler_cls or make_handler(self.app))

    def server_close(self) -> None:
        try:
            super().server_close()
        finally:
            self.app.close()


def run_server(host: str = "127.0.0.1", port: int = 8080, db_path: str | Path | None = None) -> None:
    """Run the API until interrupted."""

    app = create_app(db_path)
    server = MeetingMemoryHTTPServer((host, int(port)), app=app)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="offline meeting-memory HTTP service")
    parser.add_argument("--host", default=os.environ.get("MEETING_MEMORY_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("MEETING_MEMORY_PORT", "8080")))
    parser.add_argument("--db", default=os.environ.get("MEETING_MEMORY_DB", "meeting_memory.sqlite3"))
    args = parser.parse_args(argv)
    run_server(args.host, args.port, args.db)
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised by smoke command
    raise SystemExit(main())
