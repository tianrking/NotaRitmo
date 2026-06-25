package com.example.notaritmo.engine

import com.example.notaritmo.data.TranscriptSegment

data class OfflineTranscriptionResult(
    val segments: List<TranscriptSegment>,
    val durationLabel: String,
    val summary: String,
)
