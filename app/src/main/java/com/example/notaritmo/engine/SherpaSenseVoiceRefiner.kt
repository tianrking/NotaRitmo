package com.example.notaritmo.engine

import android.content.Context
import com.k2fsa.sherpa.onnx.OfflineModelConfig
import com.k2fsa.sherpa.onnx.OfflineRecognizer
import com.k2fsa.sherpa.onnx.OfflineRecognizerConfig
import com.k2fsa.sherpa.onnx.OfflineSenseVoiceModelConfig
import com.k2fsa.sherpa.onnx.getFeatureConfig
import java.io.File

class SherpaSenseVoiceRefiner(
    private val context: Context,
) {
    private val modelDir: File by lazy {
        modelDir(context)
    }

    /**
     * Hotwords for native shallow-fusion biasing (layer ①). Newline-separated
     * canonical terms; applied per-stream at decode time when non-empty.
     */
    var hotwords: String = ""

    fun isModelReady(): Boolean {
        return File(modelDir, "model.int8.onnx").isFile &&
            File(modelDir, "tokens.txt").isFile
    }

    fun refine(samples: FloatArray, sampleRate: Int): SenseVoiceRefineResult {
        if (!isModelReady()) {
            throw IllegalStateException(
                "Missing SenseVoice refine model. Put model.int8.onnx and tokens.txt under ${modelDir.absolutePath}"
            )
        }

        val config = OfflineRecognizerConfig(
            featConfig = getFeatureConfig(sampleRate = sampleRate, featureDim = 80),
            modelConfig = OfflineModelConfig(
                senseVoice = OfflineSenseVoiceModelConfig(
                    model = File(modelDir, "model.int8.onnx").absolutePath,
                    language = "auto",
                    useInverseTextNormalization = true,
                ),
                tokens = File(modelDir, "tokens.txt").absolutePath,
                numThreads = maxOf(1, Runtime.getRuntime().availableProcessors() / 2),
                provider = "cpu",
                modelingUnit = "cjkchar",
            ),
        )

        val recognizer = OfflineRecognizer(assetManager = null, config = config)
        return try {
            // Layer ①: feed hotwords to the offline stream for CTC prefix
            // biasing. A hotword whose tokens are out of vocabulary can make the
            // native layer throw; fall back to a plain stream so refine still
            // runs (the deterministic glossary layer ⑤ still corrects text).
            val stream = try {
                recognizer.createStream(hotwords)
            } catch (t: Throwable) {
                recognizer.createStream()
            }
            try {
                stream.acceptWaveform(samples, sampleRate)
                recognizer.decode(stream)
                val result = recognizer.getResult(stream)
                SenseVoiceRefineResult(
                    text = result.text.trim(),
                    lang = result.lang,
                    emotion = result.emotion,
                    event = result.event,
                )
            } finally {
                stream.release()
            }
        } finally {
            recognizer.release()
        }
    }

    companion object {
        const val MODEL_NAME = "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17"

        @JvmStatic
        fun modelDir(context: Context): File {
            val external = context.getExternalFilesDir("models")
            return File(external ?: File(context.filesDir, "models"), MODEL_NAME)
        }
    }
}
