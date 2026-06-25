# NotaRitmo Architecture

NotaRitmo is a local-first Android voice pipeline. Audio stays on device for
capture, realtime ASR, and final ASR refinement. SaaS LLM calls receive text
only.

## Layers

- `MainActivity`
  - Owns Android views, permissions, simple navigation, and rendering.
  - Does not own ASR algorithms or transcript mutation rules.

- `session`
  - `VoiceSessionController` owns one live voice session.
  - It converts engine callbacks into `RecordingItem` timeline state.
  - It is the orchestration boundary between UI and ASR engines.

- `engine`
  - `SherpaRealtimeAsrEngine` captures microphone PCM and runs streaming
    Zipformer.
  - `SherpaSenseVoiceRefiner` runs offline SenseVoice refinement after stop.
  - `SherpaModelDownloader` prepares both model families.
  - `OpenAiCompatibleLlmClient` calls an external LLM with finalized text.

- `audio`
  - `PcmSessionBuffer` stores raw PCM in a temporary cache file while recording.
  - This keeps long sessions out of Java/Kotlin heap memory.

- `data`
  - `RecordingItem` and `TranscriptSegment` are the current UI/domain snapshot.

## Runtime Flow

1. User taps `Download ASR model`.
2. The model downloader prepares Zipformer realtime files and SenseVoice refine
   files from packaged assets or online URLs.
3. User taps `Start live ASR`.
4. `SherpaRealtimeAsrEngine` streams microphone PCM into Zipformer and writes
   the same PCM into a temporary cache file.
5. Realtime segments are shown immediately.
6. User stops recording.
7. SenseVoice reads the temporary PCM, refines the final transcript locally, and
   replaces the realtime transcript.
8. LLM summarization can run against the final text only.

## Reliability Rules

- Do not upload raw audio in the default pipeline.
- Do not add algorithm code to `MainActivity`.
- Do not keep long audio sessions in memory.
- Any new model must be represented in model download/packaging logic before it
  is used by an engine.
