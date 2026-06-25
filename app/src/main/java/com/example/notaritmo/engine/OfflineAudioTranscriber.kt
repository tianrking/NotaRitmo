package com.example.notaritmo.engine

import android.content.Context
import android.net.Uri
import com.example.notaritmo.audio.AndroidAudioDecoder
import com.example.notaritmo.data.TranscriptSegment
import com.example.notaritmo.session.VoiceSessionController
import com.example.notaritmo.voiceprint.LocalVoiceprintStore

class OfflineAudioTranscriber(
    private val context: Context,
) {
    private val sampleRate = 16000

    fun transcribe(uri: Uri): OfflineTranscriptionResult {
        val refiner = SherpaSenseVoiceRefiner(context)
        if (!refiner.isModelReady()) {
            throw IllegalStateException("SenseVoice refine model is missing")
        }

        val samples = AndroidAudioDecoder(context).decodeTo16kMono(uri)
        if (samples.isEmpty()) {
            throw IllegalArgumentException("Decoded audio is empty")
        }

        val refined = refine(samples, refiner)
        if (refined.isEmpty()) {
            throw IllegalStateException("SenseVoice did not produce text")
        }

        val punctuation = SherpaPunctuationRestorer(context)
        val voiceprints = LocalVoiceprintStore(context)
        val segments = refined.map { segment ->
            val match = voiceprints.search(segment.embedding, 0.58f)
            TranscriptSegment(
                VoiceSessionController.formatDuration(segment.startSeconds),
                VoiceSessionController.formatDuration(segment.endSeconds),
                if (match == null) segment.speaker else "${match.name} (${segment.speaker})",
                segment.lang.ifEmpty { "SenseVoice" },
                segment.emotion.ifEmpty { "Refined" },
                segment.event.ifEmpty { "Speech" },
                punctuation.restore(segment.text),
                0.95f,
            )
        }

        val duration = VoiceSessionController.formatDuration(samples.size.toFloat() / sampleRate)
        return OfflineTranscriptionResult(
            segments = segments,
            durationLabel = duration,
            summary = "Imported audio transcribed fully offline with local SenseVoice, punctuation, speaker labels, and voiceprint matching.",
        )
    }

    private fun refine(
        samples: FloatArray,
        refiner: SherpaSenseVoiceRefiner,
    ): List<RefinedTranscriptSegment> {
        val voiceprintExtractor = SherpaVoiceprintExtractor(context).takeIf { it.isModelReady() }
        val diarized = SherpaSpeakerDiarizer(context).diarize(samples)
        if (diarized.isNotEmpty()) {
            return diarized.mapNotNull { segment ->
                refineSegment(segment, refiner, voiceprintExtractor)
            }
        }

        val vadSegments = SherpaVadSegmenter(context).split(samples)
        var cursorSeconds = 0f
        return vadSegments.mapNotNull { segmentSamples ->
            val start = cursorSeconds
            val end = start + segmentSamples.size.toFloat() / sampleRate
            cursorSeconds = end
            val result = refiner.refine(segmentSamples, sampleRate)
            if (result.text.isEmpty()) {
                null
            } else {
                RefinedTranscriptSegment(
                    startSeconds = start,
                    endSeconds = end,
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

    private fun refineSegment(
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
}
