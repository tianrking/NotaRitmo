package com.example.notaritmo.engine;

import java.util.List;

public interface RealtimeAsrListener {
    void onReady(String modelName);

    void onPartial(String text);

    void onFinal(String text);

    default void onRefining(String modelName) {
    }

    default void onRefined(String text, String lang, String emotion, String event) {
    }

    default void onRefinedSegments(List<RefinedTranscriptSegment> segments) {
    }

    default void onRefineSkipped(String message) {
    }

    void onStopped();

    void onError(String message);
}
