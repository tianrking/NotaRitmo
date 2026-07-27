from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any

import jieba

STOPWORDS = {
    "这个",
    "那个",
    "然后",
    "就是",
    "我们",
    "你们",
    "他们",
    "一个",
    "可以",
    "需要",
    "还是",
    "已经",
    "进行",
    "关于",
    "因为",
    "所以",
    "但是",
    "如果",
    "以及",
    "会议",
}


def _unwrap(bundle: dict[str, Any], key: str) -> dict[str, Any]:
    value = bundle.get(key) or {}
    if isinstance(value, dict) and isinstance(value.get(key), dict):
        return value[key]
    return value if isinstance(value, dict) else {}


def _first_text(value: Any, preferred: tuple[str, ...]) -> str | None:
    if isinstance(value, dict):
        for key in preferred:
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
        for child in value.values():
            found = _first_text(child, preferred)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _first_text(child, preferred)
            if found:
                return found
    return None


def tokenize(text: str) -> list[str]:
    terms: list[str] = []
    for token in jieba.cut(text):
        token = token.strip().lower()
        if not token or token in STOPWORDS:
            continue
        if re.fullmatch(r"[\W_]+", token):
            continue
        if len(token) == 1 and not token.isascii():
            continue
        terms.append(token)
    return terms


def keyword_items(text: str, limit: int = 30) -> list[dict[str, Any]]:
    counts = Counter(tokenize(text))
    maximum = max(counts.values(), default=1)
    return [
        {"text": token, "count": count, "weight": round(count / maximum, 4)}
        for token, count in counts.most_common(limit)
    ]


def _segments(
    transcription: dict[str, Any],
) -> tuple[list[dict], list[dict], list[dict], int | None]:
    paragraphs = transcription.get("Paragraphs") or []
    audio_info = transcription.get("AudioInfo") or {}
    speakers: dict[str, dict] = {}
    segments: list[dict] = []
    canonical_words: list[dict] = []
    ordinal = 0
    word_ordinal = 0

    for paragraph in paragraphs:
        provider_speaker_id = str(paragraph.get("SpeakerId", "unknown"))
        speakers.setdefault(
            provider_speaker_id,
            {
                "provider_speaker_id": provider_speaker_id,
                "display_name": f"Speaker {provider_speaker_id}",
            },
        )
        words = paragraph.get("Words") or []
        grouped: dict[int, list[dict]] = defaultdict(list)
        for index, word in enumerate(words):
            grouped[int(word.get("SentenceId", index))].append(word)

        for sentence_id, sentence_words in grouped.items():
            if not sentence_words:
                continue
            text = "".join(str(word.get("Text", "")) for word in sentence_words).strip()
            if not text:
                continue
            segments.append(
                {
                    "provider_speaker_id": provider_speaker_id,
                    "paragraph_id": str(paragraph.get("ParagraphId", "")) or None,
                    "sentence_id": sentence_id,
                    "ordinal": ordinal,
                    "start_ms": int(sentence_words[0].get("Start", 0)),
                    "end_ms": int(sentence_words[-1].get("End", 0)),
                    "text": text,
                    "confidence": None,
                    "overlap": False,
                }
            )
            for word in sentence_words:
                word_text = str(word.get("Text", "")).strip()
                if not word_text:
                    continue
                confidence = word.get("Confidence")
                canonical_words.append(
                    {
                        "segment_ordinal": ordinal,
                        "provider_speaker_id": provider_speaker_id,
                        "provider_word_id": (
                            str(word["Id"]) if word.get("Id") is not None else None
                        ),
                        "ordinal": word_ordinal,
                        "start_ms": int(word.get("Start", 0)),
                        "end_ms": int(word.get("End", word.get("Start", 0))),
                        "text": word_text,
                        "confidence": float(confidence) if confidence is not None else None,
                    }
                )
                word_ordinal += 1
            ordinal += 1

    return list(speakers.values()), segments, canonical_words, audio_info.get("Duration")


def _provider_artifacts(bundle: dict[str, Any]) -> dict[str, Any]:
    summarization = _unwrap(bundle, "Summarization")
    chapters = _unwrap(bundle, "AutoChapters")
    assistance = _unwrap(bundle, "MeetingAssistance")

    summary = _first_text(
        summarization,
        ("ParagraphSummary", "Summary", "SummaryText", "Text", "Content"),
    )
    chapter_items = chapters.get("Chapters") or chapters.get("AutoChapters") or []
    keywords = assistance.get("Keywords") or assistance.get("KeywordList") or []
    actions = (
        assistance.get("Actions")
        or assistance.get("ActionItems")
        or assistance.get("Tasks")
        or []
    )
    key_information = (
        assistance.get("KeyInformation")
        or assistance.get("KeySentences")
        or assistance.get("ImportantContent")
        or []
    )
    mindmap = summarization.get("MindMap") or summarization.get("MindMapData")

    return {
        "summary": summary,
        "chapters": chapter_items if isinstance(chapter_items, list) else [],
        "provider_keywords": keywords if isinstance(keywords, list) else [],
        "action_items": actions if isinstance(actions, list) else [],
        "key_information": key_information if isinstance(key_information, list) else [],
        "mindmap": mindmap,
    }


def _evidence_ordinals(
    segments: list[dict[str, Any]],
    *,
    text: str | None = None,
    start_ms: int | None = None,
    end_ms: int | None = None,
    limit: int = 3,
) -> list[int]:
    if start_ms is not None or end_ms is not None:
        start = start_ms if start_ms is not None else 0
        end = end_ms if end_ms is not None else 2**63 - 1
        matched = [
            segment["ordinal"]
            for segment in segments
            if segment["end_ms"] >= start and segment["start_ms"] <= end
        ]
        if matched:
            return matched[:limit]
    terms = tokenize(text or "")
    ranked: list[tuple[int, int]] = []
    for segment in segments:
        score = sum(1 for term in terms if term in segment["text"].lower())
        if score:
            ranked.append((score, segment["ordinal"]))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return [ordinal for _, ordinal in ranked[:limit]]


def _normalize_chapters(
    chapters: list[Any], segments: list[dict[str, Any]], summary: str
) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for index, item in enumerate(chapters):
        if not isinstance(item, dict):
            continue
        title = (
            item.get("Title")
            or item.get("title")
            or item.get("Headline")
            or f"章节 {index + 1}"
        )
        chapter_summary = (
            item.get("Summary")
            or item.get("summary")
            or item.get("Content")
            or item.get("Text")
            or ""
        )
        start = int(item.get("Start", item.get("start_ms", 0)) or 0)
        end = int(item.get("End", item.get("end_ms", start)) or start)
        values.append(
            {
                "title": str(title),
                "summary": str(chapter_summary),
                "start_ms": start,
                "end_ms": end,
                "evidence_ordinals": _evidence_ordinals(
                    segments, text=str(chapter_summary), start_ms=start, end_ms=end, limit=20
                ),
            }
        )
    if values:
        return values
    return [
        {
            "title": "会议内容",
            "summary": summary,
            "start_ms": segments[0]["start_ms"] if segments else 0,
            "end_ms": segments[-1]["end_ms"] if segments else 0,
            "evidence_ordinals": [item["ordinal"] for item in segments],
        }
    ]


def _provider_actions(
    actions: list[Any], segments: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for item in actions:
        if isinstance(item, str):
            task, owner, due_date = item, None, None
        elif isinstance(item, dict):
            task = (
                item.get("Task")
                or item.get("Content")
                or item.get("Text")
                or item.get("Action")
            )
            owner = item.get("Owner") or item.get("Assignee") or item.get("Responsible")
            due_date = item.get("DueDate") or item.get("Deadline")
        else:
            continue
        if not task:
            continue
        evidence_text = " ".join(str(value) for value in (task, owner, due_date) if value)
        values.append(
            {
                "task": str(task),
                "owner": str(owner) if owner else None,
                "due_date": str(due_date) if due_date else None,
                "status": "open",
                "confidence": 1.0,
                "evidence_ordinals": _evidence_ordinals(
                    segments, text=evidence_text, limit=3
                ),
            }
        )
    return values


def _rule_facts(segments: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    markers = {
        "decisions": ("决定", "确定", "结论", "改到", "改为", "采用", "最终", "统一"),
        "action_items": ("负责", "待办", "需要完成", "跟进", "截止", "安排"),
        "risks": ("风险", "可能失败", "阻塞", "隐患", "延迟", "来不及", "不稳定"),
        "open_questions": ("待确认", "还没定", "未确定", "需要讨论", "问题是", "？", "?"),
    }
    values: dict[str, list[dict[str, Any]]] = {key: [] for key in markers}
    for segment in segments:
        text = segment["text"]
        evidence = [segment["ordinal"]]
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
        if any(marker in text for marker in markers["risks"]):
            values["risks"].append(
                {
                    "text": text,
                    "status": "open",
                    "confidence": 0.7,
                    "evidence_ordinals": evidence,
                }
            )
        if any(marker in text for marker in markers["open_questions"]):
            values["open_questions"].append(
                {
                    "text": text,
                    "status": "open",
                    "confidence": 0.68,
                    "evidence_ordinals": evidence,
                }
            )
    return values


def _deduplicate(items: list[dict[str, Any]], field: str) -> list[dict[str, Any]]:
    seen: set[str] = set()
    values = []
    for item in items:
        key = re.sub(r"\W+", "", str(item.get(field, "")).lower())
        if not key or key in seen:
            continue
        seen.add(key)
        values.append(item)
    return values


def _speaker_stats(
    speakers: list[dict[str, Any]], segments: list[dict[str, Any]], duration_ms: int | None
) -> list[dict[str, Any]]:
    stats: list[dict[str, Any]] = []
    total = max(duration_ms or sum(s["end_ms"] - s["start_ms"] for s in segments), 1)
    for speaker in speakers:
        own = [
            segment
            for segment in segments
            if segment["provider_speaker_id"] == speaker["provider_speaker_id"]
        ]
        speaking_ms = sum(max(item["end_ms"] - item["start_ms"], 0) for item in own)
        stats.append(
            {
                **speaker,
                "segment_count": len(own),
                "speaking_ms": speaking_ms,
                "share": round(speaking_ms / total, 4),
                "character_count": sum(len(item["text"]) for item in own),
                "evidence_ordinals": [item["ordinal"] for item in own],
            }
        )
    return stats


def normalize_tingwu(bundle: dict[str, Any]) -> dict[str, Any]:
    transcription = _unwrap(bundle, "Transcription")
    speakers, segments, words, duration_ms = _segments(transcription)
    transcript_text = "\n".join(segment["text"] for segment in segments)
    provider = _provider_artifacts(bundle)

    keywords = keyword_items(transcript_text)
    if provider["provider_keywords"]:
        provider_words = []
        for item in provider["provider_keywords"]:
            if isinstance(item, str):
                provider_words.append({"text": item, "count": 1, "weight": 1.0})
            elif isinstance(item, dict):
                text = item.get("Text") or item.get("Keyword") or item.get("Word")
                if text:
                    provider_words.append(
                        {
                            "text": text,
                            "count": item.get("Count", 1),
                            "weight": item.get("Weight", 1.0),
                        }
                    )
        if provider_words:
            keywords = provider_words

    fallback_summary = " ".join(segment["text"] for segment in segments[:8])
    summary = provider["summary"] or fallback_summary or "暂无可用摘要。"
    chapters = _normalize_chapters(provider["chapters"], segments, summary)
    facts = _rule_facts(segments)
    provider_actions = _provider_actions(provider["action_items"], segments)
    action_items = _deduplicate(provider_actions + facts["action_items"], "task")
    summary_evidence = _evidence_ordinals(segments, text=summary, limit=8)

    mindmap = provider["mindmap"] or {
        "name": "会议",
        "children": [
            {
                "name": str(
                    chapter.get("title")
                    or f"章节 {index + 1}"
                ),
                "start_ms": chapter.get("start_ms", 0),
                "end_ms": chapter.get("end_ms", 0),
                "evidence_ordinals": chapter.get("evidence_ordinals", []),
                "children": [
                    {
                        "name": segment["text"],
                        "start_ms": segment["start_ms"],
                        "end_ms": segment["end_ms"],
                        "evidence_ordinals": [segment["ordinal"]],
                    }
                    for segment in segments
                    if segment["ordinal"] in chapter.get("evidence_ordinals", [])
                ][:5],
            }
            for index, chapter in enumerate(chapters)
        ],
    }

    artifacts = [
        {
            "kind": "summary",
            "source": "tingwu" if provider["summary"] else "fallback",
            "data": {"text": summary, "evidence_ordinals": summary_evidence},
        },
        {
            "kind": "detailed_summary",
            "source": "derived",
            "data": {
                "overview": summary,
                "decisions": facts["decisions"],
                "action_items": action_items,
                "risks": facts["risks"],
                "open_questions": facts["open_questions"],
                "evidence_ordinals": sorted(
                    {
                        ordinal
                        for group in (
                            facts["decisions"],
                            action_items,
                            facts["risks"],
                            facts["open_questions"],
                        )
                        for item in group
                        for ordinal in item["evidence_ordinals"]
                    }
                ),
            },
        },
        {
            "kind": "chapters",
            "source": "tingwu" if provider["chapters"] else "fallback",
            "data": {"items": chapters},
        },
        {"kind": "keywords", "source": "tingwu+local", "data": {"items": keywords}},
        {"kind": "wordcloud", "source": "derived", "data": {"items": keywords}},
        {
            "kind": "mindmap",
            "source": "tingwu" if provider["mindmap"] else "derived",
            "data": mindmap,
        },
        {
            "kind": "action_items",
            "source": "tingwu+rules" if provider_actions else "rules",
            "data": {"items": action_items},
        },
        {"kind": "decisions", "source": "rules", "data": {"items": facts["decisions"]}},
        {"kind": "risks", "source": "rules", "data": {"items": facts["risks"]}},
        {
            "kind": "open_questions",
            "source": "rules",
            "data": {"items": facts["open_questions"]},
        },
        {
            "kind": "speaker_stats",
            "source": "derived",
            "data": {"items": _speaker_stats(speakers, segments, duration_ms)},
        },
        {
            "kind": "key_information",
            "source": "tingwu",
            "data": {"items": provider["key_information"]},
        },
    ]

    memories: list[dict[str, Any]] = []
    for kind, values, content_field in (
        ("decision", facts["decisions"], "text"),
        ("action_item", action_items, "task"),
        ("risk", facts["risks"], "text"),
        ("open_question", facts["open_questions"], "text"),
    ):
        for item in values:
            subject = item.get("owner") if kind == "action_item" else None
            memories.append(
                {
                    "kind": kind,
                    "subject": subject,
                    "content": item[content_field],
                    "status": "confirmed" if item in provider_actions else "candidate",
                    "evidence_ordinals": item["evidence_ordinals"],
                    "extractor": {
                        "name": "tingwu" if item in provider_actions else "rules",
                        "version": "2",
                        "confidence": item.get("confidence"),
                        "structured": item,
                    },
                }
            )
    for item in keywords[:15]:
        memories.append(
            {
                "kind": "topic",
                "subject": item["text"],
                "content": item["text"],
                "status": "observed",
                "evidence_ordinals": _evidence_ordinals(
                    segments, text=item["text"], limit=5
                ),
                "extractor": {
                    "name": "tingwu+local-keywords",
                    "version": "2",
                    "weight": item.get("weight"),
                    "count": item.get("count"),
                },
            }
        )

    return {
        "duration_ms": duration_ms,
        "speakers": speakers,
        "segments": segments,
        "words": words,
        "artifacts": artifacts,
        "memories": memories,
    }
