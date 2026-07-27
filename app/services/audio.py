from __future__ import annotations

import hashlib
import json
import math
import shutil
import statistics
import subprocess
import tempfile
import wave
from array import array
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Meeting, UploadSession
from app.services.storage import download_file, parse_minio_uri, put_file


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _probe(path: Path) -> dict[str, Any]:
    command = [
        settings.ffprobe_binary,
        "-v",
        "error",
        "-show_format",
        "-show_streams",
        "-of",
        "json",
        str(path),
    ]
    result = subprocess.run(
        command, check=False, capture_output=True, text=True, timeout=120
    )
    if result.returncode != 0:
        raise ValueError(f"ffprobe rejected media: {result.stderr.strip()[:1000]}")
    payload = json.loads(result.stdout)
    audio_streams = [
        stream for stream in payload.get("streams", []) if stream.get("codec_type") == "audio"
    ]
    if not audio_streams:
        raise ValueError("uploaded media has no audio stream")
    stream = audio_streams[0]
    format_info = payload.get("format") or {}
    duration = float(format_info.get("duration") or stream.get("duration") or 0)
    if duration <= 0:
        raise ValueError("media duration is missing or zero")
    if duration > settings.audio_max_duration_seconds:
        raise ValueError(
            f"media duration {duration:.1f}s exceeds limit "
            f"{settings.audio_max_duration_seconds}s"
        )
    return {
        "format_name": format_info.get("format_name"),
        "format_long_name": format_info.get("format_long_name"),
        "duration_ms": round(duration * 1000),
        "size_bytes": int(format_info.get("size") or path.stat().st_size),
        "bit_rate": int(format_info.get("bit_rate") or 0),
        "codec": stream.get("codec_name"),
        "sample_rate": int(stream.get("sample_rate") or 0),
        "channels": int(stream.get("channels") or 0),
        "channel_layout": stream.get("channel_layout"),
    }


def _normalize(source: Path, destination: Path, denoise: bool) -> None:
    command = [
        settings.ffmpeg_binary,
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(source),
        "-map",
        "0:a:0",
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
    ]
    if denoise:
        command.extend(["-af", "afftdn=nr=12:nf=-40"])
    command.extend(["-c:a", "pcm_s16le", str(destination)])
    result = subprocess.run(
        command, check=False, capture_output=True, text=True, timeout=3600
    )
    if result.returncode != 0:
        raise ValueError(f"ffmpeg normalization failed: {result.stderr.strip()[:1000]}")


def _audio_quality(path: Path) -> dict[str, Any]:
    with wave.open(str(path), "rb") as wav:
        if wav.getnchannels() != 1 or wav.getsampwidth() != 2:
            raise ValueError("normalized audio is not mono PCM16")
        sample_rate = wav.getframerate()
        samples = array("h", wav.readframes(wav.getnframes()))
    if not samples:
        raise ValueError("normalized audio contains no samples")

    normalized = [sample / 32768.0 for sample in samples]
    frame_size = max(1, round(sample_rate * 0.03))
    frame_rms = []
    for start in range(0, len(normalized), frame_size):
        frame = normalized[start : start + frame_size]
        if not frame:
            continue
        frame_rms.append(math.sqrt(sum(value * value for value in frame) / len(frame)))
    sorted_rms = sorted(frame_rms)
    noise_floor = sorted_rms[max(0, round(len(sorted_rms) * 0.2) - 1)]
    threshold = max(noise_floor * 3.0, 10 ** (-45 / 20))
    voiced = [value for value in frame_rms if value >= threshold]
    speech_ratio = len(voiced) / max(len(frame_rms), 1)
    overall_rms = math.sqrt(sum(value * value for value in normalized) / len(normalized))
    rms_dbfs = 20 * math.log10(max(overall_rms, 1e-9))
    peak = max(abs(value) for value in normalized)
    clipping_ratio = sum(1 for value in normalized if abs(value) >= 0.999) / len(
        normalized
    )
    voiced_level = statistics.median(voiced) if voiced else overall_rms
    snr_db = 20 * math.log10(
        max(voiced_level, 1e-9) / max(noise_floor, 1e-9)
    )
    dc_offset = sum(normalized) / len(normalized)

    score = 100.0
    flags = []
    if speech_ratio < 0.05:
        score -= 45
        flags.append("very_low_speech_ratio")
    elif speech_ratio < 0.2:
        score -= 20
        flags.append("low_speech_ratio")
    if rms_dbfs < -38:
        score -= 20
        flags.append("very_quiet")
    elif rms_dbfs < -28:
        score -= 8
        flags.append("quiet")
    if clipping_ratio > 0.01:
        score -= 25
        flags.append("clipping")
    elif clipping_ratio > 0.001:
        score -= 10
        flags.append("some_clipping")
    if snr_db < 6:
        score -= 25
        flags.append("low_snr")
    elif snr_db < 12:
        score -= 10
        flags.append("moderate_snr")
    if abs(dc_offset) > 0.05:
        score -= 10
        flags.append("dc_offset")
    return {
        "sample_rate": sample_rate,
        "channels": 1,
        "duration_ms": round(len(normalized) / sample_rate * 1000),
        "speech_ratio": round(speech_ratio, 4),
        "silence_ratio": round(1 - speech_ratio, 4),
        "rms_dbfs": round(rms_dbfs, 2),
        "peak": round(peak, 5),
        "clipping_ratio": round(clipping_ratio, 6),
        "snr_db": round(snr_db, 2),
        "dc_offset": round(dc_offset, 6),
        "quality_score": max(0, min(100, round(score))),
        "quality_flags": flags,
        "vad": {
            "algorithm": "adaptive-energy-v1",
            "frame_ms": 30,
            "threshold_dbfs": round(20 * math.log10(max(threshold, 1e-9)), 2),
        },
    }


def _download_http(uri: str, destination: Path) -> None:
    with httpx.stream("GET", uri, follow_redirects=True, timeout=300) as response:
        response.raise_for_status()
        declared = int(response.headers.get("content-length") or 0)
        if declared > settings.audio_max_bytes:
            raise ValueError("remote media exceeds AUDIO_MAX_BYTES")
        total = 0
        with destination.open("wb") as output:
            for chunk in response.iter_bytes(1024 * 1024):
                total += len(chunk)
                if total > settings.audio_max_bytes:
                    raise ValueError("remote media exceeds AUDIO_MAX_BYTES")
                output.write(chunk)


def prepare_meeting_audio(db: Session, meeting: Meeting) -> dict[str, Any]:
    if meeting.audio_preflight and meeting.normalized_audio_uri:
        return {"status": "CACHED", **meeting.audio_preflight}
    if not meeting.audio_uri:
        raise ValueError("meeting audio_uri is missing")

    temporary_root = Path(tempfile.mkdtemp(prefix=f"notaritmo-{meeting.id}-"))
    try:
        source = temporary_root / "source-media"
        if meeting.audio_uri.startswith("minio://"):
            download_file(parse_minio_uri(meeting.audio_uri), source)
        elif meeting.audio_uri.startswith(("http://", "https://")):
            _download_http(meeting.audio_uri, source)
        else:
            raise ValueError("audio_uri must be minio://, http:// or https://")
        size = source.stat().st_size
        if size <= 0 or size > settings.audio_max_bytes:
            raise ValueError(f"invalid media size: {size}")

        input_hash = _sha256(source)
        upload = db.query(UploadSession).filter(
            UploadSession.meeting_id == meeting.id
        ).one_or_none()
        if (
            upload
            and upload.expected_sha256
            and upload.expected_sha256.lower() != input_hash
        ):
            raise ValueError("uploaded media SHA-256 does not match upload declaration")
        probe = _probe(source)
        denoise = bool(meeting.denoise_enabled)
        normalized = temporary_root / "normalized-16k-mono.wav"
        _normalize(source, normalized, denoise)
        normalized_probe = _probe(normalized)
        quality = _audio_quality(normalized)
        object_name = (
            f"{meeting.tenant_id}/{meeting.id}/derived/"
            f"{settings.audio_preprocess_version}-{input_hash[:16]}.wav"
        )
        normalized_uri = put_file(object_name, normalized, "audio/wav")
        preflight = {
            "status": "COMPLETED",
            "input": probe,
            "normalized": normalized_probe,
            "quality": quality,
            "input_sha256": input_hash,
            "normalized_sha256": _sha256(normalized),
            "preprocess_version": settings.audio_preprocess_version,
            "denoise_enabled": denoise,
        }
        meeting.audio_input_hash = input_hash
        meeting.normalized_audio_uri = normalized_uri
        meeting.audio_preflight = preflight
        meeting.audio_preprocess_version = settings.audio_preprocess_version
        meeting.duration_ms = quality["duration_ms"]
        meeting.status = "AUDIO_READY"
        meeting.error = None
        db.commit()
        return preflight
    finally:
        shutil.rmtree(temporary_root, ignore_errors=True)
