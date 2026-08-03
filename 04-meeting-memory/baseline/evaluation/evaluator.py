"""固定会议 Fixture 的 Provider 评估入口。

评估器不依赖任何模型 SDK。它既可以调用 ``LLMProvider``，也可以直接评估已
落盘的结构化预测，方便将 SaaS 调用与离线回归解耦。严格字段分数按集合
precision/recall/F1 计算；证据按 segment_id 计算，避免把生成文字相似误判为
事实正确。
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

try:  # 既可作为 ``evaluation.evaluator``，也可被 unittest discover 直接导入。
    from .provider import (
        FixtureReplayProvider,
        LLMProvider,
        LLMResponse,
        OpenAICompatibleConfig,
        OpenAICompatibleProvider,
        ProviderError,
        build_meeting_extraction_request,
    )
except ImportError:  # pragma: no cover - 仅是脚本/发现式测试的导入兼容
    from provider import (  # type: ignore
        FixtureReplayProvider,
        LLMProvider,
        LLMResponse,
        OpenAICompatibleConfig,
        OpenAICompatibleProvider,
        ProviderError,
        build_meeting_extraction_request,
    )


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ProviderError("invalid JSONL %s:%d" % (path, line_number)) from exc
            if not isinstance(value, dict):
                raise ProviderError("JSONL row must be an object: %s:%d" % (path, line_number))
            rows.append(value)
    return rows


def _stable_value(value: Any) -> str:
    if isinstance(value, str):
        return " ".join(value.strip().lower().split())
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _items(values: Any, preferred_keys: Sequence[str] = ()) -> List[str]:
    """将字符串、dict 列表或单值统一为评估标签。

    外部 LLM 可以返回 ``decision_id``/``id``，也可以返回 ``content``。若要和
    Fixture gold 做严格 ID 分数，应在 Provider 输出中保留 gold ID 或由上层做
    明确的标签映射；评估器不会偷偷猜测同义词。
    """

    if values is None:
        return []
    if isinstance(values, (str, int, float, bool)):
        return [_stable_value(values)]
    if isinstance(values, Mapping):
        values = [values]
    if not isinstance(values, Sequence):
        return [_stable_value(values)]
    result: List[str] = []
    keys = list(preferred_keys) + ["id", "claim_id", "decision_id", "action_id", "risk_id", "label", "name", "title", "content", "text"]
    for item in values:
        if isinstance(item, Mapping):
            selected = None
            for key in keys:
                if item.get(key) not in (None, ""):
                    selected = item[key]
                    break
            if selected is not None:
                result.append(_stable_value(selected))
        elif item not in (None, ""):
            result.append(_stable_value(item))
    return result


def _set(value: Any, preferred_keys: Sequence[str] = ()) -> set:
    return set(_items(value, preferred_keys))


def prf(expected: Iterable[str], predicted: Iterable[str]) -> Dict[str, Any]:
    gold = set(expected)
    got = set(predicted)
    true_positive = len(gold & got)
    precision = true_positive / len(got) if got else (1.0 if not gold else 0.0)
    recall = true_positive / len(gold) if gold else (1.0 if not got else 0.0)
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "expected": len(gold),
        "predicted": len(got),
        "true_positive": true_positive,
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "f1": round(f1, 6),
    }


@dataclass
class MeetingScore:
    meeting_id: str
    fields: Dict[str, Dict[str, Any]]
    evidence: Dict[str, Any]
    claims: Dict[str, Any]
    provider: Dict[str, Any]
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def score_artifact(
    meeting_id: str,
    gold_artifact: Mapping[str, Any],
    prediction: Mapping[str, Any],
    gold_claims: Sequence[Mapping[str, Any]] = (),
    provider: Optional[Mapping[str, Any]] = None,
) -> MeetingScore:
    """评估一个会议的结构化 Artifact；不调用模型、不访问数据库。"""

    fields = {
        "topics": prf(gold_artifact.get("expected_topics", []), prediction.get("topics", [])),
        "decisions": prf(gold_artifact.get("expected_decisions", []), prediction.get("decisions", [])),
        "action_items": prf(gold_artifact.get("expected_action_items", []), prediction.get("action_items", [])),
        "risks": prf(gold_artifact.get("expected_risks", []), prediction.get("risks", [])),
    }
    evidence = prf(gold_artifact.get("evidence_segment_ids", []), prediction.get("evidence_segment_ids", []))
    gold_claim_ids = [claim.get("claim_id") for claim in gold_claims if claim.get("claim_id")]
    claims = prf(gold_claim_ids, _items(prediction.get("claims", []), ("claim_id",)))
    return MeetingScore(
        meeting_id=meeting_id,
        fields=fields,
        evidence=evidence,
        claims=claims,
        provider=dict(provider or {}),
    )


def _mean(scores: Sequence[Mapping[str, Any]], path: Sequence[str]) -> float:
    values: List[float] = []
    for score in scores:
        value: Any = score
        for key in path:
            value = value.get(key, {}) if isinstance(value, Mapping) else {}
        if isinstance(value, (int, float)):
            values.append(float(value))
    return round(sum(values) / len(values), 6) if values else 0.0


def evaluate_predictions(
    predictions: Mapping[str, Mapping[str, Any]],
    gold_artifacts: Sequence[Mapping[str, Any]],
    gold_claims_by_meeting: Optional[Mapping[str, Sequence[Mapping[str, Any]]]] = None,
    provider_metadata: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """对已存在的 prediction 做离线评分。

    prediction 的 key 是 meeting_id，value 是模型输出的 Artifact JSON。这个入口
    是外部 SaaS 批量调用后重跑评测的关键，避免每次比较都重新消耗 token。
    """

    gold_claims_by_meeting = gold_claims_by_meeting or {}
    scores: List[MeetingScore] = []
    for gold in gold_artifacts:
        meeting_id = str(gold.get("meeting_id", ""))
        prediction = predictions.get(meeting_id, {})
        scores.append(
            score_artifact(
                meeting_id,
                gold,
                prediction,
                gold_claims_by_meeting.get(meeting_id, []),
                provider_metadata,
            )
        )
    rows = [score.to_dict() for score in scores]
    return {
        "meetings": len(scores),
        "scores": rows,
        "macro": {
            "topics_f1": _mean(rows, ("fields", "topics", "f1")),
            "decisions_f1": _mean(rows, ("fields", "decisions", "f1")),
            "action_items_f1": _mean(rows, ("fields", "action_items", "f1")),
            "risks_f1": _mean(rows, ("fields", "risks", "f1")),
            "evidence_f1": _mean(rows, ("evidence", "f1")),
            "claims_f1": _mean(rows, ("claims", "f1")),
        },
        "provider": dict(provider_metadata or {}),
    }


def _claims_by_meeting(rows: Sequence[Mapping[str, Any]]) -> Dict[str, List[Mapping[str, Any]]]:
    result: Dict[str, List[Mapping[str, Any]]] = {}
    for row in rows:
        result.setdefault(str(row.get("source_meeting_id", "")), []).append(row)
    return result


def evaluate_provider(
    provider: LLMProvider,
    fixture_dir: Path,
    output_path: Optional[Path] = None,
    max_meetings: Optional[int] = None,
    prompt_version: str = "meeting-extract-v1",
) -> Dict[str, Any]:
    """调用 Provider 并评估 10 场 Fixture，记录每次调用的成本/版本元数据。"""

    fixture_dir = Path(fixture_dir)
    meetings = read_jsonl(fixture_dir / "meetings.jsonl")
    segments = read_jsonl(fixture_dir / "segments.jsonl")
    gold_artifacts = read_jsonl(fixture_dir / "gold_artifacts.jsonl")
    gold_claims = _claims_by_meeting(read_jsonl(fixture_dir / "gold_claims.jsonl"))
    segment_by_meeting: Dict[str, List[Mapping[str, Any]]] = {}
    for segment in segments:
        segment_by_meeting.setdefault(str(segment.get("meeting_id", "")), []).append(segment)

    selected = meetings[:max_meetings] if max_meetings else meetings
    gold_by_meeting = {str(row.get("meeting_id")): row for row in gold_artifacts}
    predictions: Dict[str, Mapping[str, Any]] = {}
    call_metadata: Dict[str, Mapping[str, Any]] = {}
    errors = 0
    estimated_cost = 0.0
    total_tokens = 0
    scores: List[MeetingScore] = []
    for meeting in selected:
        meeting_id = str(meeting.get("meeting_id", ""))
        request = build_meeting_extraction_request(meeting, segment_by_meeting.get(meeting_id, []), prompt_version)
        try:
            response = provider.complete_json(request)
            predictions[meeting_id] = response.data
            metadata = {
                "provider": response.provider,
                "model": response.model,
                "prompt_version": response.prompt_version,
                "input_hash": response.input_hash,
                "usage": asdict(response.usage),
                "cost_usd": response.cost_usd,
                "latency_ms": response.latency_ms,
                "cached": response.cached,
                "raw_metadata": dict(response.raw_metadata),
            }
            call_metadata[meeting_id] = metadata
            if response.cost_usd is not None:
                estimated_cost += float(response.cost_usd)
            total_tokens += int(response.usage.total_tokens)
        except Exception as exc:  # keep other meetings evaluable
            errors += 1
            call_metadata[meeting_id] = {"error": str(exc), "input_hash": request.input_hash, "prompt_version": prompt_version}
            predictions[meeting_id] = {}

        if meeting_id in gold_by_meeting:
            score = score_artifact(meeting_id, gold_by_meeting[meeting_id], predictions[meeting_id], gold_claims.get(meeting_id, []), call_metadata[meeting_id])
            if "error" in call_metadata[meeting_id]:
                score.error = call_metadata[meeting_id]["error"]
            scores.append(score)

    rows = [score.to_dict() for score in scores]
    result = {
        "mode": "provider_evaluation",
        "fixture_dir": str(fixture_dir),
        "meetings": len(selected),
        "errors": errors,
        "estimated_cost_usd": round(estimated_cost, 10),
        "total_tokens": total_tokens,
        "provider": getattr(provider, "name", provider.__class__.__name__),
        "prompt_version": prompt_version,
        "scores": rows,
        "macro": {
            "topics_f1": _mean(rows, ("fields", "topics", "f1")),
            "decisions_f1": _mean(rows, ("fields", "decisions", "f1")),
            "action_items_f1": _mean(rows, ("fields", "action_items", "f1")),
            "risks_f1": _mean(rows, ("fields", "risks", "f1")),
            "evidence_f1": _mean(rows, ("evidence", "f1")),
            "claims_f1": _mean(rows, ("claims", "f1")),
        },
    }
    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def _provider_from_args(args: argparse.Namespace, fixture_dir: Path) -> LLMProvider:
    if args.provider == "fixture-replay":
        return FixtureReplayProvider(fixture_dir)
    config = OpenAICompatibleConfig.from_env()
    if args.base_url:
        config = OpenAICompatibleConfig(
            base_url=args.base_url,
            model=args.model or config.model,
            api_key=config.api_key,
            timeout_s=config.timeout_s,
            chat_path=config.chat_path,
            input_usd_per_1m=config.input_usd_per_1m,
            output_usd_per_1m=config.output_usd_per_1m,
            temperature=config.temperature,
            json_mode=config.json_mode,
        )
    return OpenAICompatibleProvider(config)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="会议 Fixture 的可选 LLM Provider 评估")
    parser.add_argument("--fixture-dir", required=True, type=Path)
    parser.add_argument("--provider", choices=("fixture-replay", "openai-compatible"), default="fixture-replay")
    parser.add_argument("--base-url", default="", help="可选，覆盖 LLM_BASE_URL")
    parser.add_argument("--model", default="", help="可选，覆盖 LLM_MODEL")
    parser.add_argument("--prompt-version", default="meeting-extract-v1")
    parser.add_argument("--max-meetings", type=int, default=0)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)
    provider = _provider_from_args(args, args.fixture_dir)
    result = evaluate_provider(
        provider,
        args.fixture_dir,
        args.output,
        max_meetings=args.max_meetings or None,
        prompt_version=args.prompt_version,
    )
    print(json.dumps({key: result[key] for key in ("mode", "meetings", "errors", "estimated_cost_usd", "total_tokens", "provider", "macro")}, ensure_ascii=False, indent=2))
    return 0 if result["errors"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
