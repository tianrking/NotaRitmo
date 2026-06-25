package com.example.notaritmo.engine

import android.content.Context
import com.k2fsa.sherpa.onnx.SileroVadModelConfig
import com.k2fsa.sherpa.onnx.Vad
import com.k2fsa.sherpa.onnx.VadModelConfig
import java.io.File

class SherpaVadSegmenter(
    private val context: Context,
) {
    private val sampleRate = 16000
    private val modelDir: File by lazy {
        modelDir(context)
    }

    fun isModelReady(): Boolean = File(modelDir, MODEL_FILE).isFile

    fun split(samples: FloatArray): List<FloatArray> {
        if (!isModelReady()) {
            return listOf(samples)
        }

        val vad = Vad(
            assetManager = null,
            config = VadModelConfig(
                sileroVadModelConfig = SileroVadModelConfig(
                    model = File(modelDir, MODEL_FILE).absolutePath,
                    threshold = 0.5f,
                    minSilenceDuration = 0.35f,
                    minSpeechDuration = 0.25f,
                    windowSize = 512,
                    maxSpeechDuration = 12.0f,
                ),
                sampleRate = sampleRate,
                numThreads = 1,
                provider = "cpu",
            ),
        )

        return try {
            vad.acceptWaveform(samples)
            vad.flush()
            val segments = mutableListOf<FloatArray>()
            while (!vad.empty()) {
                val segment = vad.front()
                if (segment.samples.isNotEmpty()) {
                    segments.add(padSegment(segment.samples))
                }
                vad.pop()
            }
            if (segments.isEmpty()) listOf(samples) else segments
        } finally {
            vad.release()
        }
    }

    private fun padSegment(samples: FloatArray): FloatArray {
        val padding = (sampleRate * 0.15f).toInt()
        if (padding <= 0) return samples
        val padded = FloatArray(samples.size + padding * 2)
        samples.copyInto(padded, padding)
        return padded
    }

    companion object {
        const val MODEL_NAME = "silero-vad"
        const val MODEL_FILE = "silero_vad.onnx"
        const val MODEL_URL = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models"

        @JvmStatic
        fun modelDir(context: Context): File {
            val external = context.getExternalFilesDir("models")
            return File(external ?: File(context.filesDir, "models"), MODEL_NAME)
        }
    }
}
