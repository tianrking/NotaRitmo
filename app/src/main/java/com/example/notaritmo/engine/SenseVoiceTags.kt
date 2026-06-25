package com.example.notaritmo.engine

import java.util.Locale

object SenseVoiceTags {
    @JvmStatic
    fun language(raw: String?): String {
        return when (val tag = clean(raw).lowercase(Locale.US)) {
            "zh", "zh-cn", "yue" -> "Chinese"
            "en" -> "English"
            "ja", "jp" -> "Japanese"
            "ko" -> "Korean"
            "es" -> "Spanish"
            "fr" -> "French"
            "de" -> "German"
            "ru" -> "Russian"
            "auto", "unknown", "" -> "Auto"
            "nospeech", "no_speech", "no speech", "silence" -> "No speech"
            else -> title(tag)
        }
    }

    @JvmStatic
    fun emotion(raw: String?): String {
        var tag = clean(raw)
        if (tag.uppercase(Locale.US).startsWith("EMO_")) {
            tag = tag.substring(4)
        }
        return when (tag.lowercase(Locale.US)) {
            "", "unknown", "neutral" -> "Neutral"
            "happy", "happiness" -> "Happy"
            "sad", "sadness" -> "Sad"
            "angry", "anger" -> "Angry"
            "fear", "fearful" -> "Fearful"
            "disgust" -> "Disgust"
            "surprise", "surprised" -> "Surprised"
            else -> title(tag)
        }
    }

    @JvmStatic
    fun event(raw: String?): String {
        return when (val tag = clean(raw).lowercase(Locale.US)) {
            "", "unknown", "speech" -> "Speech"
            "laughter", "laugh" -> "Laughter"
            "applause" -> "Applause"
            "cough", "coughing" -> "Cough"
            "sneeze", "sneezing" -> "Sneeze"
            "noise", "background_noise", "background noise" -> "Noise"
            "music" -> "Music"
            "crying", "cry" -> "Crying"
            "silence" -> "Silence"
            else -> title(tag.replace('_', ' '))
        }
    }

    private fun clean(raw: String?): String {
        return raw
            ?.replace("<", "")
            ?.replace(">", "")
            ?.replace("|", "")
            ?.trim()
            .orEmpty()
    }

    private fun title(value: String): String {
        return value
            .split(Regex("\\s+"))
            .filter { it.isNotEmpty() }
            .joinToString(" ") { part ->
                part.substring(0, 1).uppercase(Locale.US) +
                    part.drop(1).lowercase(Locale.US)
            }
    }
}
