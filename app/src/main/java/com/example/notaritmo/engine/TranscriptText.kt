package com.example.notaritmo.engine

object TranscriptText {
    @JvmStatic
    fun hasMeaningfulSpeech(text: String?): Boolean {
        val cleaned = text
            ?.replace(Regex("[\\s\\p{Punct}\\p{IsPunctuation}]"), "")
            ?.replace("，", "")
            ?.replace("。", "")
            ?.replace("！", "")
            ?.replace("？", "")
            ?.replace("、", "")
            ?.replace("；", "")
            ?.replace("：", "")
            ?.replace("“", "")
            ?.replace("”", "")
            ?.replace("‘", "")
            ?.replace("’", "")
            ?.trim()
            .orEmpty()
        return cleaned.isNotEmpty()
    }

    @JvmStatic
    fun polish(text: String?): String {
        return text
            ?.trim()
            ?.replace(Regex("\\s+([,.;:!?，。；：！？、])"), "$1")
            ?.replace(Regex("([.!?。！？])\\s*([.!?。！？])"), "$1")
            ?.replace(Regex("\\s+"), " ")
            ?.trim()
            .orEmpty()
    }
}
