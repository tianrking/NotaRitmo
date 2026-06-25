package com.example.notaritmo.engine

data class DiarizedSpeechSegment(
    val startSeconds: Float,
    val endSeconds: Float,
    val speaker: String,
    val samples: FloatArray,
)
