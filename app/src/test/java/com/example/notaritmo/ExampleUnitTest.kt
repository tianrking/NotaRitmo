package com.example.notaritmo

import com.example.notaritmo.engine.LocalTermNormalizer
import com.example.notaritmo.engine.SenseVoiceTags
import com.example.notaritmo.engine.TranscriptText
import org.junit.Test

import org.junit.Assert.*

class ExampleUnitTest {
    @Test
    fun senseVoiceTags_areProductReadable() {
        assertEquals("English", SenseVoiceTags.language("<|en|>"))
        assertEquals("Chinese", SenseVoiceTags.language("<|zh|>"))
        assertEquals("No speech", SenseVoiceTags.language("<|nospeech|>"))
        assertEquals("Neutral", SenseVoiceTags.emotion("|EMO_UNKNOWN|"))
        assertEquals("Happy", SenseVoiceTags.emotion("|EMO_HAPPY|"))
        assertEquals("Speech", SenseVoiceTags.event("|Speech|"))
        assertEquals("Laughter", SenseVoiceTags.event("|Laughter|"))
    }

    @Test
    fun localTerms_areNormalizedForFinalTranscript() {
        val normalizer = LocalTermNormalizer()

        val text = normalizer.normalize(
            "today I test nota ritmo with sense voice and zip former on android plus fun a s r",
        )

        assertTrue(text.contains("NotaRitmo"))
        assertTrue(text.contains("SenseVoice"))
        assertTrue(text.contains("Zipformer"))
        assertTrue(text.contains("Android"))
        assertTrue(text.contains("FunASR"))
    }

    @Test
    fun punctuationOnlyText_isNotMeaningfulSpeech() {
        assertFalse(TranscriptText.hasMeaningfulSpeech("。"))
        assertFalse(TranscriptText.hasMeaningfulSpeech("，！？"))
        assertTrue(TranscriptText.hasMeaningfulSpeech("NotaRitmo。"))
        assertEquals("Yeah.", TranscriptText.polish("Yeah .。"))
    }
}
