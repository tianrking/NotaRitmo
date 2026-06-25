package com.example.notaritmo.engine

import android.content.Context
import com.k2fsa.sherpa.onnx.OfflinePunctuation
import com.k2fsa.sherpa.onnx.OfflinePunctuationConfig
import com.k2fsa.sherpa.onnx.OfflinePunctuationModelConfig
import java.io.File

class SherpaPunctuationRestorer(
    private val context: Context,
) {
    private val modelDir: File by lazy {
        modelDir(context)
    }

    fun isModelReady(): Boolean = File(modelDir, "model.onnx").isFile

    fun restore(text: String): String {
        val normalized = text.trim()
        if (normalized.isEmpty() || !isModelReady()) return normalized

        val punctuation = OfflinePunctuation(
            assetManager = null,
            config = OfflinePunctuationConfig(
                model = OfflinePunctuationModelConfig(
                    ctTransformer = File(modelDir, "model.onnx").absolutePath,
                    numThreads = maxOf(1, Runtime.getRuntime().availableProcessors() / 2),
                    provider = "cpu",
                ),
            ),
        )
        return try {
            punctuation.addPunctuation(normalized).trim()
        } finally {
            punctuation.release()
        }
    }

    companion object {
        const val MODEL_NAME = "sherpa-onnx-punct-ct-transformer-zh-en-vocab272727-2024-04-12"

        @JvmStatic
        fun modelDir(context: Context): File {
            val external = context.getExternalFilesDir("models")
            return File(external ?: File(context.filesDir, "models"), MODEL_NAME)
        }
    }
}
