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


def _segments(transcription: dict[str, Any]) -> tuple[list[dict], list[dict], int | None]:
    paragraphs = transcription.get("Paragraphs") or []
    audio_info = transcription.get("AudioInfo") or {}
    speakers: dict[str, dict] = {}
    segments: list[dict] = []
    ordinal = 0

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
            ordinal += 1

    return list(speakers.values()), segments, audio_info.get("Duration")


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


def normalize_tingwu(bundle: dict[str, Any]) -> dict[str, Any]:
    transcription = _unwrap(bundle, "Transcription")
    speakers, segments, duration_ms = _segments(transcription)
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

    fallback_summary = " ".join(segment["text"] for segment in segments[:5])
    summary = provider["summary"] or fallback_summary or "暂无可用摘要。"

    chapters = provider["chapters"]
    if not chapters:
        chapters = [
            {
                "title": "会议内容",
                "summary": summary,
                "start_ms": segments[0]["start_ms"] if segments else 0,
                "end_ms": segments[-1]["end_ms"] if segments else 0,
            }
        ]

    mindmap = provider["mindmap"] or {
        "name": "会议",
        "children": [
            {
                "name": str(
                    chapter.get("Title")
                    or chapter.get("title")
                    or chapter.get("Headline")
                    or f"章节 {index + 1}"
                ),
                "children": [],
            }
            for index, chapter in enumerate(chapters)
        ],
    }

    artifacts = [
        {
            "kind": "summary",
            "source": "tingwu" if provider["summary"] else "fallback",
            "data": {"text": summary},
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
        {"kind": "action_items", "source": "tingwu", "data": {"items": provider["action_items"]}},
        {
            "kind": "key_information",
            "source": "tingwu",
            "data": {"items": provider["key_information"]},
        },
    ]

    memories: list[dict[str, Any]] = []
    decision_markers = ("决定", "确定", "改到", "改为", "采用", "最终")
    action_markers = ("负责", "待办", "需要完成", "跟进", "截止")
    for segment in segments:
        kind = None
        if any(marker in segment["text"] for marker in decision_markers):
            kind = "decision"
        elif any(marker in segment["text"] for marker in action_markers):
            kind = "action_item"
        if kind:
            memories.append(
                {
                    "kind": kind,
                    "subject": None,
                    "content": segment["text"],
                    "status": "candidate",
                    "evidence_ordinals": [segment["ordinal"]],
                    "extractor": {"name": "rule-baseline", "version": "1"},
                }
            )

    return {
        "duration_ms": duration_ms,
        "speakers": speakers,
        "segments": segments,
        "artifacts": artifacts,
        "memories": memories,
    }
