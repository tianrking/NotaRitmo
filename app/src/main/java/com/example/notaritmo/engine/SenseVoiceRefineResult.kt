package com.example.notaritmo.engine

data class SenseVoiceRefineResult(
    val text: String,
    val lang: String,
    val emotion: String,
    val event: String,
)
