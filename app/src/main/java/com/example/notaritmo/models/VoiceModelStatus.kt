package com.example.notaritmo.models

data class VoiceModelStatus(
    val bundles: List<VoiceModelBundle>,
) {
    val ready: Boolean = bundles.all { it.isReady() }

    val missingSummary: String
        get() = bundles
            .mapNotNull { bundle ->
                val missing = bundle.missingFiles()
                if (missing.isEmpty()) null else "${bundle.label}: ${missing.joinToString(", ")}"
            }
            .joinToString("\n")

    val displayText: String
        get() {
            if (ready) return "Local ASR models ready"
            val readyCount = bundles.count { it.isReady() }
            return "ASR models missing ($readyCount/${bundles.size} ready)\n$missingSummary"
        }
}
