package com.example.notaritmo.audio

import android.content.Context
import android.media.MediaCodec
import android.media.MediaExtractor
import android.media.MediaFormat
import android.net.Uri
import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlin.math.roundToInt

class AndroidAudioDecoder(
    private val context: Context,
) {
    fun decodeTo16kMono(uri: Uri): FloatArray {
        val extractor = MediaExtractor()
        extractor.setDataSource(context, uri, null)
        val trackIndex = findAudioTrack(extractor)
        if (trackIndex < 0) {
            extractor.release()
            throw IllegalArgumentException("No audio track found")
        }

        extractor.selectTrack(trackIndex)
        val inputFormat = extractor.getTrackFormat(trackIndex)
        val mime = inputFormat.getString(MediaFormat.KEY_MIME)
            ?: throw IllegalArgumentException("Audio MIME is missing")
        val codec = MediaCodec.createDecoderByType(mime)
        codec.configure(inputFormat, null, null, 0)
        codec.start()

        val chunks = mutableListOf<FloatArray>()
        var sawInputEnd = false
        var sawOutputEnd = false
        var outputSampleRate = inputFormat.getInteger(MediaFormat.KEY_SAMPLE_RATE)
        var outputChannels = inputFormat.getInteger(MediaFormat.KEY_CHANNEL_COUNT)
        val info = MediaCodec.BufferInfo()

        try {
            while (!sawOutputEnd) {
                if (!sawInputEnd) {
                    val inputIndex = codec.dequeueInputBuffer(10_000)
                    if (inputIndex >= 0) {
                        val inputBuffer = codec.getInputBuffer(inputIndex)
                        if (inputBuffer != null) {
                            val sampleSize = extractor.readSampleData(inputBuffer, 0)
                            if (sampleSize < 0) {
                                codec.queueInputBuffer(
                                    inputIndex,
                                    0,
                                    0,
                                    0L,
                                    MediaCodec.BUFFER_FLAG_END_OF_STREAM,
                                )
                                sawInputEnd = true
                            } else {
                                codec.queueInputBuffer(
                                    inputIndex,
                                    0,
                                    sampleSize,
                                    extractor.sampleTime,
                                    0,
                                )
                                extractor.advance()
                            }
                        }
                    }
                }

                when (val outputIndex = codec.dequeueOutputBuffer(info, 10_000)) {
                    MediaCodec.INFO_OUTPUT_FORMAT_CHANGED -> {
                        val format = codec.outputFormat
                        outputSampleRate = format.getInteger(MediaFormat.KEY_SAMPLE_RATE)
                        outputChannels = format.getInteger(MediaFormat.KEY_CHANNEL_COUNT)
                    }

                    MediaCodec.INFO_TRY_AGAIN_LATER -> {
                    }

                    else -> if (outputIndex >= 0) {
                        val outputBuffer = codec.getOutputBuffer(outputIndex)
                        if (outputBuffer != null && info.size > 0) {
                            chunks.add(readPcm16(outputBuffer, info.offset, info.size, outputChannels))
                        }
                        sawOutputEnd = (info.flags and MediaCodec.BUFFER_FLAG_END_OF_STREAM) != 0
                        codec.releaseOutputBuffer(outputIndex, false)
                    }
                }
            }
        } finally {
            codec.stop()
            codec.release()
            extractor.release()
        }

        return resample(concat(chunks), outputSampleRate, 16_000)
    }

    private fun findAudioTrack(extractor: MediaExtractor): Int {
        for (i in 0 until extractor.trackCount) {
            val format = extractor.getTrackFormat(i)
            val mime = format.getString(MediaFormat.KEY_MIME) ?: continue
            if (mime.startsWith("audio/")) return i
        }
        return -1
    }

    private fun readPcm16(buffer: ByteBuffer, offset: Int, size: Int, channels: Int): FloatArray {
        val pcm = buffer.duplicate().order(ByteOrder.LITTLE_ENDIAN)
        pcm.position(offset)
        pcm.limit(offset + size)
        val frameCount = size / (2 * channels.coerceAtLeast(1))
        val mono = FloatArray(frameCount)
        for (frame in 0 until frameCount) {
            var sum = 0f
            for (ch in 0 until channels.coerceAtLeast(1)) {
                sum += pcm.short / 32768f
            }
            mono[frame] = sum / channels.coerceAtLeast(1)
        }
        return mono
    }

    private fun concat(chunks: List<FloatArray>): FloatArray {
        val total = chunks.sumOf { it.size }
        val result = FloatArray(total)
        var offset = 0
        for (chunk in chunks) {
            chunk.copyInto(result, offset)
            offset += chunk.size
        }
        return result
    }

    private fun resample(samples: FloatArray, sourceRate: Int, targetRate: Int): FloatArray {
        if (samples.isEmpty() || sourceRate == targetRate) return samples
        val targetSize = ((samples.size.toDouble() * targetRate) / sourceRate).roundToInt()
        val result = FloatArray(targetSize)
        val ratio = sourceRate.toDouble() / targetRate
        for (i in result.indices) {
            val source = i * ratio
            val left = source.toInt().coerceIn(0, samples.lastIndex)
            val right = (left + 1).coerceIn(0, samples.lastIndex)
            val frac = (source - left).toFloat()
            result[i] = samples[left] * (1f - frac) + samples[right] * frac
        }
        return result
    }
}
