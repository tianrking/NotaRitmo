from app.services.extraction import _cost, _validate_components, canonical_input_hash


def canonical() -> dict:
    return {
        "duration_ms": 2000,
        "speakers": [
            {"provider_speaker_id": "1", "display_name": "Speaker 1"}
        ],
        "segments": [
            {
                "ordinal": 0,
                "start_ms": 0,
                "end_ms": 1000,
                "provider_speaker_id": "1",
                "text": "决定采用灰度发布。",
            },
            {
                "ordinal": 1,
                "start_ms": 1000,
                "end_ms": 2000,
                "provider_speaker_id": "1",
                "text": "李四负责验证。",
            },
        ],
        "words": [],
    }


def test_canonical_hash_is_stable_and_content_addressed() -> None:
    value = canonical()
    first = canonical_input_hash(value)
    second = canonical_input_hash(value)
    assert first == second
    value["segments"][0]["text"] = "决定全量发布。"
    assert canonical_input_hash(value) != first


def test_unified_extraction_discards_items_without_real_evidence() -> None:
    raw = {
        "summary": {"text": "采用灰度发布", "evidence_ordinals": [0, 999]},
        "facts": [],
        "decisions": [
            {"text": "采用灰度发布", "evidence_ordinals": [0]},
            {"text": "虚构决定", "evidence_ordinals": [999]},
        ],
        "action_items": [
            {"task": "李四负责验证", "owner": "李四", "evidence_ordinals": [1]}
        ],
        "risks": [],
        "open_questions": [],
        "topics": [{"text": "灰度发布", "evidence_ordinals": [0]}],
    }
    result = _validate_components(raw, canonical())
    assert result["summary"]["evidence_ordinals"] == [0]
    assert [item["text"] for item in result["decisions"]] == ["采用灰度发布"]
    assert result["action_items"][0]["owner"] == "李四"


def test_cost_uses_configured_per_million_rates(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.extraction.settings.llm_input_cost_per_million", 2.0
    )
    monkeypatch.setattr(
        "app.services.extraction.settings.llm_output_cost_per_million", 8.0
    )
    assert str(
        _cost({"input_tokens": 1000, "output_tokens": 500, "total_tokens": 1500})
    ) == "0.00600000"
