import json
from pathlib import Path

from app.services.intelligence import build_intelligence
from app.services.normalizer import normalize_tingwu


def load_fixture(name: str) -> dict:
    root = Path(__file__).resolve().parents[1]
    return json.loads((root / "fixtures" / name).read_text(encoding="utf-8"))


def test_normalize_official_tingwu_shape() -> None:
    payload = load_fixture("tingwu_meeting_01.json")
    normalized = normalize_tingwu(payload["raw_result"])

    assert normalized["duration_ms"] == 180000
    assert len(normalized["speakers"]) == 2
    assert len(normalized["segments"]) == 4
    assert normalized["segments"][1]["start_ms"] == 3000
    assert normalized["segments"][1]["text"] == "我们决定Android首版采用分包传输。"

    assert set(normalized) == {"duration_ms", "speakers", "segments", "words"}
    intelligence = build_intelligence(normalized)
    artifacts = {item["kind"]: item for item in intelligence["artifacts"]}
    assert artifacts["summary"]["source"] == "rules"
    assert artifacts["wordcloud"]["data"]["items"]
    assert artifacts["mindmap"]["data"]["name"] == "会议"
    assert any(item["kind"] == "decision" for item in intelligence["memories"])
    assert any(item["kind"] == "action_item" for item in intelligence["memories"])


def test_fallback_artifacts_are_still_generated() -> None:
    bundle = {
        "Transcription": {
            "Transcription": {
                "AudioInfo": {"Duration": 1000},
                "Paragraphs": [
                    {
                        "ParagraphId": "p",
                        "SpeakerId": "1",
                        "Words": [
                            {
                                "SentenceId": 1,
                                "Start": 0,
                                "End": 1000,
                                "Text": "测试会议包含产品计划和发布日期。",
                            }
                        ],
                    }
                ],
            }
        }
    }
    normalized = normalize_tingwu(bundle)
    intelligence = build_intelligence(normalized)
    artifacts = {item["kind"]: item for item in intelligence["artifacts"]}
    assert artifacts["summary"]["source"] == "rules"
    assert artifacts["keywords"]["data"]["items"]
    assert artifacts["chapters"]["data"]["items"]
