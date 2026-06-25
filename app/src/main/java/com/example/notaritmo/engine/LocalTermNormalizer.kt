package com.example.notaritmo.engine

class LocalTermNormalizer {
    private data class TermRule(
        val canonical: String,
        val aliases: List<String>,
    )

    private data class CompiledAlias(
        val regex: Regex,
        val canonical: String,
    )

    private val rules = listOf(
        TermRule(
            "NotaRitmo",
            listOf(
                "NotaRitmo",
                "nota ritmo",
                "notarhythm",
                "notar rhythm",
                "notar ritmo",
                "notar ritomo",
                "noto ritmo",
                "诺塔里特莫",
                "诺塔",
            ),
        ),
        TermRule(
            "Zipformer",
            listOf(
                "Zipformer",
                "zip former",
                "zip-former",
                "zip foamer",
                "zip for mer",
                "齐普former",
                "季普former",
            ),
        ),
        TermRule(
            "SenseVoice",
            listOf(
                "SenseVoice",
                "sense voice",
                "sense-voice",
                "sens voice",
                "森斯voice",
                "森思voice",
                "森斯 Voice",
                "森思 Voice",
            ),
        ),
        TermRule(
            "FunASR",
            listOf(
                "FunASR",
                "fun asr",
                "fun-asr",
                "fun a s r",
                "fun as are",
                "凡asr",
                "方asr",
            ),
        ),
        TermRule(
            "Android",
            listOf(
                "Android",
                "android",
                "安卓",
            ),
        ),
    )

    private val compiledAliases: List<CompiledAlias> = rules
        .flatMap { rule ->
            rule.aliases
                .distinct()
                .sortedByDescending { it.length }
                .map { alias -> CompiledAlias(aliasRegex(alias), rule.canonical) }
        }

    fun normalize(text: String): String {
        var result = text
        for (alias in compiledAliases) {
            result = alias.regex.replace(result, alias.canonical)
        }
        return result
    }

    private fun aliasRegex(alias: String): Regex {
        val pattern = Regex.escape(alias)
        val hasAsciiToken = alias.any { it in 'A'..'Z' || it in 'a'..'z' || it in '0'..'9' }
        val wrapped = if (hasAsciiToken) {
            "(?i)(?<![A-Za-z0-9])$pattern(?![A-Za-z0-9])"
        } else {
            pattern
        }
        return Regex(wrapped)
    }
}
