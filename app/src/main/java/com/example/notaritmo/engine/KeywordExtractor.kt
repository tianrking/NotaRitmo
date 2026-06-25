package com.example.notaritmo.engine

import com.example.notaritmo.data.TranscriptSegment
import java.util.Locale

object KeywordExtractor {
    private data class Candidate(
        val text: String,
        var score: Double,
        val firstSeen: Int,
    )

    private val knownTerms = listOf(
        "NotaRitmo",
        "Android",
        "Zipformer",
        "SenseVoice",
        "FunASR",
        "ASR",
        "LLM",
        "VAD",
        "speaker embedding",
        "diarization",
        "voiceprint",
        "punctuation",
        "realtime ASR",
        "offline ASR",
        "local ASR",
        "hotwords",
        "glossary",
        "实时识别",
        "本地识别",
        "离线识别",
        "语音识别",
        "标点恢复",
        "说话人分离",
        "声纹识别",
        "情绪识别",
        "事件检测",
        "热词",
        "关键词",
        "转写",
        "字幕",
        "总结",
        "纠错",
        "端侧",
        "模型下载",
        "导入音频",
    )

    private val englishStopwords = setOf(
        "the", "and", "for", "with", "this", "that", "then", "from", "into",
        "local", "final", "text", "audio", "speech", "voice", "test", "demo",
        "ready", "shows", "device", "summary", "transcript", "segment",
    )

    private val chineseStopwords = listOf(
        "我们", "这个", "一个", "然后", "就是", "可以", "现在", "今天", "测试",
        "一下", "效果", "怎么样", "进行", "需要", "不是", "还是", "感觉",
    )

    private val asciiTokenRegex = Regex("[A-Za-z][A-Za-z0-9+#._-]{1,}")
    private val cjkRunRegex = Regex("[\\p{IsHan}]{2,}")

    @JvmStatic
    fun extractFromSegments(
        segments: List<TranscriptSegment>?,
        glossaryText: String?,
        maxKeywords: Int,
    ): List<String> {
        val text = segments.orEmpty().joinToString("\n") { it.text.orEmpty() }
        return extract(text, glossaryText, maxKeywords)
    }

    @JvmStatic
    fun extract(
        text: String?,
        glossaryText: String?,
        maxKeywords: Int,
    ): List<String> {
        val source = text.orEmpty().trim()
        if (source.isEmpty() || maxKeywords <= 0) return emptyList()

        val candidates = linkedMapOf<String, Candidate>()
        var order = 0

        fun add(raw: String?, weight: Double) {
            val cleaned = cleanKeyword(raw) ?: return
            val key = normalizedKey(cleaned)
            val existing = candidates[key]
            if (existing == null) {
                candidates[key] = Candidate(cleaned, weight, order++)
            } else {
                existing.score += weight
            }
        }

        for (entry in glossaryEntries(glossaryText)) {
            if (containsTerm(source, entry.first) || entry.second.any { containsTerm(source, it) }) {
                add(entry.first, 14.0)
            }
        }

        for (term in knownTerms) {
            if (containsTerm(source, term)) {
                add(term, 6.0)
            }
        }

        for (match in asciiTokenRegex.findAll(source)) {
            val token = match.value
            val key = token.lowercase(Locale.US)
            if (token.length >= 3 && key !in englishStopwords) {
                add(token, 1.5 + token.length.coerceAtMost(12) / 8.0)
            }
        }

        for (match in cjkRunRegex.findAll(source)) {
            val run = match.value
            if (run.length in 2..8 && !isWeakChinese(run)) {
                add(run, 1.2 + run.length / 5.0)
            }
            knownChineseWindows(run).forEach { add(it, 2.2) }
        }

        return candidates.values
            .sortedWith(compareByDescending<Candidate> { it.score }.thenBy { it.firstSeen })
            .map { it.text }
            .take(maxKeywords)
    }

    @JvmStatic
    fun merge(first: List<String>?, second: List<String>?, maxKeywords: Int): List<String> {
        val merged = linkedMapOf<String, String>()
        for (value in first.orEmpty() + second.orEmpty()) {
            val cleaned = cleanKeyword(value) ?: continue
            merged.putIfAbsent(normalizedKey(cleaned), cleaned)
            if (merged.size >= maxKeywords) break
        }
        return merged.values.toList()
    }

    private fun glossaryEntries(glossaryText: String?): List<Pair<String, List<String>>> {
        if (glossaryText.isNullOrBlank()) return emptyList()
        return glossaryText.lines().mapNotNull { raw ->
            val line = raw.trim()
            if (line.isEmpty() || line.startsWith("#")) return@mapNotNull null
            val eq = line.indexOf('=')
            if (eq < 0) {
                line to listOf(line)
            } else {
                val canonical = line.substring(0, eq).trim()
                val aliases = line.substring(eq + 1)
                    .split(",", "，", "|", ";", "；")
                    .map { it.trim() }
                    .filter { it.isNotEmpty() }
                if (canonical.isEmpty()) null else canonical to (listOf(canonical) + aliases).distinct()
            }
        }
    }

    private fun containsTerm(source: String, term: String): Boolean {
        if (term.isBlank()) return false
        val hasAscii = term.any { it in 'A'..'Z' || it in 'a'..'z' || it in '0'..'9' }
        return if (hasAscii) {
            Regex("(?i)(?<![A-Za-z0-9])${Regex.escape(term)}(?![A-Za-z0-9])").containsMatchIn(source)
        } else {
            source.contains(term)
        }
    }

    private fun knownChineseWindows(run: String): List<String> {
        return knownTerms
            .filter { it.any { ch -> Character.UnicodeScript.of(ch.code) == Character.UnicodeScript.HAN } }
            .filter { run.contains(it) }
    }

    private fun isWeakChinese(value: String): Boolean {
        return value.length < 2 || chineseStopwords.any { value == it || value.contains(it) && value.length <= it.length + 1 }
    }

    private fun cleanKeyword(raw: String?): String? {
        val cleaned = raw.orEmpty()
            .trim()
            .trim('-', '*', '#', ':', '：', ',', '，', '.', '。', ';', '；', '"', '\'', '`', '[', ']')
            .replace(Regex("\\s+"), " ")
        if (cleaned.length < 2 || cleaned.length > 32) return null
        if (cleaned.all { it.isDigit() }) return null
        return cleaned
    }

    private fun normalizedKey(value: String): String {
        return value.lowercase(Locale.US).replace(Regex("\\s+"), " ").trim()
    }
}
