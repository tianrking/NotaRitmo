package com.example.notaritmo.models

import android.content.Context
import com.example.notaritmo.engine.SherpaPunctuationRestorer
import com.example.notaritmo.engine.SherpaRealtimeAsrEngine
import com.example.notaritmo.engine.SherpaSenseVoiceRefiner
import com.example.notaritmo.engine.SherpaSpeakerDiarizer
import com.example.notaritmo.engine.SherpaVadSegmenter

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
            VoiceModelBundle(
                label = "Punctuation",
                repoName = SherpaPunctuationRestorer.MODEL_NAME,
                modelDir = SherpaPunctuationRestorer.modelDir(context),
                files = listOf(
                    "model.onnx",
                ),
            ),
            VoiceModelBundle(
                label = "VAD segmenter",
                repoName = SherpaVadSegmenter.MODEL_NAME,
                modelDir = SherpaVadSegmenter.modelDir(context),
                files = listOf(
                    SherpaVadSegmenter.MODEL_FILE,
                ),
                directBaseUrl = SherpaVadSegmenter.MODEL_URL,
            ),
            VoiceModelBundle(
                label = "Diarization segmentation",
                repoName = SherpaSpeakerDiarizer.SEGMENTATION_MODEL_NAME,
                modelDir = SherpaSpeakerDiarizer.segmentationDir(context),
                files = listOf(
                    SherpaSpeakerDiarizer.SEGMENTATION_FILE,
                ),
            ),
            VoiceModelBundle(
                label = "Speaker embedding",
                repoName = SherpaSpeakerDiarizer.EMBEDDING_MODEL_NAME,
                modelDir = SherpaSpeakerDiarizer.embeddingDir(context),
                files = listOf(
                    SherpaSpeakerDiarizer.EMBEDDING_FILE,
                ),
            ),
        )
    }

    @JvmStatic
    fun scan(context: Context): VoiceModelStatus {
        return VoiceModelStatus(bundles(context))
    }
}
