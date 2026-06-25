package com.example.notaritmo.audio

import android.content.Context
import java.io.BufferedInputStream
import java.io.BufferedOutputStream
import java.io.DataInputStream
import java.io.File
import java.io.FileInputStream
import java.io.FileOutputStream

class PcmSessionBuffer(context: Context) {
    private val dir = File(context.cacheDir, "pcm")
    private val file = File(dir, "voice_${System.currentTimeMillis()}.pcm16")
    private var output: BufferedOutputStream? = null
    private val scratch = ByteArray(8192)

    fun open() {
        if (!dir.exists() && !dir.mkdirs()) {
            throw IllegalStateException("Cannot create PCM cache: ${dir.absolutePath}")
        }
        output = BufferedOutputStream(FileOutputStream(file))
    }

    fun append(samples: ShortArray, count: Int) {
        val out = output ?: return
        var byteOffset = 0
        for (i in 0 until count) {
            val value = samples[i].toInt()
            scratch[byteOffset++] = (value and 0xff).toByte()
            scratch[byteOffset++] = ((value ushr 8) and 0xff).toByte()
            if (byteOffset == scratch.size) {
                out.write(scratch, 0, byteOffset)
                byteOffset = 0
            }
        }
        if (byteOffset > 0) {
            out.write(scratch, 0, byteOffset)
        }
    }

    fun close() {
        output?.flush()
        output?.close()
        output = null
    }

    fun readFloats(): FloatArray {
        close()
        val length = file.length()
        if (length <= 0L) return FloatArray(0)
        val sampleCount = (length / 2L).coerceAtMost(Int.MAX_VALUE.toLong()).toInt()
        val samples = FloatArray(sampleCount)
        val pair = ByteArray(2)
        DataInputStream(BufferedInputStream(FileInputStream(file))).use { input ->
            for (i in 0 until sampleCount) {
                input.readFully(pair)
                val value = ((pair[1].toInt() shl 8) or (pair[0].toInt() and 0xff)).toShort()
                samples[i] = value / 32768.0f
            }
        }
        return samples
    }

    fun delete() {
        close()
        if (file.exists()) file.delete()
    }
}
