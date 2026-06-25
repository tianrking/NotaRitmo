package com.example.notaritmo.engine

import org.junit.Assert.assertEquals
import org.junit.Test

class OpenAiCompatibleLlmClientKeywordTest {
    @Test
    fun parsesJsonArrayInsideMarkdownFence() {
        val parsed = OpenAiCompatibleLlmClient.parseKeywords(
            """
            ```json
            ["NotaRitmo", "SenseVoice", "说话人分离"]
            ```
            """.trimIndent(),
            8,
        )

        assertEquals(listOf("NotaRitmo", "SenseVoice", "说话人分离"), parsed)
    }

    @Test
    fun parsesFallbackListAndDeduplicates() {
        val parsed = OpenAiCompatibleLlmClient.parseKeywords(
            "1. NotaRitmo\n2. SenseVoice\n3. notarItmo\n4. 热词",
            8,
        )

        assertEquals(listOf("NotaRitmo", "SenseVoice", "热词"), parsed)
    }
}
