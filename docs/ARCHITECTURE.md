# NotaRitmo Architecture

NotaRitmo is a local-first Android voice pipeline. Audio stays on device for
capture, realtime ASR, imported-file transcription, and final ASR refinement.
SaaS LLM calls receive text only, and can use either OpenAI-compatible chat
completions or Anthropic-compatible messages endpoints.

## Layers

- `MainActivity`
  - Owns Android views, permissions, simple navigation, and rendering.
  - Owns the local library UI, including re-transcribe, single audio delete,
    and clear saved audio.
  - Owns the two explicit LLM actions: correction first, summary/hotwords
    second.
  - Does not own ASR algorithms or transcript mutation rules.

- `session`
  - `VoiceSessionController` owns one live voice session.
  - It converts engine callbacks into `RecordingItem` timeline state.
  - It is the orchestration boundary between UI and ASR engines.

- `engine`
  - `SherpaRealtimeAsrEngine` captures microphone PCM and runs streaming
    Zipformer.
  - `SherpaVadSegmenter` removes silence and splits captured speech before
    final recognition when the VAD model is available.
  - `SherpaSpeakerDiarizer` runs local speaker segmentation and clustering when
    diarization models are available.
  - `SherpaVoiceprintExtractor` computes local speaker embeddings for
    enrollment and identity matching.
  - `SherpaSenseVoiceRefiner` runs offline SenseVoice refinement after stop.
  - `SherpaPunctuationRestorer` restores punctuation on finalized local text.
  - `OfflineAudioTranscriber` reuses the local refine pipeline for imported
    files.
  - `SherpaModelDownloader` prepares all local model families.
  - `KeywordExtractor` extracts local domain keywords, correction terms, and
    glossary-backed hotwords.
  - `LocalTermNormalizer` normalizes known terms and user glossary aliases on
    device.
  - `OpenAiCompatibleLlmClient` calls an external OpenAI-compatible or
    Anthropic-compatible LLM with finalized text. It supports transcript
    correction, summarization, and AI hotword extraction.

- `audio`
  - `PcmSessionBuffer` stores raw PCM in a temporary cache file while recording.
  - This keeps long sessions out of Java/Kotlin heap memory.
  - `AndroidAudioDecoder` decodes imported audio files through Android system
    codecs and resamples them to 16 kHz mono PCM.

- `data`
  - `RecordingItem` and `TranscriptSegment` are the current UI/domain snapshot.
  - `RecordingItem.audioFile` points to saved live recordings or imported
    app-private audio files when present.

- `voiceprint`
  - `LocalVoiceprintStore` persists enrolled speaker embeddings on device and
    performs local cosine-similarity matching.

## Runtime Flow

1. User taps `Download ASR model`.
2. The model downloader prepares Zipformer realtime files, SenseVoice refine
   files, punctuation, VAD, and speaker diarization models from packaged assets
   or online URLs.
3. User taps `Start live ASR`.
4. `SherpaRealtimeAsrEngine` streams microphone PCM into Zipformer and writes
   the same PCM into a temporary cache file.
5. Realtime segments are shown immediately.
6. User stops recording.
7. If speaker diarization models are present, captured PCM is split into
   speaker-aware segments. Missing diarization falls back to VAD segments, and
   missing VAD falls back to whole-recording refinement.
8. SenseVoice reads each speech segment, refines the final transcript locally,
   and exposes language, emotion, and event tags per segment.
9. Offline punctuation restores sentence punctuation.
10. Speaker embeddings are matched against enrolled local voiceprints when the
    embedding model is present.
11. LLM summarization or glossary-based correction can run against the final
    text only.

## Keyword And LLM Flow

1. Local ASR/refine produces timeline segments.
2. `KeywordExtractor` extracts local technical/domain terms from transcript
   text and the user glossary.
3. User can run LLM correction. The prompt receives the full session context,
   glossary, local keywords, and existing AI keywords. Returned corrections are
   applied segment by segment only when they are parseable and safe.
4. Corrected terms are shown separately as correction-highlight chips.
5. User can run LLM summary. The prompt receives the corrected transcript plus
   local/correction keyword hints.
6. Summary hotwords are parsed robustly from JSON arrays, object arrays, or
   simple list output, then deduplicated and filtered before display.

## Imported File Flow

1. User imports an audio file through Android document picker.
2. The file is copied into app-private storage.
3. `AndroidAudioDecoder` decodes it locally to 16 kHz mono PCM.
4. `OfflineAudioTranscriber` runs diarization or VAD segmentation, SenseVoice,
   punctuation, and voiceprint matching.
5. The imported item timeline is replaced with the offline transcript.

## Local Library Flow

1. Live recordings are exported as WAV files under the app external
   `recordings` directory.
2. Imported files are copied into the app-private `imports` directory.
3. At launch, the app scans both directories and lists recent audio items.
4. `Transcribe again` reruns the offline ASR pipeline for a saved item.
5. `Delete audio` deletes one saved/imported audio file and removes its item
   from the local list.
6. `Clear audio` deletes all saved/imported audio-backed library items. It is
   disabled by behavior while realtime ASR is running to avoid deleting the
   active recording.

## Reliability Rules

- Do not upload raw audio in the default pipeline.
- Do not add algorithm code to `MainActivity`.
- Do not keep long audio sessions in memory.
- Any new model must be represented in model download/packaging logic before it
  is used by an engine.
- Keep user-controlled glossary/hotword handling stable on device; the native
  ASR hotword path is not trusted as the only correction mechanism.
- Keep LLM mutation explicit: correction and summary are separate user actions.
