package com.example.notaritmo.data;

public class TranscriptSegment {
    public final String startLabel;
    public final String endLabel;
    public final String speaker;
    public final String role;
    public final String emotion;
    public final String event;
    public final String text;
    public final float confidence;

    public TranscriptSegment(
            String startLabel,
            String endLabel,
            String speaker,
            String role,
            String emotion,
            String text,
            float confidence
    ) {
        this(startLabel, endLabel, speaker, role, emotion, "", text, confidence);
    }

    public TranscriptSegment(
            String startLabel,
            String endLabel,
            String speaker,
            String role,
            String emotion,
            String event,
            String text,
            float confidence
    ) {
        this.startLabel = startLabel;
        this.endLabel = endLabel;
        this.speaker = speaker;
        this.role = role;
        this.emotion = emotion;
        this.event = event;
        this.text = text;
        this.confidence = confidence;
    }
}
