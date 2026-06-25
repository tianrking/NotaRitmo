# NotaRitmo Model And Runtime Notes

This file is the practical setup note for testing the Android app. The canonical
overview lives in [README.md](README.md), and the architecture detail lives in
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## What Is Real In The App

- Android native UI and microphone flow.
- Local `AudioRecord` capture at 16 kHz mono PCM.
- Local realtime Zipformer ASR through sherpa-onnx and ONNX Runtime.
- Disk-backed PCM cache for long live recordings.
- Local SenseVoice refinement after recording stops.
- Local punctuation restoration.
- Local VAD fallback and local speaker diarization when models are present.
- Local speaker embedding and voiceprint matching engine.
- SenseVoice language, emotion, and event tags in the timeline.
- Imported audio file transcription through Android decode plus the same
  offline pipeline.
- Saved/imported audio library with re-transcribe, single-delete, and clear-all
  controls.
- Local keyword extraction, correction-highlight keywords, and optional LLM
  summary hotwords.
- Optional LLM correction and summary with text only.

## Prepare Models In The App

Normal users should not need `adb push`.

1. Install the APK.
2. Open NotaRitmo.
3. Tap `Download ASR model`.
4. Wait until the model list shows `Found`.

The app checks the runtime model directory first. If files already exist, it
does not download them again. If assets are packaged in the APK, it copies them
to the runtime directory. Otherwise it downloads missing model files.

Runtime directory:

```text
/sdcard/Android/data/com.example.notaritmo/files/models/
```

## Required Model Bundles

| Bundle | Required files |
| --- | --- |
| `sherpa-onnx-streaming-zipformer-zh-int8-2025-06-30` | `encoder.int8.onnx`, `decoder.onnx`, `joiner.int8.onnx`, `tokens.txt` |
| `sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17` | `model.int8.onnx`, `tokens.txt` |
| `sherpa-onnx-punct-ct-transformer-zh-en-vocab272727-2024-04-12` | `model.onnx` |
| `silero-vad` | `silero_vad.onnx` |
| `sherpa-onnx-pyannote-segmentation-3-0` | `model.int8.onnx` |
| `3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k` | `3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx` |

## Packaged Model Option

Put model files under:

```text
app/src/main/assets/models/<model-name>/
```

Then `Download ASR model` installs those assets locally without network access.
For a production build, configure Gradle to avoid compressing ONNX files. The
tradeoff is APK size: bundling all speech models can add hundreds of megabytes.

## Manual Developer Setup

From the project root:

```powershell
.\tools\download-sherpa-zipformer-zh.ps1
```

Manual device push is still possible while developing:

```powershell
adb install -r .\app\build\outputs\apk\debug\app-debug.apk
adb push .\models\sherpa-onnx-streaming-zipformer-zh-int8-2025-06-30 /sdcard/Android/data/com.example.notaritmo/files/models/
```

## LLM Testing

LLM is optional. The app can use Anthropic-compatible messages endpoints or
OpenAI-compatible chat endpoints. Only text is sent.

Expected test order:

1. Produce or import a transcript.
2. Tap `1. Correct transcript with LLM`.
3. Review red correction chips and segment correction labels.
4. Tap `2. Summarize + extract hotwords`.
5. Review yellow summary hotword chips.

## Verification Commands

```powershell
.\gradlew.bat :app:testDebugUnitTest --no-configuration-cache
.\gradlew.bat :app:assembleDebug --no-configuration-cache
.\gradlew.bat :app:installDebug --no-configuration-cache
adb shell monkey -p com.example.notaritmo 1
adb logcat -d -t 300 | Select-String -Pattern "com.example.notaritmo|FATAL EXCEPTION|AndroidRuntime" -Context 0,2
```
