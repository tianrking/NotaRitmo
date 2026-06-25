package com.example.notaritmo;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.database.Cursor;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.provider.OpenableColumns;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.EditText;
import android.widget.HorizontalScrollView;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.ScrollView;
import android.widget.Space;
import android.widget.TextView;
import android.widget.Toast;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.appcompat.app.AppCompatActivity;
import androidx.core.app.ActivityCompat;
import androidx.core.content.ContextCompat;

import com.example.notaritmo.data.RecordingItem;
import com.example.notaritmo.data.TranscriptSegment;
import com.example.notaritmo.engine.ModelDownloadListener;
import com.example.notaritmo.engine.OpenAiCompatibleLlmClient;
import com.example.notaritmo.engine.SherpaModelDownloader;
import com.example.notaritmo.models.VoiceModelBundle;
import com.example.notaritmo.models.VoiceModelRegistry;
import com.example.notaritmo.models.VoiceModelStatus;
import com.example.notaritmo.session.VoiceSessionController;
import com.example.notaritmo.session.VoiceSessionListener;
import com.google.android.material.button.MaterialButton;
import com.google.android.material.card.MaterialCardView;

import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;
import java.util.UUID;

public class MainActivity extends AppCompatActivity {
    private static final int REQ_AUDIO = 9;
    private static final int REQ_PICK_AUDIO = 12;

    private final Handler timer = new Handler(Looper.getMainLooper());

    private VoiceSessionController voiceSession;
    private SherpaModelDownloader modelDownloader;
    private RecordingItem currentItem;

    private LinearLayout timeline;
    private LinearLayout library;
    private TextView statusText;
    private TextView titleText;
    private TextView timerText;
    private TextView summaryText;
    private TextView stageText;
    private LinearLayout modelStatusList;
    private ProgressBar progress;
    private MaterialButton recordButton;
    private MaterialButton downloadModelButton;
    private EditText llmBaseInput;
    private EditText llmModelInput;
    private EditText llmKeyInput;

    private boolean realtimeAsrRunning;

    private final Runnable tick = new Runnable() {
        @Override
        public void run() {
            if (!realtimeAsrRunning) return;
            timerText.setText(formatDuration(voiceSession.elapsedSeconds()));
            timer.postDelayed(this, 500L);
        }
    };

    @Override
    protected void onCreate(@Nullable Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().setStatusBarColor(Color.rgb(23, 63, 61));
        voiceSession = new VoiceSessionController(getApplicationContext(), voiceSessionListener());
        setContentView(buildContent());
        seedInitialSession();
        renderCurrent();
        refreshModelStatus();
    }

    private View buildContent() {
        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        scroll.setBackgroundColor(Color.rgb(248, 240, 232));

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(dp(18), dp(18), dp(18), dp(24));
        scroll.addView(root, new ScrollView.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT
        ));

        root.addView(label("NotaRitmo", 30, Color.rgb(24, 32, 31), true));
        root.addView(label("Local-first meeting voice lab", 14, Color.rgb(74, 84, 81), false));
        root.addView(space(14));
        root.addView(buildStatusBand());
        root.addView(space(14));
        root.addView(buildRecorderCard());
        root.addView(space(14));
        root.addView(buildPipelineCard());
        root.addView(space(14));
        root.addView(buildTimelineCard());
        root.addView(space(14));
        root.addView(buildSummaryCard());
        root.addView(space(14));
        root.addView(buildLibraryCard());
        return scroll;
    }

    private View buildStatusBand() {
        HorizontalScrollView scroller = new HorizontalScrollView(this);
        scroller.setHorizontalScrollBarEnabled(false);
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        scroller.addView(row);
        addChip(row, "On-device ASR", true);
        addChip(row, "Realtime", true);
        addChip(row, "Refine", true);
        addChip(row, "Emotion tag", true);
        addChip(row, "LLM SaaS", false);
        return scroller;
    }

    private View buildRecorderCard() {
        MaterialCardView card = card();
        LinearLayout box = cardBody();
        card.addView(box);

        LinearLayout head = row();
        titleText = label("Untitled recording", 20, Color.rgb(24, 32, 31), true);
        head.addView(titleText, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
        timerText = label("00:00", 18, Color.rgb(39, 91, 88), true);
        head.addView(timerText);
        box.addView(head);

        statusText = label("Ready", 13, Color.rgb(92, 101, 98), false);
        box.addView(statusText);
        box.addView(space(14));

        LinearLayout actions = row();
        recordButton = button("Start live ASR");
        recordButton.setOnClickListener(v -> toggleLiveAsr());
        actions.addView(recordButton, new LinearLayout.LayoutParams(0, dp(46), 1f));
        actions.addView(spaceHorizontal(10));

        MaterialButton importButton = button("Import audio");
        importButton.setOnClickListener(v -> pickAudio());
        actions.addView(importButton, new LinearLayout.LayoutParams(0, dp(46), 1f));
        box.addView(actions);
        return card;
    }

    private View buildPipelineCard() {
        MaterialCardView card = card();
        LinearLayout box = cardBody();
        card.addView(box);
        box.addView(label("Voice pipeline", 18, Color.rgb(24, 32, 31), true));
        box.addView(space(8));
        stageText = label("Zipformer realtime -> SenseVoice refine -> LLM text summary", 13, Color.rgb(74, 84, 81), false);
        box.addView(stageText);
        box.addView(space(10));

        modelStatusList = new LinearLayout(this);
        modelStatusList.setOrientation(LinearLayout.VERTICAL);
        box.addView(modelStatusList);
        box.addView(space(10));

        progress = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        progress.setMax(100);
        progress.setProgress(0);
        box.addView(progress, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(10)));
        box.addView(space(12));

        downloadModelButton = button("Download ASR model");
        downloadModelButton.setOnClickListener(v -> downloadAsrModel());
        box.addView(downloadModelButton, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(44)));
        return card;
    }

    private View buildTimelineCard() {
        MaterialCardView card = card();
        LinearLayout box = cardBody();
        card.addView(box);
        box.addView(label("Transcript timeline", 18, Color.rgb(24, 32, 31), true));
        box.addView(space(8));
        timeline = new LinearLayout(this);
        timeline.setOrientation(LinearLayout.VERTICAL);
        box.addView(timeline);
        return card;
    }

    private View buildSummaryCard() {
        MaterialCardView card = card();
        LinearLayout box = cardBody();
        card.addView(box);
        box.addView(label("LLM workspace", 18, Color.rgb(24, 32, 31), true));
        box.addView(space(8));

        llmBaseInput = input("API Base, e.g. https://api.deepseek.com");
        llmBaseInput.setText(getPrefs("llm_base", "https://api.deepseek.com"));
        box.addView(llmBaseInput);
        box.addView(space(8));

        llmModelInput = input("Model, e.g. deepseek-chat");
        llmModelInput.setText(getPrefs("llm_model", "deepseek-chat"));
        box.addView(llmModelInput);
        box.addView(space(8));

        llmKeyInput = input("API Key");
        llmKeyInput.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
        llmKeyInput.setText(getPrefs("llm_key", ""));
        box.addView(llmKeyInput);
        box.addView(space(10));

        MaterialButton summarize = button("Summarize with SaaS LLM");
        summarize.setOnClickListener(v -> summarizeWithLlm());
        box.addView(summarize, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(44)));
        box.addView(space(12));

        summaryText = label("", 14, Color.rgb(42, 50, 48), false);
        summaryText.setLineSpacing(dp(2), 1.0f);
        box.addView(summaryText);
        return card;
    }

    private View buildLibraryCard() {
        MaterialCardView card = card();
        LinearLayout box = cardBody();
        card.addView(box);
        box.addView(label("Local library", 18, Color.rgb(24, 32, 31), true));
        box.addView(space(8));
        library = new LinearLayout(this);
        library.setOrientation(LinearLayout.VERTICAL);
        box.addView(library);
        return card;
    }

    private void downloadAsrModel() {
        if (modelDownloader == null) {
            modelDownloader = new SherpaModelDownloader(getApplicationContext(), new ModelDownloadListener() {
                @Override
                public void onProgress(String fileName, int percent, long downloadedBytes, long totalBytes) {
                    runOnUiThread(() -> {
                        progress.setProgress(percent);
                        stageText.setText("Downloading " + fileName + " " + percent + "%");
                        statusText.setText(formatBytes(downloadedBytes) + (totalBytes > 0 ? " / " + formatBytes(totalBytes) : ""));
                    });
                }

                @Override
                public void onComplete(String modelPath) {
                    runOnUiThread(() -> {
                        downloadModelButton.setEnabled(true);
                        progress.setProgress(100);
                        stageText.setText("Models installed:\n" + modelPath);
                        refreshModelStatus();
                        Toast.makeText(MainActivity.this, "ASR models ready", Toast.LENGTH_SHORT).show();
                    });
                }

                @Override
                public void onError(String message) {
                    runOnUiThread(() -> {
                        downloadModelButton.setEnabled(true);
                        downloadModelButton.setText("Retry ASR model download");
                        statusText.setText("Model download failed");
                        stageText.setText(message);
                        Toast.makeText(MainActivity.this, message, Toast.LENGTH_LONG).show();
                    });
                }
            });
        }

        if (modelDownloader.isModelReady()) {
            Toast.makeText(this, "ASR models are already ready.", Toast.LENGTH_SHORT).show();
            downloadModelButton.setText("ASR model ready");
            return;
        }
        if (modelDownloader.isRunning()) return;

        downloadModelButton.setEnabled(false);
        downloadModelButton.setText("Downloading...");
        progress.setProgress(0);
        stageText.setText("Preparing local ASR models");
        modelDownloader.start();
    }

    private void refreshModelStatus() {
        VoiceModelStatus status = VoiceModelRegistry.scan(getApplicationContext());
        renderModelStatusList(status);
        if (status.getReady()) {
            downloadModelButton.setText("ASR models scanned");
            statusText.setText("Local ASR models ready");
            stageText.setText("Models found locally. Start live ASR when ready.");
            progress.setProgress(100);
        } else {
            downloadModelButton.setText("Download missing ASR models");
            statusText.setText("ASR models need download");
            stageText.setText(status.getDisplayText());
            progress.setProgress(0);
        }
    }

    private void renderModelStatusList(VoiceModelStatus status) {
        modelStatusList.removeAllViews();
        for (VoiceModelBundle bundle : status.getBundles()) {
            LinearLayout row = row();
            row.setPadding(0, dp(4), 0, dp(4));
            row.addView(label(bundle.getLabel(), 13, Color.rgb(42, 50, 48), true), new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));

            boolean ready = bundle.isReady();
            TextView state = label(ready ? "Found" : "Missing", 12, ready ? Color.rgb(39, 91, 88) : Color.rgb(145, 67, 45), true);
            state.setGravity(Gravity.CENTER);
            state.setPadding(dp(10), dp(4), dp(10), dp(4));
            state.setBackgroundColor(ready ? Color.rgb(226, 240, 235) : Color.rgb(250, 225, 212));
            row.addView(state, new LinearLayout.LayoutParams(dp(96), ViewGroup.LayoutParams.WRAP_CONTENT));
            modelStatusList.addView(row);

            if (!ready) {
                String missing = "Missing: " + String.join(", ", bundle.missingFiles());
                modelStatusList.addView(label(missing, 12, Color.rgb(113, 83, 73), false));
            }
        }
    }

    private void toggleLiveAsr() {
        if (realtimeAsrRunning) {
            voiceSession.stop();
            return;
        }
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            ActivityCompat.requestPermissions(this, new String[]{Manifest.permission.RECORD_AUDIO}, REQ_AUDIO);
            return;
        }
        voiceSession.start();
    }

    private VoiceSessionListener voiceSessionListener() {
        return new VoiceSessionListener() {
            @Override
            public void onSessionStarted(RecordingItem item, String modelName) {
                runOnUiThread(() -> {
                    realtimeAsrRunning = true;
                    currentItem = item;
                    recordButton.setText("Stop live ASR");
                    statusText.setText("Running " + modelName);
                    progress.setProgress(48);
                    stageText.setText("Realtime ASR running on device");
                    renderCurrent();
                    timer.post(tick);
                });
            }

            @Override
            public void onPartial(String text, int finalSegmentCount) {
                runOnUiThread(() -> {
                    statusText.setText("Partial: " + text);
                    summaryText.setText("Partial\n" + text + "\n\nFinal segments: " + finalSegmentCount);
                });
            }

            @Override
            public void onRealtimeSegment(RecordingItem item) {
                runOnUiThread(() -> {
                    currentItem = item;
                    renderCurrent();
                });
            }

            @Override
            public void onRefining(String modelName) {
                runOnUiThread(() -> {
                    recordButton.setEnabled(false);
                    statusText.setText("Refining transcript locally");
                    stageText.setText("SenseVoice refine running: " + modelName);
                    summaryText.setText("Realtime text is ready.\n\nSenseVoice is re-decoding the captured audio locally for a more accurate final transcript.");
                });
            }

            @Override
            public void onRefined(RecordingItem item, String lang, String emotion, String event) {
                runOnUiThread(() -> {
                    currentItem = item;
                    recordButton.setEnabled(true);
                    statusText.setText("SenseVoice refined transcript ready");
                    stageText.setText("Realtime Zipformer + local SenseVoice refine complete");
                    progress.setProgress(100);
                    renderCurrent();
                });
            }

            @Override
            public void onRefineSkipped(String message) {
                runOnUiThread(() -> {
                    recordButton.setEnabled(true);
                    statusText.setText("Realtime ASR stopped");
                    stageText.setText("SenseVoice refine skipped");
                    summaryText.setText((currentItem != null ? currentItem.summary : "") + "\n\nRefine skipped: " + message);
                });
            }

            @Override
            public void onStopped(boolean hasTranscript) {
                runOnUiThread(() -> {
                    realtimeAsrRunning = false;
                    recordButton.setText("Start live ASR");
                    statusText.setText(hasTranscript ? "Realtime ASR stopped" : "Ready");
                    stageText.setText("Zipformer realtime -> SenseVoice refine -> LLM text summary");
                });
            }

            @Override
            public void onError(String message) {
                runOnUiThread(() -> {
                    realtimeAsrRunning = false;
                    recordButton.setText("Start live ASR");
                    statusText.setText("ASR unavailable");
                    summaryText.setText(message + "\n\nTap Download ASR model. The models are stored in the app's external files directory and used fully offline after download.");
                    Toast.makeText(MainActivity.this, message, Toast.LENGTH_LONG).show();
                });
            }
        };
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, @NonNull String[] permissions, @NonNull int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == REQ_AUDIO && grantResults.length > 0 && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
            voiceSession.start();
        }
    }

    private void summarizeWithLlm() {
        if (currentItem == null || currentItem.segments.isEmpty()) {
            Toast.makeText(this, "No finalized local ASR transcript yet.", Toast.LENGTH_SHORT).show();
            return;
        }
        String apiBase = llmBaseInput.getText().toString().trim();
        String model = llmModelInput.getText().toString().trim();
        String apiKey = llmKeyInput.getText().toString().trim();
        if (apiKey.isEmpty()) {
            Toast.makeText(this, "Fill API Key first.", Toast.LENGTH_SHORT).show();
            return;
        }
        savePrefs("llm_base", apiBase);
        savePrefs("llm_model", model);
        savePrefs("llm_key", apiKey);
        summaryText.setText("Calling LLM...");
        new Thread(() -> {
            try {
                String result = new OpenAiCompatibleLlmClient().summarize(apiBase, apiKey, model, transcriptForLlm());
                runOnUiThread(() -> {
                    currentItem.summary = result;
                    summaryText.setText(result);
                });
            } catch (Exception ex) {
                runOnUiThread(() -> summaryText.setText("LLM failed: " + ex.getMessage()));
            }
        }, "notaritmo-llm").start();
    }

    private void seedInitialSession() {
        currentItem = new RecordingItem(UUID.randomUUID().toString(), "Android local voice-core sketch", null);
        currentItem.status = "Ready";
        currentItem.durationLabel = "00:18";
        currentItem.segments.add(new TranscriptSegment(
                "00:00",
                "00:18",
                "Speaker 1",
                "Realtime",
                "Demo",
                "Local ASR shows text immediately, then SenseVoice refines the final transcript on device.",
                0.92f
        ));
        currentItem.summary = "Architecture: realtime Zipformer for low latency, local SenseVoice for final accuracy, SaaS LLM only for text summary.";
    }

    private void pickAudio() {
        Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT);
        intent.addCategory(Intent.CATEGORY_OPENABLE);
        intent.setType("audio/*");
        startActivityForResult(intent, REQ_PICK_AUDIO);
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, @Nullable Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == REQ_PICK_AUDIO && resultCode == Activity.RESULT_OK && data != null && data.getData() != null) {
            importAudio(data.getData());
        }
    }

    private void importAudio(Uri uri) {
        try {
            String name = displayName(uri);
            File dir = new File(getFilesDir(), "imports");
            if (!dir.exists() && !dir.mkdirs()) {
                throw new IllegalStateException("Cannot create import directory");
            }
            File target = new File(dir, System.currentTimeMillis() + "_" + sanitize(name));
            try (InputStream in = getContentResolver().openInputStream(uri);
                 FileOutputStream out = new FileOutputStream(target)) {
                if (in == null) throw new IllegalStateException("Cannot open audio");
                byte[] buffer = new byte[8192];
                int read;
                while ((read = in.read(buffer)) >= 0) {
                    out.write(buffer, 0, read);
                }
            }
            currentItem = new RecordingItem(UUID.randomUUID().toString(), stripExt(name), target);
            currentItem.status = "Imported";
            currentItem.summary = "Imported audio is stored locally. File-refine support is the next pipeline slot.";
            renderCurrent();
        } catch (Exception ex) {
            Toast.makeText(this, "Import failed: " + ex.getMessage(), Toast.LENGTH_LONG).show();
        }
    }

    private void renderCurrent() {
        if (currentItem == null) return;
        titleText.setText(currentItem.title);
        timerText.setText(currentItem.durationLabel);
        statusText.setText(currentItem.status);
        summaryText.setText(currentItem.summary);

        timeline.removeAllViews();
        if (currentItem.segments.isEmpty()) {
            timeline.addView(label("No transcript yet.", 14, Color.rgb(92, 101, 98), false));
        } else {
            for (TranscriptSegment segment : currentItem.segments) {
                timeline.addView(segmentView(segment));
                timeline.addView(space(8));
            }
        }

        library.removeAllViews();
        library.addView(libraryRow(currentItem));
    }

    private View segmentView(TranscriptSegment segment) {
        MaterialCardView card = card();
        card.setCardBackgroundColor(Color.rgb(255, 252, 246));
        LinearLayout box = cardBody();
        card.addView(box);
        LinearLayout top = row();
        top.addView(label(segment.startLabel + " - " + segment.endLabel, 12, Color.rgb(91, 100, 97), true), new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
        top.addView(label(Math.round(segment.confidence * 100) + "%", 12, Color.rgb(39, 91, 88), true));
        box.addView(top);
        box.addView(label(segment.speaker + " / " + segment.role + " / " + segment.emotion, 13, Color.rgb(145, 100, 45), true));
        box.addView(space(4));
        box.addView(label(segment.text, 15, Color.rgb(24, 32, 31), false));
        return card;
    }

    private View libraryRow(RecordingItem item) {
        LinearLayout row = row();
        row.setGravity(Gravity.CENTER_VERTICAL);
        TextView left = label(item.title + "\n" + item.durationLabel + " / " + item.status, 14, Color.rgb(42, 50, 48), false);
        row.addView(left, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
        return row;
    }

    private MaterialCardView card() {
        MaterialCardView card = new MaterialCardView(this);
        card.setRadius(dp(8));
        card.setCardElevation(dp(1));
        card.setStrokeWidth(dp(1));
        card.setStrokeColor(Color.argb(28, 24, 32, 31));
        card.setCardBackgroundColor(Color.WHITE);
        card.setUseCompatPadding(true);
        card.setLayoutParams(new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT
        ));
        return card;
    }

    private LinearLayout cardBody() {
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setPadding(dp(16), dp(14), dp(16), dp(16));
        return box;
    }

    private LinearLayout row() {
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setGravity(Gravity.CENTER_VERTICAL);
        return row;
    }

    private TextView label(String text, int sp, int color, boolean bold) {
        TextView view = new TextView(this);
        view.setText(text);
        view.setTextSize(sp);
        view.setTextColor(color);
        view.setIncludeFontPadding(true);
        if (bold) view.setTypeface(view.getTypeface(), android.graphics.Typeface.BOLD);
        return view;
    }

    private EditText input(String hint) {
        EditText edit = new EditText(this);
        edit.setHint(hint);
        edit.setSingleLine(true);
        edit.setTextSize(13);
        edit.setPadding(dp(12), 0, dp(12), 0);
        edit.setMinHeight(dp(44));
        return edit;
    }

    private MaterialButton button(String text) {
        MaterialButton button = new MaterialButton(this);
        button.setText(text);
        button.setTextSize(13);
        button.setAllCaps(false);
        button.setCornerRadius(dp(8));
        button.setMinHeight(dp(42));
        return button;
    }

    private void addChip(LinearLayout row, String text, boolean local) {
        TextView chip = label(text, 12, local ? Color.rgb(39, 91, 88) : Color.rgb(145, 100, 45), true);
        chip.setGravity(Gravity.CENTER);
        chip.setPadding(dp(12), dp(7), dp(12), dp(7));
        chip.setBackgroundColor(local ? Color.rgb(226, 240, 235) : Color.rgb(250, 231, 204));
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, dp(34));
        params.setMarginEnd(dp(8));
        row.addView(chip, params);
    }

    private Space space(int dp) {
        Space space = new Space(this);
        space.setLayoutParams(new LinearLayout.LayoutParams(1, dp(dp)));
        return space;
    }

    private Space spaceHorizontal(int dp) {
        Space space = new Space(this);
        space.setLayoutParams(new LinearLayout.LayoutParams(dp(dp), 1));
        return space;
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }

    private String formatDuration(long seconds) {
        return VoiceSessionController.formatDuration(seconds);
    }

    private String displayName(Uri uri) {
        try (Cursor cursor = getContentResolver().query(uri, null, null, null, null)) {
            if (cursor != null && cursor.moveToFirst()) {
                int index = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME);
                if (index >= 0) return cursor.getString(index);
            }
        }
        return "imported_audio.m4a";
    }

    private String sanitize(String value) {
        return value.replaceAll("[^a-zA-Z0-9._-]", "_");
    }

    private String stripExt(String name) {
        int dot = name.lastIndexOf('.');
        return dot > 0 ? name.substring(0, dot) : name;
    }

    private String formatBytes(long bytes) {
        if (bytes < 1024) return bytes + " B";
        double kb = bytes / 1024.0;
        if (kb < 1024) return String.format(Locale.US, "%.1f KB", kb);
        double mb = kb / 1024.0;
        return String.format(Locale.US, "%.1f MB", mb);
    }

    private String transcriptForLlm() {
        StringBuilder builder = new StringBuilder();
        for (TranscriptSegment segment : currentItem.segments) {
            builder.append("[")
                    .append(segment.startLabel)
                    .append("-")
                    .append(segment.endLabel)
                    .append("] ")
                    .append(segment.speaker)
                    .append(": ")
                    .append(segment.text)
                    .append("\n");
        }
        return builder.toString();
    }

    private String getPrefs(String key, String fallback) {
        return getSharedPreferences("notaritmo", MODE_PRIVATE).getString(key, fallback);
    }

    private void savePrefs(String key, String value) {
        getSharedPreferences("notaritmo", MODE_PRIVATE).edit().putString(key, value).apply();
    }
}
