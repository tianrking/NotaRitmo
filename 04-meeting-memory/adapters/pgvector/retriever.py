"""PostgreSQL/pgvector Retriever with an explicit lexical fallback boundary.

The adapter retrieves candidates only.  It never decides Claim authority,
state transitions, permissions, or the final natural-language answer.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Any, Callable, Dict, Iterator, Mapping, Protocol, Sequence


Json = Dict[str, Any]
ConnectionFactory = Callable[[str], Any]


class PgVectorDependencyError(RuntimeError):
    """Raised when psycopg 3 is unavailable for a pgvector connection."""


class EmbeddingProvider(Protocol):
    """Provider-neutral embedding boundary; dimensions must match migration SQL."""

    model: str
    dimensions: int

    def embed(self, text: str) -> Sequence[float]:
        ...


class PgVectorRetriever:
    """Semantic candidate retriever backed by PostgreSQL + pgvector.

    ``fallback`` is opt-in.  When omitted, database/extension failures are
    raised so production cannot silently degrade.  Passing the existing
    LexicalRetriever explicitly is useful for controlled hybrid experiments.
    """

    retrieval_mode = "postgres_pgvector_cosine"

    def __init__(
        self,
        dsn: str | None = None,
        *,
        embedder: EmbeddingProvider,
        connection: Any | None = None,
        connection_factory: ConnectionFactory | None = None,
        fallback: Any | None = None,
        allow_fallback: bool = False,
    ) -> None:
        self.embedder = embedder
        self.fallback = fallback
        self.allow_fallback = allow_fallback
        if connection is not None:
            self.connection = connection
            return
        if not dsn:
            raise ValueError("PgVectorRetriever requires a DATABASE_URL/DSN")
        if connection_factory is None:
            try:
                import psycopg
            except ImportError as exc:  # pragma: no cover - environment dependent
                raise PgVectorDependencyError(
                    "psycopg 3 is not installed; install 'psycopg[binary]' "
                    "for a PostgreSQL/pgvector deployment."
                ) from exc
            connection_factory = psycopg.connect
        self.connection = connection_factory(dsn)

    @staticmethod
    def _vector_literal(values: Sequence[float]) -> str:
        if not values:
            raise ValueError("embedding must contain at least one dimension")
        normalized = []
        for value in values:
            number = float(value)
            if number != number or number in (float("inf"), float("-inf")):
                raise ValueError("embedding contains NaN or infinity")
            normalized.append(format(number, ".12g"))
        return "[" + ",".join(normalized) + "]"

    @staticmethod
    def _decode(value: Any) -> Json:
        if isinstance(value, str):
            value = json.loads(value)
        if not isinstance(value, dict):
            raise ValueError("retrieval payload must be a JSON object")
        return dict(value)

    @contextmanager
    def _transaction_for_tenant(self, tenant_id: str) -> Iterator[Any]:
        if not str(tenant_id).strip():
            raise ValueError("tenant_id is required for pgvector retrieval")
        transaction = getattr(self.connection, "transaction", None)
        if transaction is None:  # pragma: no cover
            raise TypeError("connection must expose psycopg 3 transaction()")
        with transaction():
            with self.connection.cursor() as cursor:
                cursor.execute(
                    "SELECT set_config('app.tenant_id', %s, true)",
                    (tenant_id,),
                )
            yield self.connection

    def _retrieve_once(
        self,
        question: str,
        tenant_id: str,
        query_type: str,
        top_k: int,
    ) -> dict[str, list[Json]]:
        vector = self._vector_literal(self.embedder.embed(question))
        with self._transaction_for_tenant(tenant_id):
            with self.connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT s.payload,
                           1 - (e.embedding <=> %s::vector) AS score
                    FROM segment_embeddings e
                    JOIN segments s ON s.tenant_id = e.tenant_id
                                   AND s.segment_id = e.segment_id
                    WHERE e.tenant_id = %s
                    ORDER BY e.embedding <=> %s::vector
                    LIMIT %s
                    """,
                    (vector, tenant_id, vector, max(1, int(top_k))),
                )
                segment_rows = [
                    {"score": float(row[1]), "segment": self._decode(row[0])}
                    for row in cursor.fetchall()
                ]
                claim_sql = """
                    SELECT c.payload,
                           1 - (e.embedding <=> %s::vector) AS score
                    FROM claim_embeddings e
                    JOIN claims c ON c.tenant_id = e.tenant_id
                                AND c.claim_id = e.claim_id
                    WHERE e.tenant_id = %s
                """
                params: list[Any] = [vector, tenant_id]
                if query_type == "current_state":
                    claim_sql += " AND c.status = 'active'\n"
                claim_sql += " ORDER BY e.embedding <=> %s::vector LIMIT %s"
                params.extend([vector, max(1, int(top_k))])
                cursor.execute(claim_sql, tuple(params))
                claim_rows = [
                    {"score": float(row[1]), "claim": self._decode(row[0])}
                    for row in cursor.fetchall()
                ]
        return {"segments": segment_rows, "claims": claim_rows}

    def retrieve(
        self,
        question: str,
        tenant_id: str,
        query_type: str,
        top_k: int = 5,
    ) -> dict[str, list[Json]]:
        try:
            return self._retrieve_once(question, tenant_id, query_type, top_k)
        except Exception:
            if not self.allow_fallback or self.fallback is None:
                raise
            # Fallback is deliberately explicit and observable to callers.
            result = self.fallback.retrieve(question, tenant_id, query_type, top_k)
            result["retrieval_mode"] = "explicit_fallback"
            return result

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "PgVectorRetriever":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()
