package com.example.notaritmo.session;

import android.content.Context;

import com.example.notaritmo.data.RecordingItem;
import com.example.notaritmo.data.TranscriptSegment;
import com.example.notaritmo.engine.LocalTermNormalizer;
import com.example.notaritmo.engine.RealtimeAsrListener;
import com.example.notaritmo.engine.RefinedTranscriptSegment;
import com.example.notaritmo.engine.SenseVoiceTags;
import com.example.notaritmo.engine.SherpaPunctuationRestorer;
import com.example.notaritmo.engine.SherpaRealtimeAsrEngine;
import com.example.notaritmo.engine.TranscriptText;
import com.example.notaritmo.voiceprint.LocalVoiceprintStore;
import com.example.notaritmo.voiceprint.VoiceprintMatch;

import java.io.File;
import java.util.Comparator;
import java.util.List;
import java.util.Locale;
import java.util.UUID;

public class VoiceSessionController {
    private final Context context;
    private final VoiceSessionListener listener;

    private SherpaRealtimeAsrEngine engine;
    private RecordingItem currentItem;
    private final LocalTermNormalizer termNormalizer = new LocalTermNormalizer();
    private boolean running;
    private long startedAt;
    private String hotwords = "";
    private String pendingEnrollmentName = "";

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

    /**
     * Layer ⑤: load the user domain glossary into the local term normalizer.
     * Runs deterministically after decode, with or without a network.
     */
    public void setGlossary(String glossaryText) {
        termNormalizer.setUserGlossary(glossaryText);
    }

    public void enrollNextRecording(String name) {
        pendingEnrollmentName = name == null ? "" : name.trim();
    }

    public int voiceprintCount() {
        return new LocalVoiceprintStore(context).count();
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
                        termNormalizer.normalize(text),
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
                String finalText = TranscriptText.polish(
                        new SherpaPunctuationRestorer(context).restore(termNormalizer.normalize(text))
                );
                String displayLang = SenseVoiceTags.language(lang);
                String displayEmotion = SenseVoiceTags.emotion(emotion);
                String displayEvent = SenseVoiceTags.event(event);
                currentItem.segments.clear();
                if (!TranscriptText.hasMeaningfulSpeech(finalText)) {
                    currentItem.durationLabel = formatDuration(elapsed);
                    currentItem.status = "No speech";
                    currentItem.summary = "No clear speech was detected in this recording. The local models are ready; try speaking closer to the microphone or importing a cleaner audio file.";
                    listener.onRefined(currentItem, displayLang, displayEmotion, displayEvent);
                    return;
                }
                currentItem.segments.add(new TranscriptSegment(
                        "00:00",
                        formatDuration(elapsed),
                        "Speaker 1",
                        displayLang,
                        displayEmotion,
                        displayEvent,
                        finalText,
                        0.96f
                ));
                currentItem.durationLabel = formatDuration(elapsed);
                currentItem.status = "Refined";
                currentItem.summary = "Final local SenseVoice transcript with offline punctuation and term normalization."
                        + "\nLanguage: " + displayLang
                        + "\nEmotion: " + displayEmotion
                        + "\nEvent: " + displayEvent;
                listener.onRefined(currentItem, displayLang, displayEmotion, displayEvent);
            }

            @Override
            public void onRefinedSegments(List<RefinedTranscriptSegment> segments) {
                if (currentItem == null || segments == null || segments.isEmpty()) return;
                SherpaPunctuationRestorer punctuation = new SherpaPunctuationRestorer(context);
                LocalVoiceprintStore voiceprints = new LocalVoiceprintStore(context);
                RefinedTranscriptSegment enrollmentSegment = pickEnrollmentSegment(segments);
                if (!pendingEnrollmentName.isEmpty() && enrollmentSegment != null) {
                    voiceprints.save(pendingEnrollmentName, enrollmentSegment.getEmbedding());
                }
                currentItem.segments.clear();
                String lang = "";
                String emotion = "";
                String event = "";
                float endSeconds = 0f;
                for (RefinedTranscriptSegment segment : segments) {
                    if (segment.getText().isEmpty()) continue;
                    VoiceprintMatch match = voiceprints.search(segment.getEmbedding(), 0.58f);
                    String speaker = match == null
                            ? segment.getSpeaker()
                            : match.getName() + " (" + segment.getSpeaker() + ")";
                    if (lang.isEmpty() && !segment.getLang().isEmpty()) lang = segment.getLang();
                    if (emotion.isEmpty() && !segment.getEmotion().isEmpty()) emotion = segment.getEmotion();
                    if (event.isEmpty() && !segment.getEvent().isEmpty()) event = segment.getEvent();
                    endSeconds = Math.max(endSeconds, segment.getEndSeconds());
                    String finalText = TranscriptText.polish(
                            punctuation.restore(termNormalizer.normalize(segment.getText()))
                    );
                    if (!TranscriptText.hasMeaningfulSpeech(finalText)) continue;
                    currentItem.segments.add(new TranscriptSegment(
                            formatDuration(segment.getStartSeconds()),
                            formatDuration(segment.getEndSeconds()),
                            speaker,
                            SenseVoiceTags.language(segment.getLang()),
                            SenseVoiceTags.emotion(segment.getEmotion()),
                            SenseVoiceTags.event(segment.getEvent()),
                            finalText,
                            0.96f
                    ));
                }
                currentItem.durationLabel = formatDuration(Math.max(endSeconds, elapsedSeconds()));
                String displayLang = SenseVoiceTags.language(lang);
                String displayEmotion = SenseVoiceTags.emotion(emotion);
                String displayEvent = SenseVoiceTags.event(event);
                if (currentItem.segments.isEmpty()) {
                    pendingEnrollmentName = "";
                    currentItem.status = "No speech";
                    currentItem.summary = "No clear speech was detected in this recording. The local models are ready; try speaking closer to the microphone or importing a cleaner audio file.";
                    listener.onRefined(currentItem, displayLang, displayEmotion, displayEvent);
                    return;
                }
                currentItem.status = "Refined";
                String enrollmentLine = pendingEnrollmentName.isEmpty()
                        ? ""
                        : "\nVoiceprint enrolled: " + pendingEnrollmentName;
                pendingEnrollmentName = "";
                currentItem.summary = "Final local diarized SenseVoice transcript with offline punctuation and term normalization."
                        + "\nLanguage: " + displayLang
                        + "\nEmotion: " + displayEmotion
                        + "\nEvent: " + displayEvent
                        + enrollmentLine;
                listener.onRefined(currentItem, displayLang, displayEmotion, displayEvent);
            }

            @Override
            public void onRefineSkipped(String message) {
                listener.onRefineSkipped(message);
            }

            @Override
            public void onAudioSaved(File audioFile) {
                if (currentItem == null || audioFile == null) return;
                currentItem.audioFile = audioFile;
                listener.onRealtimeSegment(currentItem);
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

    private static RefinedTranscriptSegment pickEnrollmentSegment(List<RefinedTranscriptSegment> segments) {
        return segments.stream()
                .filter(segment -> segment.getEmbedding().length > 0)
                .max(Comparator.comparingDouble(segment -> segment.getEndSeconds() - segment.getStartSeconds()))
                .orElse(null);
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

    public static String formatDuration(float seconds) {
        return formatDuration(Math.max(0L, Math.round(seconds)));
    }
}
