package com.example.notaritmo.voiceprint

import android.content.Context
import android.util.Base64
import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlin.math.sqrt

class LocalVoiceprintStore(context: Context) {
    private val prefs = context.getSharedPreferences("notaritmo_voiceprints", Context.MODE_PRIVATE)

    fun save(name: String, embedding: FloatArray) {
        val clean = name.trim()
        if (clean.isEmpty() || embedding.isEmpty()) return
        prefs.edit().putString(clean, encode(embedding)).apply()
    }

    fun search(embedding: FloatArray, threshold: Float = 0.58f): VoiceprintMatch? {
        if (embedding.isEmpty()) return null
        var bestName = ""
        var bestScore = -1f
        for ((name, value) in prefs.all) {
            val stored = decode(value as? String ?: continue)
            val score = cosine(embedding, stored)
            if (score > bestScore) {
                bestName = name
                bestScore = score
            }
        }
        return if (bestName.isNotEmpty() && bestScore >= threshold) {
            VoiceprintMatch(bestName, bestScore)
        } else {
            null
        }
    }

    fun count(): Int = prefs.all.size

    private fun encode(values: FloatArray): String {
        val buffer = ByteBuffer.allocate(values.size * 4).order(ByteOrder.LITTLE_ENDIAN)
        values.forEach { buffer.putFloat(it) }
        return Base64.encodeToString(buffer.array(), Base64.NO_WRAP)
    }

    private fun decode(value: String): FloatArray {
        val bytes = Base64.decode(value, Base64.NO_WRAP)
        val buffer = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN)
        val result = FloatArray(bytes.size / 4)
        for (i in result.indices) {
            result[i] = buffer.float
        }
        return result
    }

    private fun cosine(a: FloatArray, b: FloatArray): Float {
        if (a.isEmpty() || b.isEmpty() || a.size != b.size) return -1f
        var dot = 0.0
        var normA = 0.0
        var normB = 0.0
        for (i in a.indices) {
            dot += (a[i] * b[i]).toDouble()
            normA += (a[i] * a[i]).toDouble()
            normB += (b[i] * b[i]).toDouble()
        }
        val denom = sqrt(normA) * sqrt(normB)
        if (denom <= 0.0) return -1f
        return (dot / denom).toFloat()
    }
}
