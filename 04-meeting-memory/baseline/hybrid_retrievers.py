"""Composable Hybrid Retriever for lexical plus optional secondary candidates."""

from __future__ import annotations

from typing import Any

from ports import JsonObject, Repository, Retriever


class HybridRetriever:
    """Fuse two already tenant-filtered retrievers without owning storage."""

    retrieval_mode = "hybrid_lexical_secondary"

    def __init__(
        self,
        primary: Retriever,
        secondary: Retriever | None = None,
        *,
        primary_weight: float = 0.7,
        secondary_weight: float = 0.3,
    ) -> None:
        if primary_weight < 0 or secondary_weight < 0 or primary_weight + secondary_weight <= 0:
            raise ValueError("retriever weights must be non-negative and not both zero")
        self.primary = primary
        self.secondary = secondary
        total = primary_weight + secondary_weight
        self.primary_weight = primary_weight / total
        self.secondary_weight = secondary_weight / total

    @staticmethod
    def _key(row: JsonObject) -> tuple[str, str]:
        if "segment" in row:
            return ("segment", str(row["segment"]["segment_id"]))
        return ("claim", str(row["claim"]["claim_id"]))

    def _merge(
        self,
        primary: list[JsonObject],
        secondary: list[JsonObject],
    ) -> list[JsonObject]:
        merged: dict[tuple[str, str], JsonObject] = {}
        for row in primary:
            key = self._key(row)
            merged[key] = {**row, "score": self.primary_weight * float(row.get("score", 0.0))}
        for row in secondary:
            key = self._key(row)
            value = self.secondary_weight * float(row.get("score", 0.0))
            if key in merged:
                merged[key]["score"] = min(1.0, merged[key]["score"] + value)
            else:
                merged[key] = {**row, "score": value}
        return sorted(merged.values(), key=lambda row: row["score"], reverse=True)

    def retrieve(
        self,
        question: str,
        tenant_id: str,
        query_type: str,
        top_k: int = 5,
    ) -> dict[str, list[JsonObject]]:
        primary_result = self.primary.retrieve(question, tenant_id, query_type, top_k)
        secondary_result = (
            self.secondary.retrieve(question, tenant_id, query_type, top_k)
            if self.secondary is not None
            else {"segments": [], "claims": []}
        )
        segments = self._merge(primary_result["segments"], secondary_result["segments"])
        claims = self._merge(primary_result["claims"], secondary_result["claims"])
        return {"segments": segments[:top_k], "claims": claims[:top_k]}
