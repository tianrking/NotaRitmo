"""Standard-library SQLite repository for local Windows/WSL replacement tests."""

from __future__ import annotations

import json
import sqlite3
from threading import RLock
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Sequence


Json = Dict[str, Any]


class SQLiteRepository:
    """Repository-compatible local store.

    It is intentionally small and deterministic. PostgreSQL remains the
    production authority; this adapter proves that the service does not depend
    on Python dictionaries or a particular database implementation.
    """

    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        # The research HTTP entry point has a worker thread and request
        # threads.  Repository operations are serialized by this re-entrant
        # lock; check_same_thread is disabled only for this local adapter.
        self._lock = RLock()
        self.connection = sqlite3.connect(self.path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self._create_schema()

    def _create_schema(self) -> None:
        with self._lock:
            self.connection.executescript(
                """
            CREATE TABLE IF NOT EXISTS meetings (
                meeting_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS segments (
                segment_id TEXT PRIMARY KEY,
                meeting_id TEXT NOT NULL,
                tenant_id TEXT NOT NULL,
                payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS artifacts (
                meeting_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS claims (
                claim_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                subject TEXT NOT NULL,
                predicate TEXT NOT NULL,
                object_text TEXT NOT NULL,
                status TEXT NOT NULL,
                valid_from TEXT,
                valid_to TEXT,
                payload TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_segments_tenant ON segments(tenant_id);
            CREATE INDEX IF NOT EXISTS idx_claims_tenant_key
              ON claims(tenant_id, subject, predicate);
                """
            )
            self.connection.commit()

    @staticmethod
    def _encode(value: Json) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)

    @staticmethod
    def _decode(value: str) -> Json:
        result = json.loads(value)
        if not isinstance(result, dict):
            raise ValueError("repository payload must be a JSON object")
        return result

    @property
    def meetings(self) -> dict[str, Json]:
        with self._lock:
            return {
                row["meeting_id"]: self._decode(row["payload"])
                for row in self.connection.execute("SELECT meeting_id, payload FROM meetings")
            }

    @property
    def segments(self) -> dict[str, Json]:
        with self._lock:
            return {
                row["segment_id"]: self._decode(row["payload"])
                for row in self.connection.execute("SELECT segment_id, payload FROM segments")
            }

    @property
    def artifacts(self) -> dict[str, Json]:
        with self._lock:
            return {
                row["meeting_id"]: self._decode(row["payload"])
                for row in self.connection.execute("SELECT meeting_id, payload FROM artifacts")
            }

    @property
    def claims(self) -> dict[str, Json]:
        with self._lock:
            return {
                row["claim_id"]: self._decode(row["payload"])
                for row in self.connection.execute("SELECT claim_id, payload FROM claims")
            }

    def ingest_meeting(
        self,
        meeting: Json,
        segments: Sequence[Json],
        *,
        extractor: Any | None = None,
    ) -> Json:
        if extractor is None:
            raise ValueError("SQLiteRepository.ingest_meeting requires an extractor")
        with self._lock:
            artifact = extractor.extract(meeting, list(segments))
            with self.connection:
                self.connection.execute(
                    "INSERT OR REPLACE INTO meetings(meeting_id, tenant_id, payload) VALUES (?, ?, ?)",
                    (meeting["meeting_id"], meeting["tenant_id"], self._encode(meeting)),
                )
                for segment in segments:
                    self.connection.execute(
                        "INSERT OR REPLACE INTO segments(segment_id, meeting_id, tenant_id, payload) VALUES (?, ?, ?, ?)",
                        (
                            segment["segment_id"],
                            segment["meeting_id"],
                            segment["tenant_id"],
                            self._encode(segment),
                        ),
                    )
                self.connection.execute(
                    "INSERT OR REPLACE INTO artifacts(meeting_id, tenant_id, payload) VALUES (?, ?, ?)",
                    (artifact["meeting_id"], artifact["tenant_id"], self._encode(artifact)),
                )
                for claim in artifact.get("claims", []):
                    self._upsert_claim(claim)
        return artifact

    def _upsert_claim(self, claim: Json) -> None:
        incoming = deepcopy(claim)
        previous_row = self.connection.execute(
            """SELECT claim_id, object_text, status, payload FROM claims
               WHERE tenant_id = ? AND subject = ? AND predicate = ? AND status = 'active'
               ORDER BY rowid DESC LIMIT 1""",
            (incoming["tenant_id"], incoming["subject"], incoming["predicate"]),
        ).fetchone()
        if previous_row and previous_row["claim_id"] != incoming["claim_id"]:
            previous = self._decode(previous_row["payload"])
            if previous["object"] != incoming["object"] and previous["status"] == "active":
                previous["status"] = "superseded"
                previous["valid_to"] = incoming.get("valid_from")
                previous["superseded_by"] = incoming["claim_id"]
                incoming["supersedes"] = previous["claim_id"]
                self.connection.execute(
                    "UPDATE claims SET status = ?, valid_to = ?, payload = ? WHERE claim_id = ?",
                    ("superseded", previous.get("valid_to"), self._encode(previous), previous["claim_id"]),
                )
        self.connection.execute(
            """INSERT OR REPLACE INTO claims
               (claim_id, tenant_id, subject, predicate, object_text, status, valid_from, valid_to, payload)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                incoming["claim_id"],
                incoming["tenant_id"],
                incoming["subject"],
                incoming["predicate"],
                incoming["object"],
                incoming.get("status", "active"),
                incoming.get("valid_from"),
                incoming.get("valid_to"),
                self._encode(incoming),
            ),
        )

    def upsert_claim(self, claim: Json) -> None:
        with self._lock:
            with self.connection:
                self._upsert_claim(claim)

    def visible_segments(self, tenant_id: str) -> list[Json]:
        with self._lock:
            return [
                self._decode(row["payload"])
                for row in self.connection.execute(
                    "SELECT payload FROM segments WHERE tenant_id = ?", (tenant_id,)
                )
            ]

    def visible_claims(self, tenant_id: str) -> list[Json]:
        with self._lock:
            return [
                self._decode(row["payload"])
                for row in self.connection.execute(
                    "SELECT payload FROM claims WHERE tenant_id = ?", (tenant_id,)
                )
            ]

    def get_segment(self, segment_id: str) -> Json | None:
        with self._lock:
            row = self.connection.execute(
                "SELECT payload FROM segments WHERE segment_id = ?", (segment_id,)
            ).fetchone()
            return self._decode(row["payload"]) if row else None

    def close(self) -> None:
        with self._lock:
            self.connection.close()

    def __enter__(self) -> "SQLiteRepository":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()
