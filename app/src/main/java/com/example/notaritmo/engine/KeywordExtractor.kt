package com.example.notaritmo.engine

import com.example.notaritmo.data.TranscriptSegment
import java.util.Locale

object KeywordExtractor {
    private data class Candidate(
        val text: String,
        var score: Double,
        val firstSeen: Int,
        val trusted: Boolean,
    )

    private val knownTerms = listOf(
        "NotaRitmo",
        "Android",
        "Zipformer",
        "SenseVoice",
        "FunASR",
        "ASR",
        "LLM",
        "TTS",
        "VAD",
        "PCM",
        "WAV",
        "speaker diarization",
        "speaker embedding",
        "voiceprint",
        "punctuation",
        "realtime ASR",
        "offline ASR",
        "local ASR",
        "hotwords",
        "glossary",
        "keywords",
        "transcript correction",
        "audio library",
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
        "实时录音",
        "音频库",
        "上下文",
        "语义分词",
    )

    private val englishStopwords = setOf(
        "the", "and", "for", "with", "this", "that", "then", "from", "into",
        "local", "final", "text", "audio", "speech", "voice", "test", "demo",
        "ready", "shows", "device", "summary", "transcript", "segment", "thing",
        "things", "problem", "issue", "error", "failed", "normal", "maybe",
    )

    private val chineseStopwords = listOf(
        "我们", "这个", "一个", "然后", "就是", "可以", "现在", "今天", "测试",
        "一下", "效果", "怎么样", "进行", "需要", "不是", "还是", "感觉",
        "东西", "问题", "异常", "正常", "怎么", "回事", "是否", "更加",
        "优化", "理想", "选择", "点击", "提示",
    )

    private val domainHints = listOf(
        "识别", "模型", "热词", "关键词", "转写", "录音", "音频", "纠错",
        "总结", "分段", "字幕", "声纹", "端侧", "本地", "离线", "实时",
        "导入", "情绪", "事件", "说话人", "上下文", "语义",
    )

    private val asciiTokenRegex = Regex("[A-Za-z][A-Za-z0-9+#._-]{1,}")
    private val cjkRunRegex = Regex("[\\p{IsHan}]{2,}")
    private val correctionArrowRegex = Regex("(.{1,24})\\s*->\\s*(.{1,24})")

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

        fun add(raw: String?, weight: Double, trusted: Boolean = false) {
            val cleaned = cleanKeyword(raw) ?: return
            val key = normalizedKey(cleaned)
            val existing = candidates[key]
            if (existing == null) {
                candidates[key] = Candidate(cleaned, weight, order++, trusted)
            } else {
                existing.score += weight
            }
        }

        for (entry in glossaryEntries(glossaryText)) {
            if (containsTerm(source, entry.first) || entry.second.any { containsTerm(source, it) }) {
                add(entry.first, 24.0, trusted = true)
            }
        }

        correctionArrowRegex.findAll(source).forEach { match ->
            val before = cleanCorrectionSide(match.groupValues[1])
            val after = cleanCorrectionSide(match.groupValues[2])
            add(after, 20.0, trusted = true)
            add("$before -> $after", 18.0, trusted = true)
        }

        for (term in knownTerms) {
            val count = occurrenceCount(source, term)
            if (count > 0) {
                add(term, 10.0 + count * 2.5 + term.length.coerceAtMost(16) / 4.0, trusted = true)
            }
        }

        for (match in asciiTokenRegex.findAll(source)) {
            val token = match.value
            val key = token.lowercase(Locale.US)
            val looksLikeTerm = token.any { it.isUpperCase() } ||
                token.any { it.isDigit() } ||
                token.contains("-") ||
                token.contains("_")
            if (token.length >= 3 && key !in englishStopwords && looksLikeTerm) {
                add(token, 4.0 + token.length.coerceAtMost(12) / 4.0)
            }
        }

        val cjkRuns = cjkRunRegex.findAll(source).map { it.value }.toList()
        val repeatedChinese = repeatedChinesePhrases(cjkRuns)
        for (phrase in repeatedChinese) {
            add(phrase, 4.5)
        }
        for (run in cjkRuns) {
            extractDomainChinesePhrases(run).forEach { add(it, 5.0) }
        }

        val sorted = candidates.values
            .sortedWith(
                compareByDescending<Candidate> { if (it.trusted) 1 else 0 }
                    .thenByDescending { it.score }
                    .thenBy { it.firstSeen },
            )

        val selected = mutableListOf<Candidate>()
        for (candidate in sorted) {
            if (selected.size >= maxKeywords) break
            if (shouldSkipBecauseCovered(candidate, selected)) continue
            selected += candidate
        }
        return selected.map { it.text }
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

    private fun occurrenceCount(source: String, term: String): Int {
        if (term.isBlank()) return 0
        val hasAscii = term.any { it in 'A'..'Z' || it in 'a'..'z' || it in '0'..'9' }
        return if (hasAscii) {
            Regex("(?i)(?<![A-Za-z0-9])${Regex.escape(term)}(?![A-Za-z0-9])").findAll(source).count()
        } else {
            Regex(Regex.escape(term)).findAll(source).count()
        }
    }

    private fun repeatedChinesePhrases(runs: List<String>): List<String> {
        val counts = linkedMapOf<String, Int>()
        for (run in runs) {
            for (length in 2..6) {
                if (run.length < length) continue
                for (start in 0..run.length - length) {
                    val phrase = run.substring(start, start + length)
                    if (isWeakChinese(phrase)) continue
                    if (!hasDomainHint(phrase) && length < 4) continue
                    counts[phrase] = (counts[phrase] ?: 0) + 1
                }
            }
        }
        return counts
            .filter { it.value >= 2 }
            .keys
            .sortedByDescending { it.length }
            .take(10)
    }

    private fun extractDomainChinesePhrases(run: String): List<String> {
        val out = linkedSetOf<String>()
        for (hint in domainHints) {
            var index = run.indexOf(hint)
            while (index >= 0) {
                val start = (index - 4).coerceAtLeast(0)
                val end = (index + hint.length + 4).coerceAtMost(run.length)
                for (left in start..index) {
                    for (right in index + hint.length..end) {
                        val phrase = run.substring(left, right)
                        if (phrase.length in 2..8 && !isWeakChinese(phrase) && hasDomainHint(phrase)) {
                            out += trimChineseNoise(phrase)
                        }
                    }
                }
                index = run.indexOf(hint, index + hint.length)
            }
        }
        return out
            .filter { it.length in 2..8 && !isWeakChinese(it) }
            .sortedByDescending { phrase -> domainHints.count { phrase.contains(it) } * 10 + phrase.length }
            .take(8)
    }

    private fun trimChineseNoise(value: String): String {
        var result = value
        for (stop in chineseStopwords.sortedByDescending { it.length }) {
            if (result.startsWith(stop) && result.length > stop.length + 1) {
                result = result.removePrefix(stop)
            }
            if (result.endsWith(stop) && result.length > stop.length + 1) {
                result = result.removeSuffix(stop)
            }
        }
        return result
    }

    private fun hasDomainHint(value: String): Boolean {
        return domainHints.any { value.contains(it) }
    }

    private fun isWeakChinese(value: String): Boolean {
        if (value.length < 2) return true
        if (value.all { it == value.first() }) return true
        return chineseStopwords.any { value == it || (value.contains(it) && value.length <= it.length + 1) }
    }

    private fun shouldSkipBecauseCovered(candidate: Candidate, selected: List<Candidate>): Boolean {
        if (candidate.trusted) return false
        val key = normalizedKey(candidate.text)
        return selected.any { existing ->
            val existingKey = normalizedKey(existing.text)
            existingKey != key && existingKey.contains(key) && existing.score >= candidate.score
        }
    }

    private fun cleanKeyword(raw: String?): String? {
        val cleaned = raw.orEmpty()
            .trim()
            .trim('-', '*', '#', ':', '：', ',', '，', '.', '。', ';', '；', '"', '\'', '`', '[', ']')
            .replace(Regex("\\s+"), " ")
        if (cleaned.length < 2 || cleaned.length > 32) return null
        if (cleaned.all { it.isDigit() }) return null
        if (cleaned.lowercase(Locale.US) in englishStopwords) return null
        if (chineseStopwords.any { cleaned == it }) return null
        return cleaned
    }

    private fun cleanCorrectionSide(raw: String): String {
        return raw
            .replace(Regex("(?i)^.*AI corrected:\\s*"), "")
            .replace(Regex("(?i)^.*AI inserted:\\s*"), "")
            .replace(Regex("(?i)^.*AI removed:\\s*"), "")
            .trim()
    }

    private fun normalizedKey(value: String): String {
        return value.lowercase(Locale.US).replace(Regex("\\s+"), " ").trim()
    }
}
