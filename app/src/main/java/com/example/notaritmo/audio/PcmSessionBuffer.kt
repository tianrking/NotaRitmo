package com.example.notaritmo.audio

import android.content.Context
import java.io.BufferedInputStream
import java.io.BufferedOutputStream
import java.io.DataInputStream
import java.io.DataOutputStream
import java.io.File
import java.io.FileInputStream
import java.io.FileOutputStream

class PcmSessionBuffer(context: Context) {
    private val appContext = context.applicationContext
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

    fun exportWav(samples: FloatArray, title: String = "live_recording", sampleRate: Int = 16000): File {
        val outDir = appContext.getExternalFilesDir("recordings") ?: File(appContext.filesDir, "recordings")
        if (!outDir.exists() && !outDir.mkdirs()) {
            throw IllegalStateException("Cannot create recordings directory: ${outDir.absolutePath}")
        }
        val safeTitle = title
            .replace(Regex("[^A-Za-z0-9._-]+"), "_")
            .trim('_')
            .ifEmpty { "live_recording" }
        val wav = File(outDir, "${System.currentTimeMillis()}_$safeTitle.wav")
        DataOutputStream(BufferedOutputStream(FileOutputStream(wav))).use { out ->
            writeAscii(out, "RIFF")
            writeIntLE(out, 36 + samples.size * 2)
            writeAscii(out, "WAVE")
            writeAscii(out, "fmt ")
            writeIntLE(out, 16)
            writeShortLE(out, 1)
            writeShortLE(out, 1)
            writeIntLE(out, sampleRate)
            writeIntLE(out, sampleRate * 2)
            writeShortLE(out, 2)
            writeShortLE(out, 16)
            writeAscii(out, "data")
            writeIntLE(out, samples.size * 2)
            samples.forEach { sample ->
                val value = (sample.coerceIn(-1f, 1f) * 32767f).toInt().toShort()
                writeShortLE(out, value.toInt())
            }
        }
        return wav
    }

    fun delete() {
        close()
        if (file.exists()) file.delete()
    }

    private fun writeAscii(out: DataOutputStream, text: String) {
        out.write(text.toByteArray(Charsets.US_ASCII))
    }

    private fun writeIntLE(out: DataOutputStream, value: Int) {
        out.writeByte(value and 0xff)
        out.writeByte((value ushr 8) and 0xff)
        out.writeByte((value ushr 16) and 0xff)
        out.writeByte((value ushr 24) and 0xff)
    }

    private fun writeShortLE(out: DataOutputStream, value: Int) {
        out.writeByte(value and 0xff)
        out.writeByte((value ushr 8) and 0xff)
    }
}
