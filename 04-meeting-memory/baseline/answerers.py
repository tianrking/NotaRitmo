"""Answerer adapters with evidence and no-answer enforcement."""

from __future__ import annotations

from ports import JsonObject, LLMProvider, Repository, Retriever


class TemplateAnswerer:
    """Offline answerer preserving the original deterministic behavior."""

    def __init__(self, *, llm_provider: LLMProvider | None = None) -> None:
        self.llm_provider = llm_provider

    def _citations(
        self,
        retrieved: dict[str, list[JsonObject]],
        repository: Repository,
        tenant_id: str,
    ) -> list[JsonObject]:
        citations: list[JsonObject] = []
        seen: set[str] = set()
        for row in retrieved["segments"]:
            segment = row["segment"]
            if segment["segment_id"] in seen:
                continue
            seen.add(segment["segment_id"])
            citations.append(
                {
                    "meeting_id": segment["meeting_id"],
                    "segment_id": segment["segment_id"],
                    "speaker_id": segment["speaker_id"],
                    "start_ms": segment["start_ms"],
                    "end_ms": segment["end_ms"],
                    "text": segment["text"],
                    "score": row["score"],
                }
            )
        for row in retrieved["claims"]:
            for segment_id in row["claim"].get("evidence_segment_ids", []):
                if segment_id in seen or segment_id not in repository.segments:
                    continue
                segment = repository.segments[segment_id]
                if segment["tenant_id"] != tenant_id:
                    continue
                seen.add(segment_id)
                citations.append(
                    {
                        "meeting_id": segment["meeting_id"],
                        "segment_id": segment["segment_id"],
                        "speaker_id": segment["speaker_id"],
                        "start_ms": segment["start_ms"],
                        "end_ms": segment["end_ms"],
                        "text": segment["text"],
                        "score": row["score"],
                    }
                )
        return citations

    def answer(
        self,
        question: str,
        tenant_id: str,
        query_type: str,
        *,
        top_k: int,
        repository: Repository,
        retriever: Retriever,
    ) -> JsonObject:
        retrieved = retriever.retrieve(question, tenant_id, query_type, top_k)
        segments = retrieved["segments"]
        claims = retrieved["claims"]
        best_score = max([row["score"] for row in segments + claims] or [0.0])
        threshold = 0.25 if query_type in {"tenant_isolation", "no_answer"} else 0.12
        if best_score < threshold:
            return {
                "answer": None,
                "no_answer": True,
                "confidence": 0.0,
                "meetings": [],
                "claims": [],
                "citations": [],
                "retrieval_mode": getattr(retriever, "retrieval_mode", "custom"),
            }
        visible_claims = [row["claim"] for row in claims]
        if query_type == "current_state":
            visible_claims = [claim for claim in visible_claims if claim["status"] == "active"] or visible_claims
        answer_parts = [
            f"{claim['subject']}的{claim['predicate']}是：{claim['object']}。"
            for claim in visible_claims[:3]
        ]
        if not answer_parts:
            answer_parts = [row["segment"]["text"] for row in segments[:2]]
        citations = self._citations(retrieved, repository, tenant_id)
        meeting_ids = sorted(
            {claim["source_meeting_id"] for claim in visible_claims}
            | {citation["meeting_id"] for citation in citations}
        )
        return {
            "answer": " ".join(answer_parts),
            "no_answer": False,
            "confidence": round(min(0.99, max(0.5, best_score)), 4),
            "meetings": meeting_ids,
            "claims": visible_claims,
            "citations": citations,
            "retrieval_mode": getattr(retriever, "retrieval_mode", "custom"),
            "answer_mode": "offline_template",
        }


class GroundedLLMAnswerer(TemplateAnswerer):
    """Optional final wording provider constrained by retrieved evidence.

    Retrieval, tenant filtering, no-answer thresholds, and citations stay
    deterministic. Only final wording is delegated to the configured provider.
    """

    def __init__(self, llm_provider: LLMProvider) -> None:
        super().__init__(llm_provider=llm_provider)

    def answer(
        self,
        question: str,
        tenant_id: str,
        query_type: str,
        *,
        top_k: int,
        repository: Repository,
        retriever: Retriever,
    ) -> JsonObject:
        result = super().answer(
            question,
            tenant_id,
            query_type,
            top_k=top_k,
            repository=repository,
            retriever=retriever,
        )
        if result["no_answer"] or self.llm_provider is None:
            return result
        evidence = [
            {
                "meeting_id": citation["meeting_id"],
                "segment_id": citation["segment_id"],
                "speaker_id": citation["speaker_id"],
                "start_ms": citation["start_ms"],
                "end_ms": citation["end_ms"],
                "text": citation["text"],
            }
            for citation in result["citations"]
        ]
        prompt = (
            "只根据以下证据回答问题。不要添加证据中没有的事实；如果证据不足，"
            "请返回 NO_ANSWER。\n"
            f"问题：{question}\n证据：{evidence}"
        )
        response = self.llm_provider.generate(
            system_prompt="你是带证据引用的会议研究助手。",
            user_prompt=prompt,
            response_format="text",
            metadata={"tenant_id": tenant_id, "query_type": query_type},
        )
        if response.text and response.text.strip() != "NO_ANSWER":
            result["answer"] = response.text.strip()
            result["answer_mode"] = "llm_grounded"
            result["llm"] = {
                "provider": response.provider,
                "model": response.model,
                "usage": response.usage,
                "cost": response.cost,
            }
        return result
