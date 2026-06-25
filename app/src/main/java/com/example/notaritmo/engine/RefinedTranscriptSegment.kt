package com.example.notaritmo.engine

data class RefinedTranscriptSegment(
    val startSeconds: Float,
    val endSeconds: Float,
    val speaker: String,
    val text: String,
    val lang: String,
    val emotion: String,
    val event: String,
)
