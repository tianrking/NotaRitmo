from scripts.interview_corpus_acceptance import (
    ARTICLES,
    REQUIRED_ARTIFACTS,
    RETRIEVAL_CASES,
    simulated_tingwu_payload,
)


def test_public_interview_corpus_has_topics_and_distractors() -> None:
    assert len(ARTICLES) == 6
    assert {item["key"] for item in ARTICLES} == {
        "nasa_shirley",
        "nasa_erb",
        "nih_horigan",
        "nih_grady",
        "npc_solar",
        "ajph_kasich",
    }
    assert len({item["source_url"] for item in ARTICLES}) == len(ARTICLES)
    assert all(len(item["utterances"]) >= 9 for item in ARTICLES)
    assert any(len(item["expected"]) > 1 for item in RETRIEVAL_CASES)
    assert any(not item["expected"] for item in RETRIEVAL_CASES)
    assert len(REQUIRED_ARTIFACTS) == 13


def test_simulated_tingwu_payload_preserves_speakers_timestamps_and_confidence() -> None:
    article = ARTICLES[0]
    payload = simulated_tingwu_payload(article)
    transcription = payload["raw_result"]["Transcription"]["Transcription"]
    paragraphs = transcription["Paragraphs"]

    assert payload["audio_uri"] == article["source_url"]
    assert len(paragraphs) == len(article["utterances"])
    assert {item["SpeakerId"] for item in paragraphs} == {"1", "2"}
    starts = [item["Words"][0]["Start"] for item in paragraphs]
    ends = [item["Words"][0]["End"] for item in paragraphs]
    assert starts == sorted(starts)
    assert all(end > start for start, end in zip(starts, ends, strict=True))
    assert all(0 < item["Words"][0]["Confidence"] <= 1 for item in paragraphs)
