package com.example.notaritmo.engine

class LocalTermNormalizer {
    private val replacements = listOf(
        "notarhythm" to "NotaRitmo",
        "nota ritmo" to "NotaRitmo",
        "notar ritomo" to "NotaRitmo",
        "zip former" to "Zipformer",
        "zip-former" to "Zipformer",
        "sense voice" to "SenseVoice",
        "sense-voice" to "SenseVoice",
        "fun asr" to "FunASR",
        "fun-asr" to "FunASR",
        "android" to "Android",
    )

    fun normalize(text: String): String {
        var result = text
        for ((from, to) in replacements) {
            result = result.replace(from, to, ignoreCase = true)
        }
        return result
    }
}
