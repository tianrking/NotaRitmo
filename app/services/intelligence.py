from __future__ import annotations

import re
from collections import Counter
from typing import Any

from app.services.normalizer import keyword_items, tokenize

COMPONENT_KINDS = (
    "summary",
    "facts",
    "decisions",
    "action_items",
    "risks",
    "open_questions",
    "topics",
)


def _rule_components(canonical: dict[str, Any]) -> dict[str, Any]:
    segments = canonical["segments"]
    transcript = "\n".join(item["text"] for item in segments)
    markers = {
        "facts": ("是", "有", "已经", "目前", "完成", "支持"),
        "decisions": ("决定", "确定", "结论", "改到", "改为", "采用", "最终", "统一"),
        "action_items": ("负责", "待办", "需要完成", "跟进", "截止", "安排"),
        "risks": ("风险", "可能失败", "阻塞", "隐患", "延迟", "来不及", "不稳定"),
        "open_questions": ("待确认", "还没定", "未确定", "需要讨论", "问题是", "？", "?"),
    }
    values: dict[str, Any] = {
        "summary": {
            "text": " ".join(item["text"] for item in segments[:8]) or "暂无可用摘要。",
            "evidence_ordinals": [item["ordinal"] for item in segments[:8]],
        },
        "facts": [],
        "decisions": [],
        "action_items": [],
        "risks": [],
        "open_questions": [],
        "topics": [],
    }
    for segment in segments:
        text = segment["text"]
        evidence = [segment["ordinal"]]
        if any(marker in text for marker in markers["facts"]):
            values["facts"].append(
                {
                    "text": text,
                    "status": "observed",
                    "confidence": 0.62,
                    "evidence_ordinals": evidence,
                }
            )
        if any(marker in text for marker in markers["decisions"]):
            values["decisions"].append(
                {
                    "text": text,
                    "status": "candidate",
                    "confidence": 0.72,
                    "evidence_ordinals": evidence,
                }
            )
        if any(marker in text for marker in markers["action_items"]):
            owner_match = re.search(r"([\u4e00-\u9fff]{2,4})负责", text)
            due_match = re.search(
                r"((?:20\d{2}[-年/.])?\d{1,2}[-月/.]\d{1,2}日?)", text
            )
            values["action_items"].append(
                {
                    "task": text,
                    "owner": owner_match.group(1) if owner_match else None,
                    "due_date": due_match.group(1) if due_match else None,
                    "status": "open",
                    "confidence": 0.7,
                    "evidence_ordinals": evidence,
                }
            )
        for kind in ("risks", "open_questions"):
            if any(marker in text for marker in markers[kind]):
                values[kind].append(
                    {
                        "text": text,
                        "status": "open",
                        "confidence": 0.7,
                        "evidence_ordinals": evidence,
                    }
                )
    for item in keyword_items(transcript):
        evidence = [
            segment["ordinal"]
            for segment in segments
            if item["text"] in segment["text"].lower()
        ][:5]
        if evidence:
            values["topics"].append({**item, "evidence_ordinals": evidence})
    return values


def _speaker_stats(canonical: dict[str, Any]) -> list[dict[str, Any]]:
    duration = max(
        canonical.get("duration_ms")
        or sum(max(item["end_ms"] - item["start_ms"], 0) for item in canonical["segments"]),
        1,
    )
    result = []
    for speaker in canonical["speakers"]:
        own = [
            item
            for item in canonical["segments"]
            if item["provider_speaker_id"] == speaker["provider_speaker_id"]
        ]
        speaking_ms = sum(max(item["end_ms"] - item["start_ms"], 0) for item in own)
        result.append(
            {
                **speaker,
                "segment_count": len(own),
                "speaking_ms": speaking_ms,
                "share": round(speaking_ms / duration, 4),
                "character_count": sum(len(item["text"]) for item in own),
                "evidence_ordinals": [item["ordinal"] for item in own],
            }
        )
    return result


def _chapters(canonical: dict[str, Any], summary: dict[str, Any]) -> list[dict[str, Any]]:
    segments = canonical["segments"]
    if not segments:
        return []
    size = max(1, min(8, (len(segments) + 3) // 4))
    result = []
    for index in range(0, len(segments), size):
        group = segments[index : index + size]
        terms = Counter(tokenize(" ".join(item["text"] for item in group))).most_common(3)
        title = " / ".join(term for term, _ in terms) or f"章节 {len(result) + 1}"
        result.append(
            {
                "title": title,
                "summary": " ".join(item["text"] for item in group),
                "start_ms": group[0]["start_ms"],
                "end_ms": group[-1]["end_ms"],
                "evidence_ordinals": [item["ordinal"] for item in group],
            }
        )
    if len(result) == 1:
        result[0]["title"] = "会议内容"
        result[0]["summary"] = summary["text"]
    return result


def _dedupe(items: list[dict[str, Any]], field: str) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result = []
    for item in items:
        key = re.sub(r"\W+", "", str(item.get(field, "")).lower())
        if key and key not in seen:
            seen.add(key)
            result.append(item)
    return result


def build_intelligence(
    canonical: dict[str, Any],
    *,
    components: dict[str, Any] | None = None,
    source: str = "rules",
    extractor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    values = components or _rule_components(canonical)
    for kind in COMPONENT_KINDS:
        values.setdefault(kind, {} if kind == "summary" else [])
    values["facts"] = _dedupe(values["facts"], "text")
    values["decisions"] = _dedupe(values["decisions"], "text")
    values["action_items"] = _dedupe(values["action_items"], "task")
    values["risks"] = _dedupe(values["risks"], "text")
    values["open_questions"] = _dedupe(values["open_questions"], "text")
    values["topics"] = _dedupe(values["topics"], "text")

    summary = values["summary"]
    chapters = _chapters(canonical, summary)
    keywords = [
        {
            "text": item["text"],
            "count": int(item.get("count", 1)),
            "weight": float(item.get("weight", 1)),
            "evidence_ordinals": item.get("evidence_ordinals", []),
        }
        for item in values["topics"]
    ]
    detailed = {
        "overview": summary["text"],
        "facts": values["facts"],
        "decisions": values["decisions"],
        "action_items": values["action_items"],
        "risks": values["risks"],
        "open_questions": values["open_questions"],
        "evidence_ordinals": sorted(
            {
                ordinal
                for kind in (
                    "facts",
                    "decisions",
                    "action_items",
                    "risks",
                    "open_questions",
                )
                for item in values[kind]
                for ordinal in item.get("evidence_ordinals", [])
            }
        ),
    }
    mindmap = {
        "name": "会议",
        "children": [
            {
                "name": item["title"],
                "start_ms": item["start_ms"],
                "end_ms": item["end_ms"],
                "evidence_ordinals": item["evidence_ordinals"],
                "children": [
                    {
                        "name": segment["text"],
                        "start_ms": segment["start_ms"],
                        "end_ms": segment["end_ms"],
                        "evidence_ordinals": [segment["ordinal"]],
                    }
                    for segment in canonical["segments"]
                    if segment["ordinal"] in item["evidence_ordinals"]
                ][:5],
            }
            for item in chapters
        ],
    }
    artifacts = [
        {"kind": "summary", "source": source, "data": summary},
        {"kind": "detailed_summary", "source": source, "data": detailed},
        {"kind": "facts", "source": source, "data": {"items": values["facts"]}},
        {"kind": "chapters", "source": "derived", "data": {"items": chapters}},
        {"kind": "keywords", "source": source, "data": {"items": keywords}},
        {"kind": "wordcloud", "source": "derived", "data": {"items": keywords}},
        {"kind": "mindmap", "source": "derived", "data": mindmap},
        {
            "kind": "action_items",
            "source": source,
            "data": {"items": values["action_items"]},
        },
        {"kind": "decisions", "source": source, "data": {"items": values["decisions"]}},
        {"kind": "risks", "source": source, "data": {"items": values["risks"]}},
        {
            "kind": "open_questions",
            "source": source,
            "data": {"items": values["open_questions"]},
        },
        {
            "kind": "speaker_stats",
            "source": "derived",
            "data": {"items": _speaker_stats(canonical)},
        },
        {
            "kind": "key_information",
            "source": source,
            "data": {
                "items": values["facts"] + values["decisions"] + values["risks"]
            },
        },
    ]

    memories = []
    fields = (
        ("fact", values["facts"], "text"),
        ("decision", values["decisions"], "text"),
        ("action_item", values["action_items"], "task"),
        ("risk", values["risks"], "text"),
        ("open_question", values["open_questions"], "text"),
        ("topic", values["topics"], "text"),
    )
    metadata = extractor or {"name": source, "version": "3"}
    for kind, items, content_field in fields:
        for item in items:
            memories.append(
                {
                    "kind": kind,
                    "subject": (
                        item.get("owner")
                        if kind == "action_item"
                        else item.get("text")
                        if kind == "topic"
                        else None
                    ),
                    "content": item[content_field],
                    "status": item.get(
                        "status", "observed" if kind in {"fact", "topic"} else "candidate"
                    ),
                    "evidence_ordinals": item.get("evidence_ordinals", []),
                    "extractor": {**metadata, "structured": item},
                }
            )
    return {"artifacts": artifacts, "memories": memories, "components": values}
