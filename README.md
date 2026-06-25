# NotaRitmo

Local-first Android voice lab for realtime ASR, offline refinement, diarization,
voiceprint matching, punctuation, transcript correction, and summary hotwords.

The default rule is simple: raw audio stays on device. ASR, VAD, punctuation,
speaker processing, file transcription, and local keyword extraction run on the
phone. The optional LLM path receives finalized transcript text only.

## Current Features

| Area | Status | Notes |
| --- | --- | --- |
| Realtime ASR | Done | Local sherpa-onnx Zipformer streams microphone text with low latency. |
| Final refinement | Done | SenseVoice re-decodes captured audio after stop for the final transcript. |
| VAD fallback | Done | Silero VAD removes silence when diarization models are unavailable. |
| Speaker diarization | Done | Local segmentation plus speaker embeddings produce speaker-aware segments. |
| Voiceprint matching | Engine done | Local embedding match is implemented; enrollment UI is intentionally minimal. |
| Punctuation | Done | Offline punctuation restores sentence punctuation on final text. |
| Emotion/event/language tags | Done | SenseVoice tags are surfaced on timeline segments when available. |
| Imported audio ASR | Done | Android decodes audio files locally, then runs the same offline pipeline. |
| Local library | Done | Saved/imported audio can be re-transcribed, deleted individually, or cleared. |
| Keywords/hotwords | Done | Local domain extraction, correction highlights, and LLM summary hotwords are separated in the UI. |
| LLM correction | Done | Optional text-only transcript correction using full context and glossary/keyword hints. |
| LLM summary | Done | Optional text-only summary plus robust keyword extraction. |
| TTS | Not yet | Candidate slot for sherpa-onnx TTS or Android system TTS. |

## Runtime Pipeline

```text
Live recording:
Mic
 -> AudioRecord 16 kHz mono PCM
 -> Zipformer realtime ASR
 -> temporary subtitle timeline
 -> PCM cache on disk
 -> stop recording
 -> diarization if available, else VAD if available, else whole-audio fallback
 -> SenseVoice refine
 -> punctuation restore
 -> local term normalization
 -> voiceprint matching when profiles exist
 -> final timeline with language/emotion/event tags

Imported file:
Android document picker
 -> app-private copy
 -> Android MediaCodec decode and resample to 16 kHz mono
 -> same offline refine pipeline
 -> final timeline

Optional LLM:
final transcript text only
 -> correction first
 -> summary and AI hotwords second
```

## Architecture

- `MainActivity`
  - Pure Android UI, permissions, navigation, rendering, model/resource controls,
    local library actions, and LLM buttons.
  - It does not own ASR algorithms.
- `session`
  - `VoiceSessionController` owns live session orchestration and converts engine
    callbacks into timeline state.
- `engine`
  - `SherpaRealtimeAsrEngine`: microphone capture, Zipformer realtime ASR, PCM
    caching.
  - `SherpaSenseVoiceRefiner`: offline SenseVoice final recognition.
  - `SherpaSpeakerDiarizer`: speaker segmentation and clustering.
  - `SherpaVadSegmenter`: silence removal and speech segmentation fallback.
  - `SherpaPunctuationRestorer`: local punctuation recovery.
  - `SherpaVoiceprintExtractor`: local speaker embedding.
  - `OfflineAudioTranscriber`: imported file decode plus offline pipeline.
  - `KeywordExtractor` and `LocalTermNormalizer`: local hotwords, glossary,
    technical term normalization, and correction keyword extraction.
  - `OpenAiCompatibleLlmClient`: optional OpenAI-compatible or
    Anthropic-compatible text LLM calls.
  - `SherpaModelDownloader` and `SherpaPackagedModelInstaller`: model download,
    mirror fallback, and packaged asset install.
- `audio`
  - `PcmSessionBuffer`: stores long live recording PCM on disk instead of heap.
  - `AndroidAudioDecoder`: system codec decode and resample for imported files.
- `data`
  - `RecordingItem` and `TranscriptSegment` represent the current UI/domain
    snapshot.
- `voiceprint`
  - `LocalVoiceprintStore` persists enrolled embeddings and performs local
    cosine-similarity matching.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the detailed flow.

## On-Device Models

Tap `Download ASR model` in the app. The app scans existing files first, then
installs packaged assets if present, then downloads missing files. Hugging Face
is tried first; `hf-mirror.com` is used as fallback where applicable.

Runtime model path:

```text
/sdcard/Android/data/com.example.notaritmo/files/models/
```

Model bundles:

| UI label | Repository/name | Required files |
| --- | --- | --- |
| Realtime Zipformer | `sherpa-onnx-streaming-zipformer-zh-int8-2025-06-30` | `encoder.int8.onnx`, `decoder.onnx`, `joiner.int8.onnx`, `tokens.txt` |
| SenseVoice refine | `sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17` | `model.int8.onnx`, `tokens.txt` |
| Punctuation | `sherpa-onnx-punct-ct-transformer-zh-en-vocab272727-2024-04-12` | `model.onnx` |
| VAD segmenter | `silero-vad` | `silero_vad.onnx` |
| Diarization segmentation | `sherpa-onnx-pyannote-segmentation-3-0` | `model.int8.onnx` |
| Speaker embedding | `3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k` | `3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx` |

After the first successful install/download, models are reused by later app
updates as long as app data is not cleared.

## LLM Support

The app supports optional text-only LLM calls:

- Anthropic-compatible `/v1/messages`, including the configured BigModel
  Anthropic-compatible endpoint.
- OpenAI-compatible chat completions.

Default values are read from `local.properties` or environment variables at
build time:

```properties
ANTHROPIC_BASE_URL=https://open.bigmodel.cn/api/anthropic
ANTHROPIC_DEFAULT_SONNET_MODEL=glm-5.2
ANTHROPIC_MODEL=glm-5.2
ANTHROPIC_AUTH_TOKEN=
```

Do not commit real API keys. The app stores user-edited LLM settings in local
Android preferences for testing.

## Build And Test

```powershell
.\gradlew.bat :app:testDebugUnitTest --no-configuration-cache
.\gradlew.bat :app:assembleDebug --no-configuration-cache
.\gradlew.bat :app:installDebug --no-configuration-cache
```

The app targets Android `arm64-v8a` because sherpa-onnx and ONNX Runtime native
libraries are packaged under `app/src/main/jniLibs/arm64-v8a/`.

## User Flow

1. Install the app on a real arm64 Android device.
2. Tap `Download ASR model`.
3. Confirm the model list shows `Found`.
4. Tap `Start live ASR`.
5. Speak, then stop recording.
6. Review the refined final timeline.
7. Optionally tap `1. Correct transcript with LLM`.
8. Optionally tap `2. Summarize + extract hotwords`.
9. Use `Transcribe again`, `Delete audio`, or `Clear audio` in `Local library`.

## Privacy Boundary

- Raw microphone audio is not uploaded by the default pipeline.
- Imported files are copied into app-private storage and decoded locally.
- Saved live recordings are stored under the app external files directory and
  can be deleted from the local library.
- Optional LLM calls send transcript text, glossary, and keyword context only.

## License

No project license has been declared yet. Third-party components and models keep
their own licenses; review sherpa-onnx, ONNX Runtime, SenseVoice, Silero VAD,
pyannote, and 3D-Speaker terms before redistribution.
