package com.example.notaritmo.engine

import android.content.Context
import com.k2fsa.sherpa.onnx.FastClusteringConfig
import com.k2fsa.sherpa.onnx.OfflineSpeakerDiarization
import com.k2fsa.sherpa.onnx.OfflineSpeakerDiarizationConfig
import com.k2fsa.sherpa.onnx.OfflineSpeakerSegmentationModelConfig
import com.k2fsa.sherpa.onnx.OfflineSpeakerSegmentationPyannoteModelConfig
import com.k2fsa.sherpa.onnx.SpeakerEmbeddingExtractorConfig
import java.io.File
import kotlin.math.roundToInt

class SherpaSpeakerDiarizer(
    private val context: Context,
) {
    private val sampleRate = 16000

    fun isModelReady(): Boolean {
        return File(segmentationDir(context), SEGMENTATION_FILE).isFile &&
            File(embeddingDir(context), EMBEDDING_FILE).isFile
    }

    fun diarize(samples: FloatArray): List<DiarizedSpeechSegment> {
        if (!isModelReady()) return emptyList()

        val diarization = OfflineSpeakerDiarization(
            assetManager = null,
            config = OfflineSpeakerDiarizationConfig(
                segmentation = OfflineSpeakerSegmentationModelConfig(
                    pyannote = OfflineSpeakerSegmentationPyannoteModelConfig(
                        model = File(segmentationDir(context), SEGMENTATION_FILE).absolutePath,
                    ),
                    numThreads = 1,
                    provider = "cpu",
                ),
                embedding = SpeakerEmbeddingExtractorConfig(
                    model = File(embeddingDir(context), EMBEDDING_FILE).absolutePath,
                    numThreads = 1,
                    provider = "cpu",
                ),
                clustering = FastClusteringConfig(numClusters = -1, threshold = 0.6f),
                minDurationOn = 0.25f,
                minDurationOff = 0.5f,
            ),
        )

        return try {
            diarization.process(samples)
                .mapNotNull { segment ->
                    val start = (segment.start * sampleRate).roundToInt().coerceIn(0, samples.size)
                    val end = (segment.end * sampleRate).roundToInt().coerceIn(start, samples.size)
                    if (end <= start) {
                        null
                    } else {
                        DiarizedSpeechSegment(
                            startSeconds = segment.start,
                            endSeconds = segment.end,
                            speaker = "Speaker ${segment.speaker + 1}",
                            samples = samples.copyOfRange(start, end),
                        )
                    }
                }
        } finally {
            diarization.release()
        }
    }

    companion object {
        const val SEGMENTATION_MODEL_NAME = "sherpa-onnx-pyannote-segmentation-3-0"
        const val SEGMENTATION_FILE = "model.int8.onnx"
        const val EMBEDDING_MODEL_NAME = "speaker-embedding-models"
        const val EMBEDDING_FILE = "3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx"

        @JvmStatic
        fun segmentationDir(context: Context): File {
            val external = context.getExternalFilesDir("models")
            return File(external ?: File(context.filesDir, "models"), SEGMENTATION_MODEL_NAME)
        }

        @JvmStatic
        fun embeddingDir(context: Context): File {
            val external = context.getExternalFilesDir("models")
            return File(external ?: File(context.filesDir, "models"), EMBEDDING_MODEL_NAME)
        }
    }
}
