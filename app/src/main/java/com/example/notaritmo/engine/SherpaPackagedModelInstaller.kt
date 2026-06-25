package com.example.notaritmo.engine

import android.content.Context
import java.io.File

object SherpaPackagedModelInstaller {
    fun installIfPresent(
        context: Context,
        modelName: String,
        requiredFiles: List<String>,
        modelDir: File,
        listener: ModelDownloadListener,
    ): Boolean {
        val assetDir = "models/$modelName"
        val available = context.assets.list(assetDir)?.toSet().orEmpty()
        if (!requiredFiles.all { available.contains(it) }) {
            return false
        }

        if (!modelDir.exists() && !modelDir.mkdirs()) {
            throw IllegalStateException("Cannot create model directory: ${modelDir.absolutePath}")
        }

        requiredFiles.forEach { fileName ->
            val target = File(modelDir, fileName)
            if (target.isFile && target.length() > 0) {
                listener.onProgress(fileName, 100, target.length(), target.length())
                return@forEach
            }

            val part = File(modelDir, "$fileName.part")
            if (part.exists()) part.delete()

            var copied = 0L
            context.assets.open("$assetDir/$fileName").use { input ->
                part.outputStream().use { output ->
                    val buffer = ByteArray(1024 * 256)
                    while (true) {
                        val read = input.read(buffer)
                        if (read < 0) break
                        output.write(buffer, 0, read)
                        copied += read
                        listener.onProgress(fileName, 0, copied, -1)
                    }
                }
            }

            if (target.exists()) target.delete()
            if (!part.renameTo(target)) {
                throw IllegalStateException("Cannot move ${part.name} to ${target.name}")
            }
            listener.onProgress(fileName, 100, target.length(), target.length())
        }

        return true
    }
}
