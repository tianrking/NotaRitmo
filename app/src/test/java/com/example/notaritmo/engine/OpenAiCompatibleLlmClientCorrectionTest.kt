package com.example.notaritmo.engine

import org.junit.Assert.assertEquals
import org.junit.Test

class OpenAiCompatibleLlmClientCorrectionTest {
    @Test
    fun parsesCorrectionJsonArray() {
        val parsed = OpenAiCompatibleLlmClient.parseCorrectedLines(
            """
            [
              {"index":1,"text":"我们要把热刺改成热词。"},
              {"index":2,"text":"SenseVoice 负责最终精修。"}
            ]
            """.trimIndent(),
        )

        assertEquals("我们要把热刺改成热词。", parsed[0])
        assertEquals("SenseVoice 负责最终精修。", parsed[1])
    }

    @Test
    fun parsesCorrectionJsonInsideMarkdownFence() {
        val parsed = OpenAiCompatibleLlmClient.parseCorrectedLines(
            """
            ```json
            {"corrections":[{"index":1,"corrected_text":"keyworsk 应该是 keywords。"}]}
            ```
            """.trimIndent(),
        )

        assertEquals("keyworsk 应该是 keywords。", parsed[0])
    }

    @Test
    fun parsesLegacyNumberedLines() {
        val parsed = OpenAiCompatibleLlmClient.parseCorrectedLines(
            "1. NotaRitmo 可以本地识别\n2. Zipformer 实时显示字幕",
        )

        assertEquals("NotaRitmo 可以本地识别", parsed[0])
        assertEquals("Zipformer 实时显示字幕", parsed[1])
    }
}
