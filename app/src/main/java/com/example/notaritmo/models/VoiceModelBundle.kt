package com.example.notaritmo.models

import java.io.File

data class VoiceModelBundle(
    val label: String,
    val repoName: String,
    val modelDir: File,
    val files: List<String>,
) {
    fun missingFiles(): List<String> {
        return files.filter { !File(modelDir, it).isFile }
    }

    fun isReady(): Boolean = missingFiles().isEmpty()
}
