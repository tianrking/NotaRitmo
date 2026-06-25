package com.example.notaritmo.models

import android.content.Context
import com.example.notaritmo.engine.SherpaRealtimeAsrEngine
import com.example.notaritmo.engine.SherpaSenseVoiceRefiner

object VoiceModelRegistry {
    fun bundles(context: Context): List<VoiceModelBundle> {
        return listOf(
            VoiceModelBundle(
                label = "Realtime Zipformer",
                repoName = SherpaRealtimeAsrEngine.MODEL_NAME,
                modelDir = SherpaRealtimeAsrEngine.modelDir(context),
                files = listOf(
                    "encoder.int8.onnx",
                    "decoder.onnx",
                    "joiner.int8.onnx",
                    "tokens.txt",
                ),
            ),
            VoiceModelBundle(
                label = "SenseVoice refine",
                repoName = SherpaSenseVoiceRefiner.MODEL_NAME,
                modelDir = SherpaSenseVoiceRefiner.modelDir(context),
                files = listOf(
                    "model.int8.onnx",
                    "tokens.txt",
                ),
            ),
        )
    }

    @JvmStatic
    fun scan(context: Context): VoiceModelStatus {
        return VoiceModelStatus(bundles(context))
    }
}
