package com.example.notaritmo.data;

import java.io.File;
import java.util.ArrayList;
import java.util.List;

public class RecordingItem {
    public final String id;
    public String title;
    public File audioFile;
    public String durationLabel;
    public String status;
    public String summary;
    public final List<TranscriptSegment> segments = new ArrayList<>();
    public final List<String> localKeywords = new ArrayList<>();
    public final List<String> llmKeywords = new ArrayList<>();
    public final List<String> correctedKeywords = new ArrayList<>();

    public RecordingItem(String id, String title, File audioFile) {
        this.id = id;
        this.title = title;
        this.audioFile = audioFile;
        this.durationLabel = "00:00";
        this.status = "Ready";
        this.summary = "Waiting for local voice-core.";
    }
}
