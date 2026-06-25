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

    private val builtInRules = listOf(
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

    /**
     * User-supplied domain glossary. Each non-empty line is one entry, either:
     *   canonical
     * to enforce a single canonical spelling, or:
     *   canonical=alias1,alias2,alias3
     * where the aliases are common mishearings that get rewritten to the
     * canonical form during normalization. Lines starting with '#' are ignored.
     * This is the deterministic local post-decode biasing layer; it runs
     * without a network and is the stable on-device hotword path.
     */
    private val userRules = mutableListOf<TermRule>()

    private var compiledAliases: List<CompiledAlias> = emptyList()

    init {
        recompile()
    }

    fun setUserGlossary(text: String?) {
        userRules.clear()
        if (text.isNullOrEmpty()) {
            recompile()
            return
        }
        for (rawLine in text.lines()) {
            val line = rawLine.trim()
            if (line.isEmpty() || line.startsWith("#")) continue
            val eq = line.indexOf('=')
            val canonical: String
            val aliases: List<String>
            if (eq < 0) {
                canonical = line
                aliases = listOf(line)
            } else {
                canonical = line.substring(0, eq).trim()
                val parsed = line.substring(eq + 1)
                    .split(",", "，", "|")
                    .map { it.trim() }
                    .filter { it.isNotEmpty() }
                aliases = (listOf(canonical) + parsed).distinct()
            }
            if (canonical.isNotEmpty()) {
                userRules += TermRule(canonical, aliases)
            }
        }
        recompile()
    }

    fun normalize(text: String): String {
        var result = text
        for (alias in compiledAliases) {
            result = alias.regex.replace(result, alias.canonical)
        }
        return result
    }

    private fun recompile() {
        compiledAliases = (builtInRules + userRules)
            .flatMap { rule ->
                rule.aliases
                    .distinct()
                    .sortedByDescending { it.length }
                    .map { alias -> CompiledAlias(aliasRegex(alias), rule.canonical) }
            }
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
