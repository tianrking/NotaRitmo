from __future__ import annotations

import tempfile
import threading
import wave
from array import array
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import numpy as np
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import (
    Meeting,
    Person,
    Segment,
    Speaker,
    SpeakerMatchCandidate,
    VoiceprintProfile,
    VoiceprintSample,
)
from app.services.storage import download_file, parse_minio_uri

_extractor: Any | None = None
_extractor_lock = threading.Lock()


def _get_extractor() -> Any:
    global _extractor
    if not settings.speaker_embedding_enabled:
        raise RuntimeError("speaker embedding is disabled")
    model = Path(settings.speaker_embedding_model)
    if not model.is_file():
        raise RuntimeError(f"speaker embedding model not found: {model}")
    with _extractor_lock:
        if _extractor is None:
            import sherpa_onnx

            config = sherpa_onnx.SpeakerEmbeddingExtractorConfig(
                model=str(model),
                num_threads=settings.speaker_embedding_threads,
                debug=False,
                provider="cpu",
            )
            if not config.validate():
                raise RuntimeError(f"invalid speaker embedding config: {config}")
            _extractor = sherpa_onnx.SpeakerEmbeddingExtractor(config)
            if _extractor.dim != settings.speaker_embedding_dimensions:
                raise RuntimeError(
                    f"speaker model dimension {_extractor.dim} does not match "
                    f"SPEAKER_EMBEDDING_DIMENSIONS={settings.speaker_embedding_dimensions}"
                )
    return _extractor


def _normalized(vector: np.ndarray) -> list[float]:
    norm = float(np.linalg.norm(vector))
    if norm <= 1e-12:
        raise ValueError("speaker embedding has zero norm")
    return (vector / norm).astype(np.float32).tolist()


def _cosine(left: list[float], right: list[float]) -> float:
    a = np.asarray(left, dtype=np.float32)
    b = np.asarray(right, dtype=np.float32)
    denominator = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float(np.dot(a, b) / denominator) if denominator else 0.0


def _speaker_audio(
    db: Session, meeting: Meeting, speaker: Speaker
) -> tuple[np.ndarray, list[dict[str, int]], int]:
    if not meeting.normalized_audio_uri:
        raise ValueError("meeting has no normalized audio")
    segments = list(
        db.scalars(
            select(Segment)
            .where(
                Segment.meeting_id == meeting.id,
                Segment.speaker_id == speaker.id,
            )
            .order_by(Segment.start_ms)
        ).all()
    )
    intervals = []
    used_ms = 0
    for segment in segments:
        duration = max(segment.end_ms - segment.start_ms, 0)
        if duration <= 0:
            continue
        remaining = settings.speaker_max_sample_ms - used_ms
        if remaining <= 0:
            break
        end_ms = segment.start_ms + min(duration, remaining)
        intervals.append({"start_ms": segment.start_ms, "end_ms": end_ms})
        used_ms += end_ms - segment.start_ms
    if used_ms < settings.speaker_min_enrollment_ms:
        raise ValueError(
            f"speaker has only {used_ms}ms usable audio; "
            f"minimum is {settings.speaker_min_enrollment_ms}ms"
        )

    with tempfile.TemporaryDirectory(prefix="notaritmo-voice-") as directory:
        path = Path(directory) / "meeting.wav"
        download_file(parse_minio_uri(meeting.normalized_audio_uri), path)
        with wave.open(str(path), "rb") as wav:
            if (
                wav.getframerate() != 16000
                or wav.getnchannels() != 1
                or wav.getsampwidth() != 2
            ):
                raise ValueError("voiceprint source must be normalized 16k mono PCM16")
            raw = array("h", wav.readframes(wav.getnframes()))
    chunks = [
        raw[round(item["start_ms"] * 16) : round(item["end_ms"] * 16)]
        for item in intervals
    ]
    joined = array("h")
    for chunk in chunks:
        joined.extend(chunk)
    samples = np.asarray(joined, dtype=np.float32) / 32768.0
    return np.ascontiguousarray(samples), intervals, used_ms


def speaker_embedding(
    db: Session, meeting: Meeting, speaker: Speaker
) -> tuple[list[float], list[dict[str, int]], int]:
    samples, intervals, duration_ms = _speaker_audio(db, meeting, speaker)
    extractor = _get_extractor()
    stream = extractor.create_stream()
    stream.accept_waveform(sample_rate=16000, waveform=samples)
    stream.input_finished()
    if not extractor.is_ready(stream):
        raise ValueError("speaker audio is too short for embedding extraction")
    vector = np.asarray(extractor.compute(stream), dtype=np.float32)
    return _normalized(vector), intervals, duration_ms


def enroll_voiceprint(
    db: Session,
    *,
    meeting_id: UUID,
    speaker_id: UUID,
    person_id: UUID | None,
    display_name: str | None,
    tenant_id: UUID,
    user_id: UUID,
) -> dict[str, Any]:
    meeting = db.scalar(
        select(Meeting).where(Meeting.id == meeting_id, Meeting.tenant_id == tenant_id)
    )
    speaker = db.scalar(
        select(Speaker)
        .join(Meeting, Speaker.meeting_id == Meeting.id)
        .where(
            Speaker.id == speaker_id,
            Speaker.meeting_id == meeting_id,
            Meeting.tenant_id == tenant_id,
        )
    )
    if not meeting or not speaker:
        raise ValueError("meeting or speaker not found in tenant")
    person = (
        db.scalar(
            select(Person).where(Person.id == person_id, Person.tenant_id == tenant_id)
        )
        if person_id
        else None
    )
    if person_id and not person:
        raise ValueError("person not found in tenant")
    if person is None:
        name = (display_name or "").strip()
        if not name:
            raise ValueError("display_name is required for a new person")
        person = Person(
            tenant_id=tenant_id,
            created_by=user_id,
            display_name=name,
            status="ACTIVE",
        )
        db.add(person)
        db.flush()

    embedding, intervals, duration_ms = speaker_embedding(db, meeting, speaker)
    profile = db.scalar(
        select(VoiceprintProfile).where(
            VoiceprintProfile.tenant_id == tenant_id,
            VoiceprintProfile.person_id == person.id,
            VoiceprintProfile.model_version
            == settings.speaker_embedding_model_version,
        )
    )
    if profile:
        count = profile.enrollment_count
        averaged = (
            np.asarray(list(profile.embedding), dtype=np.float32) * count
            + np.asarray(embedding, dtype=np.float32)
        ) / (count + 1)
        profile.embedding = _normalized(averaged)
        profile.enrollment_count = count + 1
        profile.status = "ACTIVE"
    else:
        profile = VoiceprintProfile(
            tenant_id=tenant_id,
            person_id=person.id,
            model_version=settings.speaker_embedding_model_version,
            embedding=embedding,
            enrollment_count=1,
            status="ACTIVE",
        )
        db.add(profile)
        db.flush()
    db.add(
        VoiceprintSample(
            tenant_id=tenant_id,
            profile_id=profile.id,
            meeting_id=meeting.id,
            speaker_id=speaker.id,
            intervals=intervals,
            embedding=embedding,
            duration_ms=duration_ms,
            quality=meeting.audio_preflight or {},
            audio_hash=meeting.audio_input_hash,
        )
    )
    speaker.person_id = person.id
    speaker.display_name = person.display_name
    speaker.identity_confidence = 1.0
    speaker.identity_source = "voiceprint_enrollment"
    db.commit()
    match_tenant_speakers(db, tenant_id=tenant_id, exclude_speaker_id=speaker.id)
    return {
        "person_id": str(person.id),
        "profile_id": str(profile.id),
        "speaker_id": str(speaker.id),
        "display_name": person.display_name,
        "enrollment_count": profile.enrollment_count,
        "duration_ms": duration_ms,
        "model_version": profile.model_version,
    }


def match_meeting_speakers(
    db: Session, meeting: Meeting, *, exclude_speaker_id: UUID | None = None
) -> dict[str, Any]:
    profiles = list(
        db.scalars(
            select(VoiceprintProfile).where(
                VoiceprintProfile.tenant_id == meeting.tenant_id,
                VoiceprintProfile.status == "ACTIVE",
                VoiceprintProfile.model_version
                == settings.speaker_embedding_model_version,
            )
        ).all()
    )
    if not profiles or not meeting.normalized_audio_uri:
        return {"meeting_id": str(meeting.id), "candidates": 0, "skipped": True}
    speakers = list(
        db.scalars(
            select(Speaker).where(
                Speaker.meeting_id == meeting.id,
                Speaker.person_id.is_(None),
            )
        ).all()
    )
    created = 0
    for speaker in speakers:
        if speaker.id == exclude_speaker_id:
            continue
        try:
            embedding, _, _ = speaker_embedding(db, meeting, speaker)
        except ValueError:
            continue
        ranked = sorted(
            (
                (_cosine(embedding, list(profile.embedding)), profile)
                for profile in profiles
            ),
            key=lambda item: item[0],
            reverse=True,
        )[:3]
        for similarity, profile in ranked:
            if similarity < settings.speaker_match_threshold:
                continue
            existing = db.scalar(
                select(SpeakerMatchCandidate).where(
                    SpeakerMatchCandidate.speaker_id == speaker.id,
                    SpeakerMatchCandidate.profile_id == profile.id,
                )
            )
            if existing:
                if existing.status == "PENDING":
                    existing.similarity = similarity
                continue
            db.add(
                SpeakerMatchCandidate(
                    tenant_id=meeting.tenant_id,
                    speaker_id=speaker.id,
                    profile_id=profile.id,
                    person_id=profile.person_id,
                    similarity=similarity,
                    status="PENDING",
                    model_version=profile.model_version,
                )
            )
            created += 1
    db.commit()
    return {"meeting_id": str(meeting.id), "candidates": created, "skipped": False}


def match_tenant_speakers(
    db: Session, *, tenant_id: UUID, exclude_speaker_id: UUID | None = None
) -> dict[str, Any]:
    meetings = list(
        db.scalars(
            select(Meeting).where(
                Meeting.tenant_id == tenant_id,
                Meeting.normalized_audio_uri.is_not(None),
            )
        ).all()
    )
    results = [
        match_meeting_speakers(
            db, meeting, exclude_speaker_id=exclude_speaker_id
        )
        for meeting in meetings
    ]
    return {
        "meetings": len(results),
        "candidates": sum(item["candidates"] for item in results),
    }


def list_candidates(db: Session, *, tenant_id: UUID) -> list[dict[str, Any]]:
    rows = db.execute(
        select(SpeakerMatchCandidate, Speaker, Person, Meeting)
        .join(Speaker, SpeakerMatchCandidate.speaker_id == Speaker.id)
        .join(Person, SpeakerMatchCandidate.person_id == Person.id)
        .join(Meeting, Speaker.meeting_id == Meeting.id)
        .where(SpeakerMatchCandidate.tenant_id == tenant_id)
        .order_by(
            SpeakerMatchCandidate.status,
            SpeakerMatchCandidate.similarity.desc(),
        )
    ).all()
    return [
        {
            "id": str(candidate.id),
            "meeting_id": str(meeting.id),
            "meeting_title": meeting.title,
            "speaker_id": str(speaker.id),
            "provider_speaker_id": speaker.provider_speaker_id,
            "person_id": str(person.id),
            "person_name": person.display_name,
            "similarity": round(candidate.similarity, 6),
            "status": candidate.status,
            "model_version": candidate.model_version,
            "created_at": candidate.created_at.isoformat(),
        }
        for candidate, speaker, person, meeting in rows
    ]


def review_candidate(
    db: Session,
    *,
    candidate_id: UUID,
    accept: bool,
    tenant_id: UUID,
    user_id: UUID,
) -> dict[str, Any]:
    row = db.execute(
        select(SpeakerMatchCandidate, Speaker, Person)
        .join(Speaker, SpeakerMatchCandidate.speaker_id == Speaker.id)
        .join(Person, SpeakerMatchCandidate.person_id == Person.id)
        .where(
            SpeakerMatchCandidate.id == candidate_id,
            SpeakerMatchCandidate.tenant_id == tenant_id,
            Person.tenant_id == tenant_id,
        )
    ).one_or_none()
    if not row:
        raise ValueError("candidate not found in tenant")
    candidate, speaker, person = row
    candidate.status = "CONFIRMED" if accept else "REJECTED"
    candidate.reviewed_by = user_id
    candidate.reviewed_at = datetime.now(UTC)
    if accept:
        speaker.person_id = person.id
        speaker.display_name = person.display_name
        speaker.identity_confidence = candidate.similarity
        speaker.identity_source = "voiceprint_user_confirmed"
        for other in db.scalars(
            select(SpeakerMatchCandidate).where(
                SpeakerMatchCandidate.speaker_id == speaker.id,
                SpeakerMatchCandidate.id != candidate.id,
                SpeakerMatchCandidate.status == "PENDING",
            )
        ).all():
            other.status = "REJECTED"
            other.reviewed_by = user_id
            other.reviewed_at = candidate.reviewed_at
    db.commit()
    return {
        "candidate_id": str(candidate.id),
        "status": candidate.status,
        "speaker_id": str(speaker.id),
        "person_id": str(person.id),
        "person_name": person.display_name,
    }


def delete_voiceprint_profile(
    db: Session, *, profile_id: UUID, tenant_id: UUID
) -> bool:
    profile = db.scalar(
        select(VoiceprintProfile).where(
            VoiceprintProfile.id == profile_id,
            VoiceprintProfile.tenant_id == tenant_id,
        )
    )
    if not profile:
        return False
    person_id = profile.person_id
    db.execute(
        delete(SpeakerMatchCandidate).where(
            SpeakerMatchCandidate.profile_id == profile.id,
            SpeakerMatchCandidate.tenant_id == tenant_id,
        )
    )
    db.delete(profile)
    for speaker in db.scalars(
        select(Speaker)
        .join(Meeting, Speaker.meeting_id == Meeting.id)
        .where(
            Speaker.person_id == person_id,
            Speaker.identity_source.in_(
                ("voiceprint_enrollment", "voiceprint_user_confirmed")
            ),
            Meeting.tenant_id == tenant_id,
        )
    ).all():
        speaker.person_id = None
        speaker.display_name = f"Speaker {speaker.provider_speaker_id}"
        speaker.identity_confidence = None
        speaker.identity_source = None
    db.commit()
    return True


def delete_person(db: Session, *, person_id: UUID, tenant_id: UUID) -> bool:
    person = db.scalar(
        select(Person).where(Person.id == person_id, Person.tenant_id == tenant_id)
    )
    if not person:
        return False
    for profile in list(
        db.scalars(
            select(VoiceprintProfile).where(
                VoiceprintProfile.person_id == person.id,
                VoiceprintProfile.tenant_id == tenant_id,
            )
        ).all()
    ):
        delete_voiceprint_profile(db, profile_id=profile.id, tenant_id=tenant_id)
    db.delete(person)
    db.commit()
    return True


def list_people(db: Session, *, tenant_id: UUID) -> list[dict[str, Any]]:
    rows = db.execute(
        select(Person, VoiceprintProfile)
        .outerjoin(
            VoiceprintProfile,
            (VoiceprintProfile.person_id == Person.id)
            & (VoiceprintProfile.status == "ACTIVE"),
        )
        .where(Person.tenant_id == tenant_id)
        .order_by(Person.display_name)
    ).all()
    return [
        {
            "id": str(person.id),
            "display_name": person.display_name,
            "status": person.status,
            "profile_id": str(profile.id) if profile else None,
            "model_version": profile.model_version if profile else None,
            "enrollment_count": profile.enrollment_count if profile else 0,
        }
        for person, profile in rows
    ]
