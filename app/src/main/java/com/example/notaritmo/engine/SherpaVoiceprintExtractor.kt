package com.example.notaritmo.engine

import android.content.Context
import com.k2fsa.sherpa.onnx.SpeakerEmbeddingExtractor
import com.k2fsa.sherpa.onnx.SpeakerEmbeddingExtractorConfig
import java.io.File

class SherpaVoiceprintExtractor(
    private val context: Context,
) {
    fun isModelReady(): Boolean = File(
        SherpaSpeakerDiarizer.embeddingDir(context),
        SherpaSpeakerDiarizer.EMBEDDING_FILE,
    ).isFile

    fun extract(samples: FloatArray, sampleRate: Int): FloatArray {
        if (!isModelReady()) return FloatArray(0)

        val extractor = SpeakerEmbeddingExtractor(
            assetManager = null,
            config = SpeakerEmbeddingExtractorConfig(
                model = File(
                    SherpaSpeakerDiarizer.embeddingDir(context),
                    SherpaSpeakerDiarizer.EMBEDDING_FILE,
                ).absolutePath,
                numThreads = 1,
                provider = "cpu",
            ),
        )
        return try {
            val stream = extractor.createStream()
            try {
                stream.acceptWaveform(samples, sampleRate)
                stream.inputFinished()
                if (extractor.isReady(stream)) {
                    extractor.compute(stream)
                } else {
                    FloatArray(0)
                }
            } finally {
                stream.release()
            }
        } finally {
            extractor.release()
        }
    }
}
