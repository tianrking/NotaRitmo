package com.example.notaritmo.engine

import android.content.Context
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import com.example.notaritmo.audio.PcmSessionBuffer
import com.k2fsa.sherpa.onnx.EndpointConfig
import com.k2fsa.sherpa.onnx.EndpointRule
import com.k2fsa.sherpa.onnx.OnlineModelConfig
import com.k2fsa.sherpa.onnx.OnlineRecognizer
import com.k2fsa.sherpa.onnx.OnlineRecognizerConfig
import com.k2fsa.sherpa.onnx.OnlineTransducerModelConfig
import com.k2fsa.sherpa.onnx.getFeatureConfig
import java.io.File
import kotlin.concurrent.thread

class SherpaRealtimeAsrEngine(
    private val context: Context,
    private val listener: RealtimeAsrListener,
) {
    private val sampleRate = 16000
    private val modelName = MODEL_NAME
    private val modelDir: File by lazy {
        modelDir(context)
    }

    @Volatile
    private var running = false
    private var audioRecord: AudioRecord? = null
    private var recognizer: OnlineRecognizer? = null
    private var worker: Thread? = null

    /**
     * Hotwords captured from start() for native shallow-fusion biasing (layer ①)
     * and forwarded to the SenseVoice refiner after stop.
     */
    private var hotwords: String = ""

    fun isModelReady(): Boolean {
        return File(modelDir, "encoder.int8.onnx").isFile &&
            File(modelDir, "decoder.onnx").isFile &&
            File(modelDir, "joiner.int8.onnx").isFile &&
            File(modelDir, "tokens.txt").isFile
    }

    fun expectedModelPath(): String = modelDir.absolutePath

    fun start(hotwords: String = "") {
        this.hotwords = hotwords
        if (running) return
        if (!isModelReady()) {
            listener.onError(
                "Missing local ASR model. Put encoder.int8.onnx, decoder.onnx, joiner.int8.onnx and tokens.txt under ${modelDir.absolutePath}"
            )
            return
        }

        worker = thread(name = "notaritmo-sherpa-asr", start = true) {
            val refineBuffer = PcmSessionBuffer(context)
            try {
                refineBuffer.open()
                val config = OnlineRecognizerConfig(
                    featConfig = getFeatureConfig(sampleRate = sampleRate, featureDim = 80),
                    modelConfig = OnlineModelConfig(
                        transducer = OnlineTransducerModelConfig(
                            encoder = File(modelDir, "encoder.int8.onnx").absolutePath,
                            decoder = File(modelDir, "decoder.onnx").absolutePath,
                            joiner = File(modelDir, "joiner.int8.onnx").absolutePath,
                        ),
                        tokens = File(modelDir, "tokens.txt").absolutePath,
                        numThreads = maxOf(1, Runtime.getRuntime().availableProcessors() / 2),
                        provider = "cpu",
                        modelType = "zipformer2",
                    ),
                    endpointConfig = EndpointConfig(
                        rule1 = EndpointRule(false, 2.4f, 0.0f),
                        rule2 = EndpointRule(true, 1.2f, 0.0f),
                        rule3 = EndpointRule(false, 0.0f, 20.0f),
                    ),
                    enableEndpoint = true,
                )

                recognizer = OnlineRecognizer(assetManager = null, config = config)
                val recorder = createAudioRecord()
                audioRecord = recorder
                running = true
                listener.onReady(modelName)
                recorder.startRecording()

                // Layer ①: shallow-fusion hotwords. OOV/bad tokens can make the
                // native createStream throw; fall back to a plain stream so the
                // realtime session never crashes. Deterministic glossary
                // correction (layer ⑤) still runs afterwards regardless.
                val stream = try {
                    recognizer!!.createStream(this.hotwords)
                } catch (t: Throwable) {
                    recognizer!!.createStream()
                }
                val buffer = ShortArray((sampleRate * 0.1).toInt())

                while (running) {
                    val n = recorder.read(buffer, 0, buffer.size)
                    if (n <= 0) continue
                    refineBuffer.append(buffer, n)
                    val samples = FloatArray(n) { i -> buffer[i] / 32768.0f }
                    stream.acceptWaveform(samples, sampleRate)

                    while (recognizer!!.isReady(stream)) {
                        recognizer!!.decode(stream)
                    }

                    var text = recognizer!!.getResult(stream).text.trim()
                    val endpoint = recognizer!!.isEndpoint(stream)

                    if (endpoint && text.isNotEmpty()) {
                        val padding = FloatArray((0.8 * sampleRate).toInt())
                        stream.acceptWaveform(padding, sampleRate)
                        while (recognizer!!.isReady(stream)) {
                            recognizer!!.decode(stream)
                        }
                        text = recognizer!!.getResult(stream).text.trim()
                    }

                    if (text.isNotEmpty()) {
                        if (endpoint) {
                            listener.onFinal(text)
                            recognizer!!.reset(stream)
                        } else {
                            listener.onPartial(text)
                        }
                    } else if (endpoint) {
                        recognizer!!.reset(stream)
                    }
                }

                stream.release()
            } catch (t: Throwable) {
                listener.onError(t.message ?: t.javaClass.simpleName)
            } finally {
                stopRecorder()
                recognizer?.release()
                recognizer = null
                running = false
                listener.onStopped()
                refineIfPossible(refineBuffer)
            }
        }
    }

    fun stop() {
        running = false
    }

    private fun createAudioRecord(): AudioRecord {
        val minBytes = AudioRecord.getMinBufferSize(
            sampleRate,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
        )
        return AudioRecord(
            MediaRecorder.AudioSource.MIC,
            sampleRate,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
            maxOf(minBytes * 2, sampleRate),
        )
    }

    private fun stopRecorder() {
        val recorder = audioRecord ?: return
        try {
            recorder.stop()
        } catch (_: Throwable) {
        }
        try {
            recorder.release()
        } catch (_: Throwable) {
        }
        audioRecord = null
    }

    private fun refineIfPossible(buffer: PcmSessionBuffer) {
        val refiner = SherpaSenseVoiceRefiner(context)
        refiner.hotwords = hotwords
        if (!refiner.isModelReady()) {
            buffer.delete()
            listener.onRefineSkipped(
                "SenseVoice refine model is missing. Tap Download ASR model to prepare both realtime and refine models."
            )
            return
        }

        try {
            listener.onRefining(SherpaSenseVoiceRefiner.MODEL_NAME)
            val samples = buffer.readFloats()
            if (samples.isEmpty()) {
                listener.onRefineSkipped("No captured audio was available for SenseVoice refine.")
                return
            }
            val refinedSegments = refineSegments(samples, refiner)
            if (refinedSegments.isNotEmpty()) {
                listener.onRefinedSegments(refinedSegments)
            } else {
                listener.onRefineSkipped("SenseVoice did not produce text for this recording.")
            }
        } catch (t: Throwable) {
            listener.onRefineSkipped(t.message ?: t.javaClass.simpleName)
        } finally {
            buffer.delete()
        }
    }

    private fun refineSegments(
        samples: FloatArray,
        refiner: SherpaSenseVoiceRefiner,
    ): List<RefinedTranscriptSegment> {
        val voiceprintExtractor = SherpaVoiceprintExtractor(context).takeIf { it.isModelReady() }
        val diarized = SherpaSpeakerDiarizer(context).diarize(samples)
        if (diarized.isNotEmpty()) {
            return diarized.mapNotNull { segment ->
                refineSpeechSegment(segment, refiner, voiceprintExtractor)
            }
        }

        val vadSegments = SherpaVadSegmenter(context).split(samples)
        var cursorSeconds = 0f
        return vadSegments.mapNotNull { segmentSamples ->
            val startSeconds = cursorSeconds
            val endSeconds = startSeconds + segmentSamples.size.toFloat() / sampleRate
            cursorSeconds = endSeconds
            val result = refiner.refine(segmentSamples, sampleRate)
            if (result.text.isEmpty()) {
                null
            } else {
                RefinedTranscriptSegment(
                    startSeconds = startSeconds,
                    endSeconds = endSeconds,
                    speaker = "Speaker 1",
                    text = result.text,
                    lang = result.lang,
                    emotion = result.emotion,
                    event = result.event,
                    embedding = voiceprintExtractor?.extract(segmentSamples, sampleRate) ?: FloatArray(0),
                )
            }
        }
    }

    private fun refineSpeechSegment(
        segment: DiarizedSpeechSegment,
        refiner: SherpaSenseVoiceRefiner,
        voiceprintExtractor: SherpaVoiceprintExtractor?,
    ): RefinedTranscriptSegment? {
        val result = refiner.refine(segment.samples, sampleRate)
        if (result.text.isEmpty()) return null
        return RefinedTranscriptSegment(
            startSeconds = segment.startSeconds,
            endSeconds = segment.endSeconds,
            speaker = segment.speaker,
            text = result.text,
            lang = result.lang,
            emotion = result.emotion,
            event = result.event,
            embedding = voiceprintExtractor?.extract(segment.samples, sampleRate) ?: FloatArray(0),
        )
    }

    companion object {
        const val MODEL_NAME = "sherpa-onnx-streaming-zipformer-zh-int8-2025-06-30"

        @JvmStatic
        fun modelDir(context: Context): File {
            val external = context.getExternalFilesDir("models")
            return File(external ?: File(context.filesDir, "models"), MODEL_NAME)
        }
    }
}
