"""固定会议 Fixture 的研究质量评估。

只评估现有 MeetingMemoryService/MemoryStore 的 answer 结果，不联网、不调用
LLM、不修改 Provider。评估会议、Claim、证据的排序质量，并检查引用时间窗、
no-answer、租户隔离和当前/历史状态。
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

try:
    from engine import Fixture, load_fixture
    from service import MeetingMemoryService
except ImportError:
    # 直接执行 evaluation/research_quality.py 时补上 baseline 目录。
    import sys
    baseline_dir = Path(__file__).resolve().parents[1]
    if str(baseline_dir) not in sys.path:
        sys.path.insert(0, str(baseline_dir))
    from engine import Fixture, load_fixture  # type: ignore
    from service import MeetingMemoryService  # type: ignore

DEFAULT_KS: Tuple[int, ...] = (1, 3, 5)
CROSS_MEETING_QUERY_TYPES = {"cross_meeting_change", "cross_meeting_summary"}
STATE_QUERY_TYPES = {"current_state", "historical_state"}
CITATION_REQUIRED_FIELDS = (
    "meeting_id", "segment_id", "speaker_id", "start_ms", "end_ms", "text",
)


def _unique(values: Iterable[str]) -> List[str]:
    result: List[str] = []
    seen: set[str] = set()
    for value in values:
        value = str(value)
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _recall(ranked: Sequence[str], expected: set[str], k: int) -> float:
    if not expected:
        return 1.0 if not ranked[:k] else 0.0
    return round(len(set(ranked[:k]) & expected) / len(expected), 6)


def _precision(ranked: Sequence[str], expected: set[str], k: int) -> float:
    selected = list(ranked[:k])
    if not selected:
        return 1.0 if not expected else 0.0
    return round(len(set(selected) & expected) / len(selected), 6)


def _mrr(ranked: Sequence[str], expected: set[str]) -> float:
    if not expected:
        return 1.0 if not ranked else 0.0
    for index, value in enumerate(ranked, 1):
        if value in expected:
            return round(1.0 / index, 6)
    return 0.0


def _ndcg(ranked: Sequence[str], expected: set[str], k: int) -> float:
    if not expected:
        return 1.0 if not ranked[:k] else 0.0
    selected = ranked[:k]
    dcg = sum(
        1.0 / math.log2(index + 2)
        for index, value in enumerate(selected)
        if value in expected
    )
    ideal_hits = min(len(expected), k)
    ideal = sum(1.0 / math.log2(index + 2) for index in range(ideal_hits))
    return round(dcg / ideal, 6) if ideal else 0.0


def _mean(values: Iterable[float]) -> float:
    numbers = [float(value) for value in values]
    return round(sum(numbers) / len(numbers), 6) if numbers else 0.0


def _at_path(root: Any, path: Sequence[str], default: Any = None) -> Any:
    value = root
    for key in path:
        if not isinstance(value, Mapping):
            return default
        value = value.get(key, default)
    return value


def _canonical_claim(
    candidate: Mapping[str, Any],
    gold_by_id: Mapping[str, Mapping[str, Any]],
) -> Optional[str]:
    candidate_id = str(candidate.get("claim_id", ""))
    if candidate_id in gold_by_id:
        return candidate_id
    candidate_key = tuple(
        str(candidate.get(field, ""))
        for field in ("tenant_id", "subject", "predicate", "object")
    )
    for gold_id, gold in gold_by_id.items():
        gold_key = tuple(
            str(gold.get(field, ""))
            for field in ("tenant_id", "subject", "predicate", "object")
        )
        if candidate_key == gold_key:
            return gold_id
    candidate_evidence = set(map(str, candidate.get("evidence_segment_ids", [])))
    if candidate_evidence:
        matches: List[Tuple[int, str]] = []
        for gold_id, gold in gold_by_id.items():
            overlap = len(candidate_evidence & set(map(str, gold.get("evidence_segment_ids", []))))
            if overlap:
                matches.append((overlap, gold_id))
        if matches:
            return max(matches)[1]
    return None


def _ranked_claims(
    claims: Sequence[Mapping[str, Any]],
    gold_by_id: Mapping[str, Mapping[str, Any]],
) -> Tuple[List[str], Dict[str, Mapping[str, Any]]]:
    ranked: List[str] = []
    candidates: Dict[str, Mapping[str, Any]] = {}
    for claim in claims:
        canonical = _canonical_claim(claim, gold_by_id)
        claim_id = canonical or ("candidate:" + str(claim.get("claim_id", "")))
        ranked.append(claim_id)
        candidates[claim_id] = claim
    return _unique(ranked), candidates


def _ranked_meetings(
    result: Mapping[str, Any],
    ranked_claim_ids: Sequence[str],
    claim_candidates: Mapping[str, Mapping[str, Any]],
) -> List[str]:
    values: List[str] = []
    for claim_id in ranked_claim_ids:
        meeting_id = claim_candidates.get(claim_id, {}).get("source_meeting_id")
        if meeting_id:
            values.append(str(meeting_id))
    for citation in result.get("citations", []) or []:
        if citation.get("meeting_id"):
            values.append(str(citation["meeting_id"]))
    values.extend(str(value) for value in result.get("meetings", []) or [])
    return _unique(values)


def _ranked_evidence(result: Mapping[str, Any]) -> List[str]:
    return _unique(
        str(citation["segment_id"])
        for citation in result.get("citations", []) or []
        if citation.get("segment_id")
    )


def _citation_shape(citation: Mapping[str, Any]) -> Tuple[bool, str]:
    missing = [field for field in CITATION_REQUIRED_FIELDS if citation.get(field) in (None, "")]
    if missing:
        return False, "missing:" + ",".join(missing)
    start, end = citation.get("start_ms"), citation.get("end_ms")
    if (
        isinstance(start, bool) or isinstance(end, bool)
        or not isinstance(start, (int, float))
        or not isinstance(end, (int, float))
    ):
        return False, "invalid_time_type"
    if start < 0 or end < start:
        return False, "invalid_time_range"
    if not isinstance(citation.get("text"), str) or not citation["text"].strip():
        return False, "empty_text"
    return True, ""


def _citation_summary(result: Mapping[str, Any], expected: set[str]) -> Dict[str, Any]:
    citations = list(result.get("citations", []) or [])
    valid = 0
    invalid: List[Dict[str, str]] = []
    for citation in citations:
        ok, reason = _citation_shape(citation)
        if ok:
            valid += 1
        else:
            invalid.append({
                "segment_id": str(citation.get("segment_id", "")),
                "reason": reason,
            })
    rate = valid / len(citations) if citations else (1.0 if not expected else 0.0)
    return {
        "valid": valid,
        "total": len(citations),
        "rate": round(rate, 6),
        "invalid": invalid,
        "required_fields": list(CITATION_REQUIRED_FIELDS),
        "time_window_is_playable_shape": bool(not invalid and (citations or not expected)),
    }


def _tenant_check(result: Mapping[str, Any], tenant_id: str, system: Any) -> Dict[str, Any]:
    repository = getattr(system, "repository", system)
    segments = getattr(repository, "segments", {}) or {}
    meetings = getattr(repository, "meetings", {}) or {}
    claims = getattr(repository, "claims", {}) or {}
    leaked_meetings: List[str] = []
    leaked_claims: List[str] = []
    leaked_segments: List[str] = []

    for meeting_id in result.get("meetings", []) or []:
        meeting = meetings.get(meeting_id)
        if meeting and str(meeting.get("tenant_id")) != str(tenant_id):
            leaked_meetings.append(str(meeting_id))
    for claim in result.get("claims", []) or []:
        claim_id = str(claim.get("claim_id", ""))
        claim_tenant = claim.get("tenant_id")
        stored = claims.get(claim_id)
        if claim_tenant not in (None, "") and str(claim_tenant) != str(tenant_id):
            leaked_claims.append(claim_id)
        if stored and str(stored.get("tenant_id")) != str(tenant_id):
            leaked_claims.append(claim_id)
    for citation in result.get("citations", []) or []:
        segment_id = str(citation.get("segment_id", ""))
        if citation.get("tenant_id") not in (None, "") and str(citation["tenant_id"]) != str(tenant_id):
            leaked_segments.append(segment_id)
        stored_segment = segments.get(segment_id)
        if stored_segment and str(stored_segment.get("tenant_id")) != str(tenant_id):
            leaked_segments.append(segment_id)
        meeting = meetings.get(citation.get("meeting_id"))
        if meeting and str(meeting.get("tenant_id")) != str(tenant_id):
            leaked_meetings.append(str(citation.get("meeting_id")))
    return {
        "leak_free": not (leaked_meetings or leaked_claims or leaked_segments),
        "leaked_meetings": _unique(leaked_meetings),
        "leaked_claims": _unique(leaked_claims),
        "leaked_segments": _unique(leaked_segments),
    }


def _state_hit(
    query: Mapping[str, Any],
    ranked_claim_ids: Sequence[str],
    claim_candidates: Mapping[str, Mapping[str, Any]],
    gold_by_id: Mapping[str, Mapping[str, Any]],
) -> Optional[bool]:
    query_type = str(query.get("query_type", ""))
    if query_type not in STATE_QUERY_TYPES:
        return None
    expected = set(map(str, query.get("expected_claims", [])))
    if not expected:
        return False
    for claim_id in ranked_claim_ids:
        if claim_id in expected:
            candidate = claim_candidates.get(claim_id, {})
            gold = gold_by_id.get(claim_id, {})
            return str(candidate.get("status", "")) == str(gold.get("status", ""))
    return False


def evaluate_query(
    system: Any,
    query: Mapping[str, Any],
    *,
    gold_claims: Sequence[Mapping[str, Any]] = (),
    ks: Sequence[int] = DEFAULT_KS,
) -> Dict[str, Any]:
    """评估一个问题。system 只需要实现既有 answer(question, tenant, ...)。"""

    normalized_ks = tuple(sorted(set(max(1, int(k)) for k in ks)))
    if not normalized_ks:
        raise ValueError("ks must contain at least one positive integer")
    top_k = max(normalized_ks)
    result = system.answer(
        str(query["question"]),
        str(query["tenant_id"]),
        str(query.get("query_type", "retrieval")),
        top_k=top_k,
    )
    gold_by_id = {
        str(claim["claim_id"]): claim
        for claim in gold_claims
        if claim.get("claim_id")
    }
    ranked_claims, claim_candidates = _ranked_claims(result.get("claims", []) or [], gold_by_id)
    ranked_meetings = _ranked_meetings(result, ranked_claims, claim_candidates)
    ranked_evidence = _ranked_evidence(result)
    expected_meetings = set(map(str, query.get("expected_meetings", [])))
    expected_claims = set(map(str, query.get("expected_claims", [])))
    expected_evidence = set(map(str, query.get("expected_evidence", [])))

    recall_at_k: Dict[str, Dict[str, float]] = {"meeting": {}, "claim": {}, "evidence": {}}
    precision_at_k: Dict[str, Dict[str, float]] = {"meeting": {}, "claim": {}, "evidence": {}}
    ndcg_at_k: Dict[str, Dict[str, float]] = {"meeting": {}, "claim": {}, "evidence": {}}
    for k in normalized_ks:
        key = str(k)
        for kind, ranked, expected in (
            ("meeting", ranked_meetings, expected_meetings),
            ("claim", ranked_claims, expected_claims),
            ("evidence", ranked_evidence, expected_evidence),
        ):
            recall_at_k[kind][key] = _recall(ranked, expected, k)
            precision_at_k[kind][key] = _precision(ranked, expected, k)
            ndcg_at_k[kind][key] = _ndcg(ranked, expected, k)

    no_answer_correct = bool(result.get("no_answer")) == bool(query.get("no_answer"))
    localization = bool(ranked_meetings and ranked_meetings[0] in expected_meetings) if expected_meetings else not ranked_meetings
    exact_meetings = set(ranked_meetings) == expected_meetings
    tenant = _tenant_check(result, str(query["tenant_id"]), system)
    state_hit = _state_hit(query, ranked_claims, claim_candidates, gold_by_id)
    cross_recall: Optional[float] = None
    cross_hit: Optional[bool] = None
    if str(query.get("query_type", "")) in CROSS_MEETING_QUERY_TYPES:
        cross_recall = recall_at_k["meeting"][str(top_k)]
        cross_hit = cross_recall >= 1.0

    return {
        "query_id": str(query.get("query_id", "")),
        "query_type": str(query.get("query_type", "retrieval")),
        "tenant_id": str(query.get("tenant_id", "")),
        "question": str(query.get("question", "")),
        "expected": {
            "meetings": sorted(expected_meetings),
            "claims": sorted(expected_claims),
            "evidence": sorted(expected_evidence),
            "no_answer": bool(query.get("no_answer")),
        },
        "ranked": {"meetings": ranked_meetings, "claims": ranked_claims, "evidence": ranked_evidence},
        "recall_at_k": recall_at_k,
        "precision_at_k": precision_at_k,
        "mrr": {
            "meeting": _mrr(ranked_meetings, expected_meetings),
            "claim": _mrr(ranked_claims, expected_claims),
            "evidence": _mrr(ranked_evidence, expected_evidence),
        },
        "ndcg_at_k": ndcg_at_k,
        "meeting_localization_accuracy": int(localization),
        "meeting_set_accuracy": int(exact_meetings),
        "evidence_recall": recall_at_k["evidence"][str(top_k)],
        "citation_playable": _citation_summary(result, expected_evidence),
        "no_answer_correct": int(no_answer_correct),
        "tenant_isolation": tenant,
        "state_kind": str(query.get("query_type")) if str(query.get("query_type")) in STATE_QUERY_TYPES else None,
        "state_hit": state_hit,
        "cross_meeting_recall": cross_recall,
        "cross_meeting_hit": int(cross_hit) if cross_hit is not None else None,
        "answer": dict(result),
    }


def _aggregate(rows: Sequence[Mapping[str, Any]], ks: Sequence[int]) -> Dict[str, Any]:
    if not rows:
        raise ValueError("no query rows to aggregate")
    normalized_ks = tuple(sorted(set(max(1, int(k)) for k in ks)))

    def mean_path(path: Sequence[str], selected: Optional[Sequence[Mapping[str, Any]]] = None) -> float:
        source = list(selected if selected is not None else rows)
        values = [_at_path(row, path) for row in source]
        return _mean(value for value in values if isinstance(value, (int, float)))

    current = [row for row in rows if row.get("state_kind") == "current_state"]
    historical = [row for row in rows if row.get("state_kind") == "historical_state"]
    cross = [row for row in rows if row.get("cross_meeting_hit") is not None]
    valid_citations = sum(int(_at_path(row, ("citation_playable", "valid"), 0)) for row in rows)
    total_citations = sum(int(_at_path(row, ("citation_playable", "total"), 0)) for row in rows)
    citation_rate = valid_citations / total_citations if total_citations else _mean(
        _at_path(row, ("citation_playable", "rate"), 0.0) for row in rows
    )
    leak_free = sum(bool(_at_path(row, ("tenant_isolation", "leak_free"), False)) for row in rows)

    recall: Dict[str, Dict[str, float]] = {}
    precision: Dict[str, Dict[str, float]] = {}
    ndcg: Dict[str, Dict[str, float]] = {}
    for kind in ("meeting", "claim", "evidence"):
        recall[kind] = {str(k): mean_path(("recall_at_k", kind, str(k))) for k in normalized_ks}
        precision[kind] = {str(k): mean_path(("precision_at_k", kind, str(k))) for k in normalized_ks}
        ndcg[kind] = {str(k): mean_path(("ndcg_at_k", kind, str(k))) for k in normalized_ks}

    return {
        "queries": len(rows),
        "ks": list(normalized_ks),
        "recall_at_k": recall,
        "precision_at_k": precision,
        "mrr": {
            "meeting": mean_path(("mrr", "meeting")),
            "claim": mean_path(("mrr", "claim")),
            "evidence": mean_path(("mrr", "evidence")),
        },
        "ndcg_at_k": ndcg,
        "meeting_localization_accuracy": mean_path(("meeting_localization_accuracy",)),
        "meeting_set_accuracy": mean_path(("meeting_set_accuracy",)),
        "evidence_recall": mean_path(("evidence_recall",)),
        "citation_playable_rate": round(citation_rate, 6),
        "citation_shape_valid": {"valid": valid_citations, "total": total_citations, "rate": round(citation_rate, 6)},
        "no_answer_accuracy": mean_path(("no_answer_correct",)),
        "tenant_isolation": {
            "leak_free_queries": leak_free,
            "queries": len(rows),
            "leakage_free_rate": round(leak_free / len(rows), 6),
        },
        "current_state_hit_rate": mean_path(("state_hit",), current),
        "current_state_queries": len(current),
        "historical_state_hit_rate": mean_path(("state_hit",), historical),
        "historical_state_queries": len(historical),
        "cross_meeting_hit_rate": mean_path(("cross_meeting_hit",), cross),
        "cross_meeting_recall": mean_path(("cross_meeting_recall",), cross),
        "cross_meeting_queries": len(cross),
    }


def evaluate_fixture(
    fixture_root: Path,
    *,
    system: Any | None = None,
    ks: Sequence[int] = DEFAULT_KS,
) -> Dict[str, Any]:
    """评估固定 Fixture，system 可替换为任何兼容 answer() 的实现。"""

    fixture: Fixture = load_fixture(Path(fixture_root))
    service = system or MeetingMemoryService.from_fixture(fixture)
    rows = [
        evaluate_query(service, query, gold_claims=fixture.gold_claims, ks=ks)
        for query in fixture.queries
    ]
    report = _aggregate(rows, ks)
    report.update({
        "fixture": str(Path(fixture_root)),
        "meetings_loaded": len(getattr(service, "meetings", {})),
        "segments_loaded": len(getattr(service, "segments", {})),
        "claims_loaded": len(getattr(service, "claims", {})),
        "query_rows": rows,
    })
    return report


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="固定会议 Fixture 研究质量评估")
    parser.add_argument(
        "--fixture-root",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "fixtures" / "meeting-memory-fixture-10",
    )
    parser.add_argument("--ks", default="1,3,5")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    ks = tuple(int(value.strip()) for value in str(args.ks).split(",") if value.strip())
    report = evaluate_fixture(args.fixture_root, ks=ks)
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
        print("wrote", args.output)
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
