"""Retriever adapters for the meeting-memory core."""

from __future__ import annotations

from typing import Callable

from engine import lexical_score
from ports import JsonObject, Repository


class LexicalRetriever:
    """Exact offline token/phrase retriever used by the original baseline."""

    retrieval_mode = "offline_lexical_token_baseline"

    def __init__(
        self,
        repository: Repository,
        *,
        score_fn: Callable[[str, str], float] = lexical_score,
    ) -> None:
        self.repository = repository
        self.score_fn = score_fn

    def retrieve(
        self,
        question: str,
        tenant_id: str,
        query_type: str,
        top_k: int = 5,
    ) -> dict[str, list[JsonObject]]:
        segment_rows = [
            {"score": self.score_fn(question, segment["text"]), "segment": segment}
            for segment in self.repository.visible_segments(tenant_id)
        ]
        segment_rows = sorted(
            (row for row in segment_rows if row["score"] > 0),
            key=lambda row: row["score"],
            reverse=True,
        )
        claim_rows = []
        for claim in self.repository.visible_claims(tenant_id):
            score = self.score_fn(
                question,
                " ".join((claim["subject"], claim["predicate"], claim["object"])),
            )
            if query_type == "current_state" and claim["status"] != "active":
                score *= 0.2
            if query_type == "historical_state" and claim["status"] == "superseded":
                score = min(1.0, score * 1.25)
            if score > 0:
                claim_rows.append({"score": min(1.0, score), "claim": claim})
        claim_rows.sort(key=lambda row: row["score"], reverse=True)
        return {"segments": segment_rows[:top_k], "claims": claim_rows[:top_k]}
