package com.example.notaritmo.session;

import android.content.Context;

import com.example.notaritmo.data.RecordingItem;
import com.example.notaritmo.data.TranscriptSegment;
import com.example.notaritmo.engine.RealtimeAsrListener;
import com.example.notaritmo.engine.SherpaPunctuationRestorer;
import com.example.notaritmo.engine.SherpaRealtimeAsrEngine;

import java.util.Locale;
import java.util.UUID;

public class VoiceSessionController {
    private final Context context;
    private final VoiceSessionListener listener;

    private SherpaRealtimeAsrEngine engine;
    private RecordingItem currentItem;
    private boolean running;
    private long startedAt;
    private String hotwords = "";

    public VoiceSessionController(Context context, VoiceSessionListener listener) {
        this.context = context.getApplicationContext();
        this.listener = listener;
    }

    public boolean isRunning() {
        return running;
    }

    public RecordingItem currentItem() {
        return currentItem;
    }

    public long elapsedSeconds() {
        if (startedAt <= 0L) return 0L;
        return Math.max(0L, (System.currentTimeMillis() - startedAt) / 1000L);
    }

    public void start() {
        if (engine == null) {
            engine = new SherpaRealtimeAsrEngine(context, callbacks());
        }
        engine.start(hotwords);
    }

    public void stop() {
        if (engine != null) {
            engine.stop();
        }
    }

    public void setHotwords(String hotwords) {
        this.hotwords = hotwords == null ? "" : hotwords;
    }

    private RealtimeAsrListener callbacks() {
        return new RealtimeAsrListener() {
            @Override
            public void onReady(String modelName) {
                running = true;
                startedAt = System.currentTimeMillis();
                currentItem = new RecordingItem(UUID.randomUUID().toString(), "Live ASR " + clockLabel(), null);
                currentItem.status = "Realtime ASR";
                currentItem.summary = "Local streaming Zipformer is listening. SenseVoice will refine the final transcript after stop.";
                listener.onSessionStarted(currentItem, modelName);
            }

            @Override
            public void onPartial(String text) {
                int count = currentItem == null ? 0 : currentItem.segments.size();
                listener.onPartial(text, count);
            }

            @Override
            public void onFinal(String text) {
                if (currentItem == null) return;
                long elapsed = elapsedSeconds();
                String start = formatDuration(Math.max(0L, elapsed - 6L));
                String end = formatDuration(elapsed);
                currentItem.segments.add(new TranscriptSegment(
                        start,
                        end,
                        "Speaker 1",
                        "Realtime",
                        "Unrefined",
                        text,
                        0.90f
                ));
                currentItem.durationLabel = end;
                currentItem.status = "Realtime ASR";
                currentItem.summary = "Local ASR has produced " + currentItem.segments.size() + " finalized segment(s). SenseVoice will refine after stop.";
                listener.onRealtimeSegment(currentItem);
            }

            @Override
            public void onRefining(String modelName) {
                listener.onRefining(modelName);
            }

            @Override
            public void onRefined(String text, String lang, String emotion, String event) {
                if (currentItem == null) return;
                long elapsed = Math.max(1L, elapsedSeconds());
                String finalText = new SherpaPunctuationRestorer(context).restore(text);
                currentItem.segments.clear();
                currentItem.segments.add(new TranscriptSegment(
                        "00:00",
                        formatDuration(elapsed),
                        "Speaker 1",
                        isBlank(lang) ? "SenseVoice" : lang,
                        isBlank(emotion) ? "Refined" : emotion,
                        finalText,
                        0.96f
                ));
                currentItem.durationLabel = formatDuration(elapsed);
                currentItem.status = "Refined";
                currentItem.summary = "Final local SenseVoice transcript with offline punctuation.\nLanguage: " + lang + "\nEmotion: " + emotion + "\nEvent: " + event;
                listener.onRefined(currentItem, lang, emotion, event);
            }

            @Override
            public void onRefineSkipped(String message) {
                listener.onRefineSkipped(message);
            }

            @Override
            public void onStopped() {
                running = false;
                boolean hasTranscript = currentItem != null && !currentItem.segments.isEmpty();
                listener.onStopped(hasTranscript);
            }

            @Override
            public void onError(String message) {
                running = false;
                listener.onError(message);
            }
        };
    }

    private static boolean isBlank(String value) {
        return value == null || value.isEmpty();
    }

    private static String clockLabel() {
        java.text.SimpleDateFormat format = new java.text.SimpleDateFormat("HH:mm", Locale.US);
        return format.format(new java.util.Date());
    }

    public static String formatDuration(long seconds) {
        long min = seconds / 60L;
        long sec = seconds % 60L;
        return String.format(Locale.US, "%02d:%02d", min, sec);
    }
}
