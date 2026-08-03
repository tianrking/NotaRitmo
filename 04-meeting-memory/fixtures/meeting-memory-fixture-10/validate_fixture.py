from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def read_jsonl(name: str) -> list[dict]:
    rows = []
    for line_no, line in enumerate((ROOT / name).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise AssertionError(f"{name}:{line_no}: invalid JSON: {exc}") from exc
    return rows


def main() -> None:
    meetings = read_jsonl("meetings.jsonl")
    segments = read_jsonl("segments.jsonl")
    artifacts = read_jsonl("gold_artifacts.jsonl")
    claims = read_jsonl("gold_claims.jsonl")
    queries = read_jsonl("queries.jsonl")

    meeting_map = {row["meeting_id"]: row for row in meetings}
    segment_map = {row["segment_id"]: row for row in segments}
    claim_map = {row["claim_id"]: row for row in claims}
    assert len(meeting_map) == 10, "expected 10 unique meetings"
    assert len(segment_map) == 60, "expected 60 unique segments"
    assert len(claim_map) == 18, "expected 18 unique claims"
    assert len(queries) == 18, "expected 18 queries"

    for meeting_id, meeting in meeting_map.items():
        meeting_segments = [s for s in segments if s["meeting_id"] == meeting_id]
        assert len(meeting_segments) == 6, f"{meeting_id}: expected six segments"
        previous_end = -1
        for segment in meeting_segments:
            assert segment["tenant_id"] == meeting["tenant_id"]
            assert segment["start_ms"] >= 0
            assert segment["end_ms"] > segment["start_ms"]
            assert segment["start_ms"] >= previous_end, f"{meeting_id}: overlapping segments"
            previous_end = segment["end_ms"]

    for segment in segments:
        assert segment["meeting_id"] in meeting_map
        assert segment["text"].strip()

    for artifact in artifacts:
        assert artifact["meeting_id"] in meeting_map
        for segment_id in artifact["evidence_segment_ids"]:
            assert segment_id in segment_map
            assert segment_map[segment_id]["meeting_id"] == artifact["meeting_id"]

    for claim in claims:
        assert claim["source_meeting_id"] in meeting_map
        assert claim["tenant_id"] == meeting_map[claim["source_meeting_id"]]["tenant_id"]
        for segment_id in claim["evidence_segment_ids"]:
            assert segment_id in segment_map
            assert segment_map[segment_id]["tenant_id"] == claim["tenant_id"]
        if claim.get("supersedes"):
            assert claim["supersedes"] in claim_map
        if claim.get("superseded_by"):
            assert claim["superseded_by"] in claim_map

    for query in queries:
        assert query["tenant_id"] in {"tenant_alpha", "tenant_beta"}
        for meeting_id in query["expected_meetings"]:
            assert meeting_id in meeting_map
            assert meeting_map[meeting_id]["tenant_id"] == query["tenant_id"]
        for claim_id in query["expected_claims"]:
            assert claim_id in claim_map
            assert claim_map[claim_id]["tenant_id"] == query["tenant_id"]
        for segment_id in query["expected_evidence"]:
            assert segment_id in segment_map
            assert segment_map[segment_id]["meeting_id"] in query["expected_meetings"]
        if query["no_answer"]:
            assert not query["expected_meetings"]
            assert not query["expected_claims"]
            assert not query["expected_evidence"]

    print(
        f"fixture valid: {len(meeting_map)} meetings, "
        f"{len(segment_map)} segments, {len(claim_map)} claims, "
        f"{len(queries)} queries"
    )


if __name__ == "__main__":
    main()
