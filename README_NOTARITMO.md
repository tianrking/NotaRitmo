# NotaRitmo Android Voice Core

This project now contains a real on-device two-layer ASR path based on sherpa-onnx.

See `docs/ARCHITECTURE.md` for the module boundaries and runtime flow.

## What is real now

- Android native UI and microphone flow.
- `AudioRecord` captures 16 kHz mono PCM.
- sherpa-onnx JNI libraries are packaged for `arm64-v8a`.
- Streaming Zipformer runs locally through ONNX Runtime for low-latency text.
- SenseVoice runs locally after stop to refine the final transcript.
- Offline punctuation restores commas and periods for the final transcript.
- Local hotwords bias realtime ASR toward project names, people, and terms.
- LLM is intentionally external and not required for local ASR.

## Prepare the ASR model

Normal users do not need `adb push`. Install the APK, open the app, and tap
`Download ASR model`. The app downloads both the realtime Zipformer files and
the SenseVoice refine files into its own external files directory:

`/sdcard/Android/data/com.example.notaritmo/files/models/sherpa-onnx-streaming-zipformer-zh-int8-2025-06-30/`

`/sdcard/Android/data/com.example.notaritmo/files/models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/`

After the download finishes, `Start live ASR` works fully offline. Zipformer
shows text immediately while speaking; SenseVoice re-decodes the captured audio
after stop, offline punctuation restores sentence punctuation, and the refined
timeline replaces the realtime transcript.

The downloader tries Hugging Face first and then `hf-mirror.com` as a fallback.

## Developer-only model setup

From the project root on Windows:

```powershell
.\tools\download-sherpa-zipformer-zh.ps1
```

You can still prepare the model manually while developing:

```powershell
adb install -r .\app\build\outputs\apk\debug\app-debug.apk
adb push .\models\sherpa-onnx-streaming-zipformer-zh-int8-2025-06-30 /sdcard/Android/data/com.example.notaritmo/files/models/
```

## Packaging the model into the APK

This is also supported by the same `Download ASR model` button. Put the model
files under:

`app/src/main/assets/models/sherpa-onnx-streaming-zipformer-zh-int8-2025-06-30/`

`app/src/main/assets/models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/`

When those assets exist, the app copies them into the same runtime model
directory and does not hit the network. Add `noCompress += "onnx"` in Gradle for
a production packaged build. The tradeoff is APK size: the current native-debug
APK is about 42 MB, while bundling this ASR model would add roughly another
390 MB for both ASR layers.

## Model

The current real-time model is:

`sherpa-onnx-streaming-zipformer-zh-int8-2025-06-30`

This is a higher-accuracy realtime Chinese model. It gives up bilingual
Chinese/English coverage from the earlier Paraformer model, but it should be
more stable for Mandarin dictation and meeting notes.

Only these files are required on device:

- `encoder.int8.onnx`
- `decoder.onnx`
- `joiner.int8.onnx`
- `tokens.txt`

The current refine model is:

`sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17`

Only these files are required on device:

- `model.int8.onnx`
- `tokens.txt`

## Next algorithm slots

- Offline file ASR: reuse the SenseVoice refiner for imported files.
- Speaker diarization: add sherpa-onnx speaker diarization or CAM++ embedding.
- TTS: add sherpa-onnx TTS or Android system TTS.
- LLM: call SaaS/private OpenAI-compatible endpoint with finalized transcript text only.
