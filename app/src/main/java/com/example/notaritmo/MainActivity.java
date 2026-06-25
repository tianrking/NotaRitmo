package com.example.notaritmo;

import android.Manifest;
import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.database.Cursor;
import android.graphics.Color;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.provider.OpenableColumns;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowManager;
import android.view.inputmethod.InputMethodManager;
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
import com.example.notaritmo.engine.OfflineAudioTranscriber;
import com.example.notaritmo.engine.OfflineTranscriptionResult;
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
    private EditText hotwordsInput;

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
        getWindow().setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_STATE_ALWAYS_HIDDEN
                | WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE);
        voiceSession = new VoiceSessionController(getApplicationContext(), voiceSessionListener());
        setContentView(buildContent());
        seedInitialSession();
        renderCurrent();
        refreshModelStatus();
        clearInputFocusAndHideKeyboard();
    }

    private View buildContent() {
        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        scroll.setBackgroundColor(Color.rgb(248, 240, 232));

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setFocusable(true);
        root.setFocusableInTouchMode(true);
        root.setPadding(dp(18), dp(18), dp(18), dp(24));
        root.requestFocus();
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
        root.addView(buildHotwordsCard());
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
        addChip(row, "Diarization", true);
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
        importButton.setOnClickListener(v -> {
            clearInputFocusAndHideKeyboard();
            pickAudio();
        });
        actions.addView(importButton, new LinearLayout.LayoutParams(0, dp(46), 1f));
        box.addView(actions);
        return card;
    }

    private View buildPipelineCard() {
        MaterialCardView card = card();
        LinearLayout box = cardBody();
        card.addView(box);
        box.addView(label("Voice pipeline", 18, Color.rgb(24, 32, 31), true));
        stageText = label("", 1, Color.TRANSPARENT, false);
        box.addView(space(12));

        modelStatusList = new LinearLayout(this);
        modelStatusList.setOrientation(LinearLayout.VERTICAL);
        box.addView(modelStatusList);
        box.addView(space(12));

        progress = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        progress.setMax(100);
        progress.setProgress(0);
        box.addView(progress, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(10)));
        box.addView(space(12));

        downloadModelButton = button("Download ASR model");
        downloadModelButton.setOnClickListener(v -> {
            clearInputFocusAndHideKeyboard();
            downloadAsrModel();
        });
        box.addView(downloadModelButton, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(44)));
        return card;
    }

    private View buildHotwordsCard() {
        MaterialCardView card = card();
        LinearLayout box = cardBody();
        card.addView(box);
        box.addView(label("Hotwords / glossary", 18, Color.rgb(24, 32, 31), true));
        box.addView(label("每行一个词。写  术语=误识1,误识2  可自动纠正误识。", 12, Color.rgb(92, 101, 98), false));
        box.addView(label("解码期浅融合 ① + 本地词表替换 ⑤(始终生效);联网时还可点 LLM 纠错 ④。", 12, Color.rgb(92, 101, 98), false));
        box.addView(space(8));

        hotwordsInput = new EditText(this);
        hotwordsInput.setHint("NotaRitmo\nAndroid\nZipformer");
        hotwordsInput.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_MULTI_LINE);
        hotwordsInput.setSingleLine(false);
        hotwordsInput.setMinLines(3);
        hotwordsInput.setGravity(Gravity.TOP);
        hotwordsInput.setTextSize(13);
        hotwordsInput.setTypeface(android.graphics.Typeface.MONOSPACE);
        hotwordsInput.setTextColor(Color.rgb(24, 32, 31));
        hotwordsInput.setHintTextColor(Color.rgb(122, 132, 128));
        hotwordsInput.setPadding(dp(12), dp(8), dp(12), dp(8));
        hotwordsInput.setBackground(inputBackground());
        hotwordsInput.setText(getPrefs("hotwords", defaultHotwords()));
        box.addView(hotwordsInput, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(108)));
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

        llmBaseInput = input("API Base, OpenAI or Anthropic compatible");
        llmBaseInput.setText(getPrefs("llm_base", BuildConfig.DEFAULT_LLM_BASE));
        box.addView(llmBaseInput);
        box.addView(space(8));

        llmModelInput = input("Model, e.g. glm-5.2");
        llmModelInput.setText(getPrefs("llm_model", BuildConfig.DEFAULT_LLM_MODEL));
        box.addView(llmModelInput);
        box.addView(space(8));

        llmKeyInput = input("API Key");
        llmKeyInput.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
        llmKeyInput.setText(getPrefs("llm_key", BuildConfig.DEFAULT_LLM_API_KEY));
        box.addView(llmKeyInput);
        box.addView(space(10));

        MaterialButton summarize = button("Summarize with SaaS LLM");
        summarize.setOnClickListener(v -> {
            clearInputFocusAndHideKeyboard();
            summarizeWithLlm();
        });
        box.addView(summarize, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(44)));
        box.addView(space(8));

        MaterialButton correct = button("Correct transcript with LLM");
        correct.setOnClickListener(v -> {
            clearInputFocusAndHideKeyboard();
            correctWithLlm();
        });
        box.addView(correct, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(44)));
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
            progress.setProgress(100);
        } else {
            downloadModelButton.setText("Download missing ASR models");
            statusText.setText("ASR models need download");
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
        }
    }

    private void toggleLiveAsr() {
        clearInputFocusAndHideKeyboard();
        if (realtimeAsrRunning) {
            voiceSession.stop();
            return;
        }
        startLiveAsr();
    }

    private void startLiveAsr() {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            ActivityCompat.requestPermissions(this, new String[]{Manifest.permission.RECORD_AUDIO}, REQ_AUDIO);
            return;
        }
        applyHotwordsToSession();
        voiceSession.start();
    }

    /** Push the hotwords/glossary field into the session (layer ① + ⑤) and persist it. */
    private void applyHotwordsToSession() {
        String raw = hotwordsInput.getText().toString();
        savePrefs("hotwords", raw);
        voiceSession.setHotwords(canonicalHotwords(raw));
        voiceSession.setGlossary(raw);
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
                    stageText.setText("Realtime Zipformer + local speaker-aware SenseVoice refine complete");
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
            applyHotwordsToSession();
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

    /** Layer ④: optional LLM post-correction. Sends the numbered transcript plus the
     *  domain glossary to an OpenAI-compatible endpoint and maps corrected lines
     *  back onto the segments. Only final text leaves the device; raw audio never does. */
    private void correctWithLlm() {
        if (currentItem == null || currentItem.segments.isEmpty()) {
            Toast.makeText(this, "No finalized local ASR transcript yet.", Toast.LENGTH_SHORT).show();
            return;
        }
        final String apiBase = llmBaseInput.getText().toString().trim();
        final String model = llmModelInput.getText().toString().trim();
        final String apiKey = llmKeyInput.getText().toString().trim();
        if (apiKey.isEmpty()) {
            Toast.makeText(this, "Fill API Key first.", Toast.LENGTH_SHORT).show();
            return;
        }
        savePrefs("llm_base", apiBase);
        savePrefs("llm_model", model);
        savePrefs("llm_key", apiKey);

        final StringBuilder numbered = new StringBuilder();
        for (int i = 0; i < currentItem.segments.size(); i++) {
            numbered.append(i + 1).append(". ").append(currentItem.segments.get(i).text).append('\n');
        }
        final String glossary = hotwordsInput.getText().toString();
        savePrefs("hotwords", glossary);
        summaryText.setText("Correcting transcript with LLM...");
        new Thread(() -> {
            try {
                final String out = new OpenAiCompatibleLlmClient().correct(apiBase, apiKey, model, numbered.toString(), glossary);
                runOnUiThread(() -> applyCorrection(out));
            } catch (Exception ex) {
                runOnUiThread(() -> summaryText.setText("LLM correction failed: " + ex.getMessage()));
            }
        }, "notaritmo-llm-correct").start();
    }

    private void applyCorrection(String out) {
        if (currentItem == null || currentItem.segments.isEmpty()) return;
        java.util.Map<Integer, String> map = new java.util.HashMap<>();
        for (String line : out.split("\\R")) {
            String trimmed = line.trim();
            if (trimmed.isEmpty()) continue;
            int dot = trimmed.indexOf('.');
            if (dot <= 0) continue;
            try {
                int idx = Integer.parseInt(trimmed.substring(0, dot).trim()) - 1;
                String text = trimmed.substring(dot + 1).trim();
                if (idx >= 0 && !text.isEmpty()) {
                    map.put(idx, text);
                }
            } catch (NumberFormatException ignored) {
            }
        }
        if (map.isEmpty()) {
            summaryText.setText("LLM returned (no numbered lines parsed):\n\n" + out);
            return;
        }
        int updated = 0;
        for (int i = 0; i < currentItem.segments.size(); i++) {
            String text = map.get(i);
            if (text != null) {
                currentItem.segments.get(i).text = text;
                updated++;
            }
        }
        currentItem.summary = "Transcript corrected with LLM against the domain glossary (" + updated + " segment(s) updated).";
        renderCurrent();
        Toast.makeText(this, "Corrected " + updated + " segment(s)", Toast.LENGTH_SHORT).show();
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
            currentItem.status = "Transcribing";
            currentItem.summary = "Imported audio is stored locally. Offline SenseVoice transcription is running.";
            renderCurrent();
            transcribeImportedAudio(target);
        } catch (Exception ex) {
            Toast.makeText(this, "Import failed: " + ex.getMessage(), Toast.LENGTH_LONG).show();
        }
    }

    private void transcribeImportedAudio(File audioFile) {
        statusText.setText("Transcribing imported audio");
        stageText.setText("Local file decode -> speaker/VAD segments -> SenseVoice refine");
        progress.setProgress(64);
        new Thread(() -> {
            try {
                OfflineAudioTranscriber transcriber = new OfflineAudioTranscriber(getApplicationContext());
                String rawHw = hotwordsInput.getText().toString();
                savePrefs("hotwords", rawHw);
                transcriber.setHotwords(canonicalHotwords(rawHw));
                transcriber.setGlossaryText(rawHw);
                OfflineTranscriptionResult result = transcriber.transcribe(Uri.fromFile(audioFile));
                runOnUiThread(() -> {
                    if (currentItem == null) return;
                    currentItem.segments.clear();
                    currentItem.segments.addAll(result.getSegments());
                    currentItem.durationLabel = result.getDurationLabel();
                    currentItem.status = "Transcribed";
                    currentItem.summary = result.getSummary();
                    statusText.setText("Imported audio transcribed offline");
                    stageText.setText("Offline file transcription complete");
                    progress.setProgress(100);
                    renderCurrent();
                });
            } catch (Exception ex) {
                runOnUiThread(() -> {
                    if (currentItem != null) {
                        currentItem.status = "Imported";
                        currentItem.summary = "Imported audio is stored locally.\n\nOffline transcription failed: " + ex.getMessage();
                    }
                    statusText.setText("Imported audio stored");
                    stageText.setText("Offline file transcription failed");
                    renderCurrent();
                    Toast.makeText(this, "File ASR failed: " + ex.getMessage(), Toast.LENGTH_LONG).show();
                });
            }
        }, "notaritmo-file-asr").start();
    }

    private void renderCurrent() {
        if (currentItem == null) return;
        titleText.setText(currentItem.title);
        timerText.setText(currentItem.durationLabel);
        statusText.setText(currentItem.status);
        summaryText.setText(currentItem.summary);

        timeline.removeAllViews();
        if (currentItem.segments.isEmpty()) {
            String emptyText = "No speech".equals(currentItem.status)
                    ? "No clear speech detected."
                    : "No transcript yet.";
            timeline.addView(label(emptyText, 14, Color.rgb(92, 101, 98), false));
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
        String meta = segment.speaker + " / " + fallback(segment.role, "SenseVoice");
        box.addView(label(meta, 13, Color.rgb(145, 100, 45), true));
        box.addView(label(
                "Emotion: " + fallback(segment.emotion, "Neutral")
                        + "   Event: " + fallback(segment.event, "Speech"),
                12,
                Color.rgb(91, 100, 97),
                false
        ));
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
        edit.setTextColor(Color.rgb(24, 32, 31));
        edit.setHintTextColor(Color.rgb(122, 132, 128));
        edit.setPadding(dp(12), dp(8), dp(12), dp(8));
        edit.setMinHeight(dp(44));
        edit.setBackground(inputBackground());
        return edit;
    }

    private void clearInputFocusAndHideKeyboard() {
        View focused = getCurrentFocus();
        if (focused != null) {
            focused.clearFocus();
            InputMethodManager imm = (InputMethodManager) getSystemService(Context.INPUT_METHOD_SERVICE);
            if (imm != null) {
                imm.hideSoftInputFromWindow(focused.getWindowToken(), 0);
            }
        }
        View root = getWindow().getDecorView();
        if (root != null) {
            root.setFocusableInTouchMode(true);
            root.requestFocus();
        }
    }

    private GradientDrawable inputBackground() {
        GradientDrawable drawable = new GradientDrawable();
        drawable.setColor(Color.rgb(250, 248, 243));
        drawable.setStroke(dp(1), Color.rgb(224, 220, 213));
        drawable.setCornerRadius(dp(8));
        return drawable;
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

    private String fallback(String value, String fallback) {
        if (value == null || value.trim().isEmpty()) return fallback;
        String trimmed = value.trim();
        return trimmed.isEmpty() ? fallback : trimmed;
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

    private String defaultHotwords() {
        return "NotaRitmo\nAndroid\nZipformer\nSenseVoice";
    }

    /** Newline-joined canonical terms for native shallow-fusion hotwords (layer ①).
     *  Strips any "=alias" suffix and comments so the glossary syntax never
     *  reaches the decoder token table. */
    private String canonicalHotwords(String raw) {
        StringBuilder out = new StringBuilder();
        for (String line : raw.split("\\R")) {
            String trimmed = line.trim();
            if (trimmed.isEmpty() || trimmed.startsWith("#")) continue;
            int eq = trimmed.indexOf('=');
            String canonical = (eq < 0) ? trimmed : trimmed.substring(0, eq).trim();
            if (canonical.isEmpty()) continue;
            if (out.length() > 0) out.append('\n');
            out.append(canonical);
        }
        return out.toString();
    }

    private String getPrefs(String key, String fallback) {
        return getSharedPreferences("notaritmo", MODE_PRIVATE).getString(key, fallback);
    }

    private void savePrefs(String key, String value) {
        getSharedPreferences("notaritmo", MODE_PRIVATE).edit().putString(key, value).apply();
    }
}
