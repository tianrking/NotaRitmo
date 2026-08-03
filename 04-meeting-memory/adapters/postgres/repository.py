"""Optional psycopg 3 Repository for production meeting memory.

This adapter intentionally does not provide an in-memory fallback.  The
baseline's SQLiteRepository is the explicit local substitute.  A missing
driver, a missing tenant context, or an invalid production timestamp should
fail loudly rather than silently changing the authority boundary.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Sequence


Json = dict[str, Any]
ConnectionFactory = Callable[[str], Any]


class PostgresDependencyError(RuntimeError):
    """Raised when the optional psycopg 3 dependency is not installed."""


class PostgreSQLRepository:
    """Repository-compatible PostgreSQL authority.

    ``connection`` and ``connection_factory`` exist for contract tests and
    controlled dependency injection.  Normal production construction uses a
    psycopg 3 connection from ``dsn``.  The caller must use a database role
    that is subject to RLS; never connect as an Owner/BYPASSRLS role.
    """

    def __init__(
        self,
        dsn: str | None = None,
        *,
        connection: Any | None = None,
        connection_factory: ConnectionFactory | None = None,
    ) -> None:
        if connection is not None:
            self.connection = connection
            return
        if not dsn:
            raise ValueError("PostgreSQLRepository requires a DATABASE_URL/DSN")
        if connection_factory is None:
            try:
                import psycopg
            except ImportError as exc:  # pragma: no cover - environment dependent
                raise PostgresDependencyError(
                    "psycopg 3 is not installed; install 'psycopg[binary]' "
                    "only when PostgreSQL is available. Use SQLiteRepository "
                    "for the offline baseline."
                ) from exc
            connection_factory = psycopg.connect
        self.connection = connection_factory(dsn)

    @staticmethod
    def _encode(value: Mapping[str, Any]) -> str:
        return json.dumps(dict(value), ensure_ascii=False, sort_keys=True)

    @staticmethod
    def _encode_json(value: Any) -> str:
        """Encode any JSON value, including the ASR words array."""

        return json.dumps(value, ensure_ascii=False, sort_keys=True)

    @staticmethod
    def _decode(value: Any) -> Json:
        if isinstance(value, str):
            value = json.loads(value)
        if not isinstance(value, dict):
            raise ValueError("PostgreSQL payload must be a JSON object")
        return dict(value)

    @staticmethod
    def _timestamp(value: Any, field: str) -> datetime | None:
        if value in (None, ""):
            return None
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError(
                    f"{field} must be an ISO-8601 timestamp in the PostgreSQL adapter; "
                    f"got {value!r}"
                ) from exc
        raise TypeError(f"{field} must be datetime, ISO string, or null")

    @staticmethod
    def _require_tenant(record: Mapping[str, Any]) -> str:
        tenant_id = str(record.get("tenant_id", "")).strip()
        if not tenant_id:
            raise ValueError("tenant_id is required for PostgreSQL writes")
        return tenant_id

    @contextmanager
    def _transaction_for_tenant(self, tenant_id: str) -> Iterator[Any]:
        """Open a transaction and set the RLS tenant for its lifetime."""

        if not str(tenant_id).strip():
            raise ValueError("tenant_id is required for PostgreSQL access")
        transaction = getattr(self.connection, "transaction", None)
        if transaction is None:  # pragma: no cover - only non-psycopg fakes
            raise TypeError("connection must expose psycopg 3 transaction()")
        with transaction():
            with self.connection.cursor() as cursor:
                cursor.execute(
                    "SELECT set_config('app.tenant_id', %s, true)",
                    (tenant_id,),
                )
            yield self.connection

    def _execute_json_list(self, tenant_id: str, sql: str, params: Sequence[Any]) -> list[Json]:
        with self._transaction_for_tenant(tenant_id):
            with self.connection.cursor() as cursor:
                cursor.execute(sql, tuple(params))
                rows = cursor.fetchall()
        return [self._decode(row[0]) for row in rows]

    def ingest_meeting(
        self,
        meeting: Json,
        segments: Sequence[Json],
        *,
        extractor: Any | None = None,
    ) -> Json:
        if extractor is None:
            raise ValueError("PostgreSQLRepository.ingest_meeting requires an extractor")
        tenant_id = self._require_tenant(meeting)
        meeting_id = str(meeting.get("meeting_id", "")).strip()
        if not meeting_id:
            raise ValueError("meeting_id is required")
        artifact = extractor.extract(meeting, list(segments))
        artifact_tenant = self._require_tenant(artifact)
        if artifact_tenant != tenant_id or artifact.get("meeting_id") != meeting_id:
            raise ValueError("extractor artifact must preserve meeting_id and tenant_id")
        version = int(artifact.get("version", artifact.get("artifact_version", 1)))
        artifact_id = str(artifact.get("artifact_id", f"{meeting_id}:v{version}"))

        with self._transaction_for_tenant(tenant_id):
            with self.connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO meetings (tenant_id, meeting_id, title, started_at,
                                          ended_at, payload)
                    VALUES (%s, %s, %s, %s, %s, %s::jsonb)
                    ON CONFLICT (tenant_id, meeting_id) DO UPDATE SET
                      title = EXCLUDED.title,
                      started_at = EXCLUDED.started_at,
                      ended_at = EXCLUDED.ended_at,
                      payload = EXCLUDED.payload,
                      updated_at = now()
                    """,
                    (
                        tenant_id,
                        meeting_id,
                        meeting.get("title"),
                        self._timestamp(meeting.get("started_at"), "started_at"),
                        self._timestamp(meeting.get("ended_at"), "ended_at"),
                        self._encode(meeting),
                    ),
                )
                for segment in segments:
                    if self._require_tenant(segment) != tenant_id:
                        raise ValueError("all segments must belong to the meeting tenant")
                    if segment.get("meeting_id") != meeting_id:
                        raise ValueError("all segments must reference the meeting")
                    cursor.execute(
                        """
                        INSERT INTO segments (tenant_id, segment_id, meeting_id, speaker_id,
                                              start_ms, end_ms, text, confidence, words, payload)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb)
                        ON CONFLICT (tenant_id, segment_id) DO UPDATE SET
                          meeting_id = EXCLUDED.meeting_id,
                          speaker_id = EXCLUDED.speaker_id,
                          start_ms = EXCLUDED.start_ms,
                          end_ms = EXCLUDED.end_ms,
                          text = EXCLUDED.text,
                          confidence = EXCLUDED.confidence,
                          words = EXCLUDED.words,
                          payload = EXCLUDED.payload,
                          updated_at = now()
                        """,
                        (
                            tenant_id,
                            segment["segment_id"],
                            meeting_id,
                            segment.get("speaker_id"),
                            int(segment.get("start_ms", 0)),
                            int(segment.get("end_ms", 0)),
                            str(segment.get("text", "")),
                            segment.get("confidence"),
                            self._encode_json(segment.get("words", [])),
                            self._encode(segment),
                        ),
                    )
                cursor.execute(
                    """
                    INSERT INTO artifacts (tenant_id, artifact_id, meeting_id, version, payload)
                    VALUES (%s, %s, %s, %s, %s::jsonb)
                    ON CONFLICT (tenant_id, artifact_id) DO UPDATE SET
                      meeting_id = EXCLUDED.meeting_id,
                      version = EXCLUDED.version,
                      payload = EXCLUDED.payload,
                      updated_at = now()
                    """,
                    (tenant_id, artifact_id, meeting_id, version, self._encode(artifact)),
                )
                for claim in artifact.get("claims", []):
                    self._upsert_claim_cursor(cursor, tenant_id, claim, meeting_id)
        return artifact

    def _upsert_claim_cursor(
        self,
        cursor: Any,
        tenant_id: str,
        claim: Mapping[str, Any],
        source_meeting_id: str | None = None,
    ) -> None:
        incoming = dict(claim)
        if self._require_tenant(incoming) != tenant_id:
            raise ValueError("claim tenant_id does not match transaction tenant")
        claim_id = str(incoming.get("claim_id", "")).strip()
        if not claim_id:
            raise ValueError("claim_id is required")
        source_meeting_id = str(
            incoming.get("source_meeting_id", source_meeting_id or "")
        ).strip()
        if not source_meeting_id:
            raise ValueError("source_meeting_id is required for a production claim")
        status = str(incoming.get("status", "active"))
        if status not in {"active", "superseded", "disputed", "retracted"}:
            raise ValueError(f"unsupported claim status: {status}")
        cursor.execute(
            """
            SELECT claim_id, object_text, payload
            FROM claims
            WHERE tenant_id = %s AND subject = %s AND predicate = %s AND status = 'active'
            ORDER BY created_at DESC
            LIMIT 1
            FOR UPDATE
            """,
            (tenant_id, incoming.get("subject", ""), incoming.get("predicate", "")),
        )
        previous_row = cursor.fetchone()
        if previous_row and previous_row[0] != claim_id and previous_row[1] != incoming.get("object"):
            previous = self._decode(previous_row[2])
            previous["status"] = "superseded"
            previous["valid_to"] = incoming.get("valid_from")
            previous["superseded_by"] = claim_id
            incoming.setdefault("supersedes", previous_row[0])
            cursor.execute(
                """
                UPDATE claims SET status = 'superseded', valid_to = %s,
                    superseded_by = %s, payload = %s::jsonb, updated_at = now()
                WHERE tenant_id = %s AND claim_id = %s
                """,
                (
                    self._timestamp(incoming.get("valid_from"), "valid_from"),
                    claim_id,
                    self._encode(previous),
                    tenant_id,
                    previous_row[0],
                ),
            )
        cursor.execute(
            """
            INSERT INTO claims (tenant_id, claim_id, source_meeting_id, state_slot_id,
                                subject, predicate, object_text, status, review_state,
                                evidence_state, valid_from, valid_to, superseded_by, payload)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            ON CONFLICT (tenant_id, claim_id) DO UPDATE SET
              source_meeting_id = EXCLUDED.source_meeting_id,
              state_slot_id = EXCLUDED.state_slot_id,
              subject = EXCLUDED.subject,
              predicate = EXCLUDED.predicate,
              object_text = EXCLUDED.object_text,
              status = EXCLUDED.status,
              review_state = EXCLUDED.review_state,
              evidence_state = EXCLUDED.evidence_state,
              valid_from = EXCLUDED.valid_from,
              valid_to = EXCLUDED.valid_to,
              superseded_by = EXCLUDED.superseded_by,
              payload = EXCLUDED.payload,
              updated_at = now()
            """,
            (
                tenant_id,
                claim_id,
                source_meeting_id,
                incoming.get("state_slot_id"),
                str(incoming.get("subject", "")),
                str(incoming.get("predicate", "")),
                str(incoming.get("object", "")),
                status,
                str(incoming.get("review_state", "candidate")),
                str(incoming.get("evidence_state", "supported")),
                self._timestamp(incoming.get("valid_from"), "valid_from"),
                self._timestamp(incoming.get("valid_to"), "valid_to"),
                incoming.get("superseded_by"),
                self._encode(incoming),
            ),
        )
        for evidence_id in incoming.get("evidence_segment_ids", incoming.get("evidence_ids", [])):
            cursor.execute(
                """
                INSERT INTO claim_evidence (tenant_id, claim_id, segment_id)
                VALUES (%s, %s, %s)
                ON CONFLICT DO NOTHING
                """,
                (tenant_id, claim_id, evidence_id),
            )

    def upsert_claim(self, claim: Json) -> None:
        tenant_id = self._require_tenant(claim)
        with self._transaction_for_tenant(tenant_id):
            with self.connection.cursor() as cursor:
                self._upsert_claim_cursor(cursor, tenant_id, claim)

    def visible_segments(self, tenant_id: str) -> list[Json]:
        return self._execute_json_list(
            tenant_id,
            """
            SELECT payload FROM segments
            WHERE tenant_id = %s
            ORDER BY meeting_id, start_ms, segment_id
            """,
            (tenant_id,),
        )

    def visible_claims(self, tenant_id: str) -> list[Json]:
        return self._execute_json_list(
            tenant_id,
            """
            SELECT payload FROM claims
            WHERE tenant_id = %s
            ORDER BY source_meeting_id, created_at, claim_id
            """,
            (tenant_id,),
        )

    def visible_meetings(self, tenant_id: str) -> list[Json]:
        return self._execute_json_list(
            tenant_id,
            "SELECT payload FROM meetings WHERE tenant_id = %s ORDER BY meeting_id",
            (tenant_id,),
        )

    def get_segment(self, tenant_id: str, segment_id: str) -> Json | None:
        rows = self._execute_json_list(
            tenant_id,
            """
            SELECT payload FROM segments
            WHERE tenant_id = %s AND segment_id = %s
            LIMIT 1
            """,
            (tenant_id, segment_id),
        )
        return rows[0] if rows else None

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "PostgreSQLRepository":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()


def migration_directory() -> Path:
    """Return the SQL migration directory for tooling and packaging."""

    return Path(__file__).with_name("migrations")
