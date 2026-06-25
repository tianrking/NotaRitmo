package com.example.notaritmo.engine

import com.example.notaritmo.data.TranscriptSegment
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class KeywordExtractorTest {
    @Test
    fun extractsCanonicalGlossaryKeywordFromAlias() {
        val keywords = KeywordExtractor.extract(
            text = "今天讨论 notarythm 的 Android 端侧 ASR 实现",
            glossaryText = "NotaRitmo=notarythm,noto ritmo",
            maxKeywords = 8,
        )

        assertEquals("NotaRitmo", keywords.first())
        assertTrue(keywords.contains("Android"))
        assertTrue(keywords.contains("ASR"))
    }

    @Test
    fun extractsDomainKeywordsFromSegments() {
        val segments = listOf(
            TranscriptSegment(
                "00:00",
                "00:03",
                "Speaker 1",
                "SenseVoice",
                "Neutral",
                "我们要做实时识别、说话人分离和声纹识别",
                0.92f,
            ),
            TranscriptSegment(
                "00:03",
                "00:08",
                "Speaker 1",
                "SenseVoice",
                "Neutral",
                "Zipformer 负责低延迟，SenseVoice 负责最终精修",
                0.94f,
            ),
        )

        val keywords = KeywordExtractor.extractFromSegments(segments, "", 10)

        assertTrue(keywords.contains("Zipformer"))
        assertTrue(keywords.contains("SenseVoice"))
        assertTrue(keywords.contains("实时识别"))
        assertTrue(keywords.contains("说话人分离"))
        assertTrue(keywords.contains("声纹识别"))
    }
}
