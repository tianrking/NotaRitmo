package com.example.notaritmo.session;

import com.example.notaritmo.data.RecordingItem;

public interface VoiceSessionListener {
    void onSessionStarted(RecordingItem item, String modelName);

    void onPartial(String text, int finalSegmentCount);

    void onRealtimeSegment(RecordingItem item);

    void onRefining(String modelName);

    void onRefined(RecordingItem item, String lang, String emotion, String event);

    void onRefineSkipped(String message);

    void onStopped(boolean hasTranscript);

    void onError(String message);
}
