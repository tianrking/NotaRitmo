"""批量运行单会议结构化抽取并离线评分。

默认 ``fixture-replay``，不联网；真实 Anthropic/OpenAI-compatible Provider
必须显式选择并提供环境变量。输出只包含安全运行元数据，不包含授权令牌。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
PROVIDER_ROOT = REPO_ROOT.parent / "llm-providers"
for path in (REPO_ROOT, PROVIDER_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from baseline.evaluation.evaluator import evaluate_predictions  # noqa: E402
from intelligence.extractor import MeetingArtifactExtractor  # noqa: E402
from intelligence.prompts import build_meeting_artifact_request  # noqa: E402
from llm_providers.contracts import LLMProvider, LLMRequest, LLMResponse, ProviderError, Usage  # noqa: E402
from llm_providers.providers import AnthropicCompatibleProvider, OfflineFixtureProvider, OpenAICompatibleProvider  # noqa: E402
from llm_providers.config import ProviderConfig  # noqa: E402


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSONL {path}:{number}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"JSONL row must be an object: {path}:{number}")
        rows.append(value)
    return rows


class FixtureReplayProvider(LLMProvider):
    """将 gold Fixture 转成完整 Artifact；只测试编排，不代表模型质量。"""
    name = "fixture-replay"

    def __init__(self, fixture_dir: Path) -> None:
        self.artifacts = {str(row["meeting_id"]): row for row in read_jsonl(fixture_dir / "gold_artifacts.jsonl")}
        self.claims: dict[str, list[dict[str, Any]]] = {}
        for row in read_jsonl(fixture_dir / "gold_claims.jsonl"):
            self.claims.setdefault(str(row.get("source_meeting_id", "")), []).append(row)

    def complete_json(self, request: LLMRequest) -> LLMResponse:
        meeting = request.user_payload.get("meeting", {})
        if not isinstance(meeting, Mapping):
            raise ProviderError("fixture meeting must be an object")
        meeting_id = str(meeting.get("meeting_id", ""))
        gold = self.artifacts.get(meeting_id)
        if gold is None:
            raise ProviderError(f"fixture has no gold artifact for {meeting_id}")
        segments = [row for row in request.user_payload.get("segments", []) if isinstance(row, Mapping)]
        local_ids = {str(row.get("segment_id", "")) for row in segments}
        evidence = [str(value) for value in gold.get("evidence_segment_ids", []) if str(value) in local_ids]
        fallback = [next(iter(local_ids))] if local_ids else []

        def items(ids: Iterable[str], prefix: str) -> list[dict[str, Any]]:
            return [{f"{prefix}_id": str(value), "content": str(value), "evidence_segment_ids": evidence[:1] or fallback} for value in ids]

        claims: list[dict[str, Any]] = []
        for claim in self.claims.get(meeting_id, []):
            copy = dict(claim)
            copy["evidence_segment_ids"] = [str(value) for value in claim.get("evidence_segment_ids", []) if str(value) in local_ids] or fallback
            claims.append(copy)
        data = {
            "schema_version": "meeting-artifact-v1",
            "meeting_id": meeting_id,
            "tenant_id": str(meeting.get("tenant_id", "")),
            "summary": "[fixture replay; not an LLM result]",
            "topics": list(gold.get("expected_topics", [])), "chapters": [], "facts": [],
            "decisions": items(gold.get("expected_decisions", []), "decision"),
            "action_items": items(gold.get("expected_action_items", []), "action"),
            "risks": items(gold.get("expected_risks", []), "risk"), "open_questions": [], "keywords": [],
            "claims": claims, "evidence": [], "evidence_segment_ids": evidence,
        }
        return LLMResponse(
            data=data, provider=self.name, model="gold-fixture", prompt_version=request.prompt_version,
            input_hash=request.input_hash, schema_version=request.schema_version,
            usage=Usage.estimate(request, data), cost_usd=0.0, latency_ms=0.0,
            raw_metadata={"mode": "fixture_replay", "warning": "contract only; not model quality"},
        )


def _remote_provider(name: str) -> LLMProvider:
    if name == "anthropic-compatible":
        base_url = os.getenv("ANTHROPIC_BASE_URL", "").strip()
        model = os.getenv("ANTHROPIC_MODEL", os.getenv("ANTHROPIC_DEFAULT_SONNET_MODEL", "")).strip()
        token = os.getenv("ANTHROPIC_AUTH_TOKEN", os.getenv("ANTHROPIC_API_KEY", "")).strip()
        if not base_url or not model or not token:
            raise ProviderError("Anthropic Provider 需要 ANTHROPIC_BASE_URL、ANTHROPIC_MODEL、ANTHROPIC_AUTH_TOKEN")
        return AnthropicCompatibleProvider(ProviderConfig(provider=name, api_style="anthropic", base_url=base_url, model=model, api_key=token, auth_header="x-api-key"))
    base_url = os.getenv("LLM_BASE_URL", "").strip()
    model = os.getenv("LLM_MODEL", "").strip()
    if not base_url or not model:
        raise ProviderError("OpenAI Provider 需要 LLM_BASE_URL、LLM_MODEL")
    return OpenAICompatibleProvider(ProviderConfig(provider=name, api_style="openai", base_url=base_url, model=model, api_key=os.getenv("LLM_API_KEY", ""), auth_header="authorization"))


def build_provider(name: str, fixture_dir: Path) -> LLMProvider:
    if name == "fixture-replay":
        return FixtureReplayProvider(fixture_dir)
    if name == "offline":
        return OfflineFixtureProvider()
    if name in {"anthropic-compatible", "openai-compatible"}:
        return _remote_provider(name)
    raise ProviderError("unknown provider: " + name)


def run_loop(provider: LLMProvider, fixture_dir: Path, output_dir: Path, *, prompt_version: str, max_meetings: int | None, max_attempts: int) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    meetings, segments = read_jsonl(fixture_dir / "meetings.jsonl"), read_jsonl(fixture_dir / "segments.jsonl")
    gold_artifacts, gold_claims = read_jsonl(fixture_dir / "gold_artifacts.jsonl"), read_jsonl(fixture_dir / "gold_claims.jsonl")
    by_meeting: dict[str, list[dict[str, Any]]] = {}
    claims_by_meeting: dict[str, list[dict[str, Any]]] = {}
    for row in segments: by_meeting.setdefault(str(row.get("meeting_id", "")), []).append(row)
    for row in gold_claims: claims_by_meeting.setdefault(str(row.get("source_meeting_id", "")), []).append(row)
    selected = meetings[:max_meetings] if max_meetings else meetings
    # ``max_meetings`` limits actual Provider calls and therefore must also
    # limit the Gold rows used for scoring.  Otherwise unprocessed meetings are
    # interpreted as empty predictions and dilute the macro metrics.
    selected_ids = {str(row.get("meeting_id", "")) for row in selected}
    selected_gold_artifacts = [
        row for row in gold_artifacts if str(row.get("meeting_id", "")) in selected_ids
    ]
    extractor = MeetingArtifactExtractor(provider, prompt_version=prompt_version, max_attempts=max_attempts)
    predictions: dict[str, Mapping[str, Any]] = {}; records: list[dict[str, Any]] = []
    counts = {"succeeded": 0, "failed": 0, "needs_review": 0}
    for meeting in selected:
        meeting_id = str(meeting.get("meeting_id", "")); meeting_segments = by_meeting.get(meeting_id, [])
        request = build_meeting_artifact_request(meeting, meeting_segments, prompt_version=prompt_version)
        outcome = extractor.extract_result(meeting, meeting_segments); counts[outcome.status.value] = counts.get(outcome.status.value, 0) + 1
        if outcome.artifact is not None: predictions[meeting_id] = outcome.artifact
        records.append({"schema_version": "llm-loop-record-v1", "meeting_id": meeting_id, "status": outcome.status.value,
                        "input_hash": outcome.provider.get("input_hash", request.input_hash), "prompt_version": prompt_version,
                        "provider": outcome.provider, "attempts": [attempt.__dict__ for attempt in outcome.attempts],
                        "error": outcome.error, "retryable": outcome.retryable, "review_reasons": outcome.review_reasons,
                        "artifact": outcome.artifact})
    predictions_path = output_dir / "predictions.jsonl"
    predictions_path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in records), encoding="utf-8")
    # 评估器的类别 gold 使用稳定 ID 字符串；落盘 predictions 保留完整对象和证据。
    scoring_predictions: dict[str, Mapping[str, Any]] = {}
    for meeting_id, artifact in predictions.items():
        scoring = dict(artifact)
        for field, id_field in (("decisions", "decision_id"), ("action_items", "action_id"), ("risks", "risk_id")):
            scoring[field] = [item.get(id_field, item.get("id", "")) if isinstance(item, Mapping) else item for item in scoring.get(field, [])]
        quality = scoring.get("evidence_segment_ids", [])
        scoring["evidence_segment_ids"] = list(quality)
        scoring_predictions[meeting_id] = scoring
    quality = evaluate_predictions(scoring_predictions, selected_gold_artifacts, claims_by_meeting, provider_metadata={"name": getattr(provider, "name", "provider"), "prompt_version": prompt_version})
    summary = {"schema_version": "llm-loop-summary-v1", "fixture_dir": str(fixture_dir), "provider": getattr(provider, "name", "provider"), "meetings": len(selected), "counts": counts, "predictions_path": str(predictions_path), "extraction_quality": quality}
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--fixture-dir", required=True, type=Path)
    parser.add_argument("--provider", default="fixture-replay", choices=("fixture-replay", "offline", "anthropic-compatible", "openai-compatible"))
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/llm-loop")); parser.add_argument("--prompt-version", default="meeting-artifact-v1")
    parser.add_argument("--max-meetings", type=int, default=0); parser.add_argument("--max-attempts", type=int, default=2); args = parser.parse_args(argv)
    try:
        result = run_loop(build_provider(args.provider, args.fixture_dir), args.fixture_dir, args.output_dir, prompt_version=args.prompt_version, max_meetings=args.max_meetings or None, max_attempts=args.max_attempts)
    except ProviderError as exc:
        print("Provider 配置或调用失败：" + str(exc), file=sys.stderr); return 2
    print(json.dumps({"provider": result["provider"], "meetings": result["meetings"], "counts": result["counts"], "macro": result["extraction_quality"]["macro"], "predictions_path": result["predictions_path"]}, ensure_ascii=False, indent=2))
    return 0 if result["counts"].get("failed", 0) == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
