package com.example.notaritmo.engine

import android.content.Context
import com.example.notaritmo.models.VoiceModelBundle
import com.example.notaritmo.models.VoiceModelRegistry
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import kotlin.concurrent.thread

class SherpaModelDownloader(
    private val context: Context,
    private val listener: ModelDownloadListener,
) {
    private val bundles = VoiceModelRegistry.bundles(context)

    @Volatile
    private var running = false

    fun isRunning(): Boolean = running

    fun isModelReady(): Boolean = bundles.all { bundle ->
        bundle.files.all { File(bundle.modelDir, it).isFile }
    }

    fun start() {
        if (running) return
        running = true
        thread(name = "notaritmo-model-download", start = true) {
            try {
                bundles.forEach { bundle ->
                    bundle.modelDir.mkdirs()
                    if (SherpaPackagedModelInstaller.installIfPresent(
                            context,
                            bundle.repoName,
                            bundle.files,
                            bundle.modelDir,
                            listener,
                        )
                    ) {
                        return@forEach
                    }
                    bundle.files.forEach { fileName ->
                        val target = File(bundle.modelDir, fileName)
                        if (target.isFile && target.length() > 0) {
                            listener.onProgress("${bundle.label}: $fileName", 100, target.length(), target.length())
                            return@forEach
                        }
                        downloadWithFallback(bundle, fileName, target)
                    }
                }
                listener.onComplete(
                    "Realtime: ${bundles[0].modelDir.absolutePath}\nRefine: ${bundles[1].modelDir.absolutePath}"
                )
            } catch (t: Throwable) {
                listener.onError(t.message ?: t.javaClass.simpleName)
            } finally {
                running = false
            }
        }
    }

    private fun downloadWithFallback(bundle: VoiceModelBundle, fileName: String, target: File) {
        val paths = listOf(
            "https://huggingface.co/csukuangfj/${bundle.repoName}/resolve/main/$fileName",
            "https://hf-mirror.com/csukuangfj/${bundle.repoName}/resolve/main/$fileName",
        )
        var last: Throwable? = null
        for (url in paths) {
            try {
                downloadOne(url, "${bundle.label}: $fileName", target)
                return
            } catch (t: Throwable) {
                last = t
            }
        }
        throw IllegalStateException("Download failed for $fileName: ${last?.message}")
    }

    private fun downloadOne(url: String, fileName: String, target: File) {
        val part = File(target.parentFile, "$fileName.part")
        if (part.exists()) part.delete()

        val conn = (URL(url).openConnection() as HttpURLConnection).apply {
            connectTimeout = 20000
            readTimeout = 120000
            requestMethod = "GET"
            setRequestProperty("User-Agent", "NotaRitmo")
        }
        val code = conn.responseCode
        if (code !in 200..299) {
            throw IllegalStateException("HTTP $code")
        }

        val total = conn.contentLengthLong
        var downloaded = 0L
        conn.inputStream.use { input ->
            part.outputStream().use { output ->
                val buffer = ByteArray(1024 * 256)
                while (true) {
                    val read = input.read(buffer)
                    if (read < 0) break
                    output.write(buffer, 0, read)
                    downloaded += read
                    val percent = if (total > 0) ((downloaded * 100) / total).toInt().coerceIn(0, 100) else 0
                    listener.onProgress(fileName, percent, downloaded, total)
                }
            }
        }
        if (target.exists()) target.delete()
        if (!part.renameTo(target)) {
            throw IllegalStateException("Cannot move ${part.name} to ${target.name}")
        }
    }
}
