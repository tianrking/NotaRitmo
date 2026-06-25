package com.example.notaritmo.engine

import com.example.notaritmo.data.TranscriptSegment
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class KeywordExtractorTest {
    @Test
    fun prioritizesGlossaryCanonicalTermFromAlias() {
        val keywords = KeywordExtractor.extract(
            text = "今天讨论 notarythm 的 Android 端侧 ASR 实现，可以测试一下效果。",
            glossaryText = "NotaRitmo=notarythm,noto ritmo",
            maxKeywords = 8,
        )

        assertEquals("NotaRitmo", keywords.first())
        assertTrue(keywords.contains("Android"))
        assertTrue(keywords.contains("ASR"))
        assertFalse(keywords.contains("今天"))
        assertFalse(keywords.contains("测试"))
    }

    @Test
    fun extractsDomainKeywordsFromSegmentsAndFiltersGenericWords() {
        val segments = listOf(
            TranscriptSegment(
                "00:00",
                "00:03",
                "Speaker 1",
                "SenseVoice",
                "Neutral",
                "我们要做实时识别、说话人分离和声纹识别，不要把这些东西当成普通问题。",
                0.92f,
            ),
            TranscriptSegment(
                "00:03",
                "00:08",
                "Speaker 1",
                "SenseVoice",
                "Neutral",
                "Zipformer 负责低延迟，SenseVoice 负责最终精修和热词优化。",
                0.94f,
            ),
        )

        val keywords = KeywordExtractor.extractFromSegments(segments, "", 12)

        assertTrue(keywords.contains("Zipformer"))
        assertTrue(keywords.contains("SenseVoice"))
        assertTrue(keywords.contains("实时识别"))
        assertTrue(keywords.contains("说话人分离"))
        assertTrue(keywords.contains("声纹识别"))
        assertTrue(keywords.contains("热词"))
        assertFalse(keywords.contains("东西"))
        assertFalse(keywords.contains("问题"))
    }

    @Test
    fun extractsCorrectedKeywordFromArrow() {
        val keywords = KeywordExtractor.extract(
            text = "AI corrected: 热刺 -> 热词\nAI corrected: keyworsk -> keywords",
            glossaryText = "",
            maxKeywords = 8,
        )

        assertTrue(keywords.contains("热词"))
        assertTrue(keywords.contains("热刺 -> 热词"))
        assertTrue(keywords.contains("keywords"))
    }
}
