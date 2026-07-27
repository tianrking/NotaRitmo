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


def _confidence(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_tingwu(bundle: dict[str, Any]) -> dict[str, Any]:
    """Convert Tingwu transcription output into provider-neutral canonical speech data.

    Deliberately ignores Summarization, AutoChapters, MeetingAssistance, TextPolish,
    Translation and every other semantic result. Tingwu is an ASR provider only.
    """

    transcription = _unwrap(bundle, "Transcription")
    paragraphs = transcription.get("Paragraphs") or []
    audio_info = transcription.get("AudioInfo") or {}
    speakers: dict[str, dict[str, Any]] = {}
    segments: list[dict[str, Any]] = []
    words: list[dict[str, Any]] = []
    segment_ordinal = 0
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
        grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for index, word in enumerate(paragraph.get("Words") or []):
            grouped[int(word.get("SentenceId", index))].append(word)

        for sentence_id, sentence_words in grouped.items():
            text = "".join(str(word.get("Text", "")) for word in sentence_words).strip()
            if not text:
                continue
            word_confidences = [
                confidence
                for word in sentence_words
                if (confidence := _confidence(word.get("Confidence"))) is not None
            ]
            segments.append(
                {
                    "provider_speaker_id": provider_speaker_id,
                    "paragraph_id": str(paragraph.get("ParagraphId", "")) or None,
                    "sentence_id": sentence_id,
                    "ordinal": segment_ordinal,
                    "start_ms": int(sentence_words[0].get("Start", 0)),
                    "end_ms": int(
                        sentence_words[-1].get(
                            "End", sentence_words[-1].get("Start", 0)
                        )
                    ),
                    "text": text,
                    "confidence": (
                        round(sum(word_confidences) / len(word_confidences), 6)
                        if word_confidences
                        else None
                    ),
                    "overlap": bool(paragraph.get("Overlap", False)),
                }
            )
            for word in sentence_words:
                word_text = str(word.get("Text", "")).strip()
                if not word_text:
                    continue
                words.append(
                    {
                        "segment_ordinal": segment_ordinal,
                        "provider_speaker_id": provider_speaker_id,
                        "provider_word_id": (
                            str(word["Id"]) if word.get("Id") is not None else None
                        ),
                        "ordinal": word_ordinal,
                        "start_ms": int(word.get("Start", 0)),
                        "end_ms": int(word.get("End", word.get("Start", 0))),
                        "text": word_text,
                        "confidence": _confidence(word.get("Confidence")),
                    }
                )
                word_ordinal += 1
            segment_ordinal += 1

    return {
        "duration_ms": audio_info.get("Duration"),
        "speakers": list(speakers.values()),
        "segments": segments,
        "words": words,
    }
