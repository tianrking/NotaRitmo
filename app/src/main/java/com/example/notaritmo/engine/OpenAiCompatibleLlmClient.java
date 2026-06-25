package com.example.notaritmo.engine;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;

public class OpenAiCompatibleLlmClient {
    private static final String DEFAULT_OPENAI_BASE = "https://api.deepseek.com";
    private static final String DEFAULT_OPENAI_MODEL = "deepseek-chat";
    private static final String ANTHROPIC_VERSION = "2023-06-01";

    /** Summarize finalized local ASR text into meeting notes. */
    public String summarize(String apiBase, String apiKey, String model, String transcript) throws Exception {
        return chat(
                apiBase,
                apiKey,
                model,
                "You are a meeting-notes assistant. Summarize all provided ASR content after correction. "
                        + "Do not invent facts. Write concise Chinese Markdown with overall summary, key decisions, next steps, risks, and quoted evidence.",
                "Please summarize the complete corrected local ASR transcript:\n\n" + transcript,
                1800
        );
    }

    /**
     * LLM post-correction. This is intentionally stronger than pure glossary
     * normalization: the model may fix obvious ASR errors, homophones, broken
     * technical terms, punctuation, and mixed Chinese/English product names,
     * while preserving the speaker's meaning and order.
     */
    public String correct(String apiBase, String apiKey, String model, String transcript, String glossary) throws Exception {
        return correct(apiBase, apiKey, model, transcript, glossary, "");
    }

    public String correct(String apiBase, String apiKey, String model, String transcript, String glossary, String correctionContext) throws Exception {
        String glossaryBlock = (glossary == null || glossary.trim().isEmpty())
                ? "(none)"
                : glossary.trim();
        String contextBlock = (correctionContext == null || correctionContext.trim().isEmpty())
                ? "(none)"
                : correctionContext.trim();
        return chat(
                apiBase,
                apiKey,
                model,
                "You are an expert ASR transcript correction engine for Mandarin/English mixed technical speech. "
                        + "You must use the full session context before deciding each line correction. "
                        + "First infer the domain, topic, likely glossary, product names, and repeated concepts from all context. "
                        + "Then correct the numbered transcript lines. Correct obvious speech-recognition mistakes: homophones, "
                        + "wrong Chinese words, broken English product names, malformed technical terms, punctuation, and spacing. "
                        + "Use the glossary and local/LLM keywords as high-priority hints, but also infer corrections from surrounding lines, "
                        + "speaker labels, timestamps, emotion/event tags, and repeated terms. "
                        + "If a word is plausible in general but implausible in this session context, correct it to the contextually likely word. "
                        + "Preserve speaker meaning, language, tone, line order, and line count. Do not summarize. Do not add new facts. "
                        + "Return ONLY JSON with this exact shape: "
                        + "[{\"index\":1,\"text\":\"corrected line\"},{\"index\":2,\"text\":\"corrected line\"}]. "
                        + "Include every input line, even if unchanged. No Markdown, no explanation.",
                "Glossary / canonical terms:\n" + glossaryBlock
                        + "\n\nFull session context. Use all of it to disambiguate likely ASR mistakes:\n" + contextBlock
                        + "\n\nExamples of allowed ASR correction:\n"
                        + "notar rhythm -> NotaRitmo\n"
                        + "sense voice / sens voice -> SenseVoice\n"
                        + "zip former -> Zipformer\n"
                        + "fun as are -> FunASR\n"
                        + "sports-team-like homophones -> hotwords, when the session context is ASR keywords/glossary\n"
                        + "life separation -> speaker diarization, when the session context is ASR speaker labels\n"
                        + "key works / keyworsk -> keywords\n"
                        + "\nNow correct these numbered lines. Return JSON only:\n\n" + transcript,
                3200
        );
    }

    /** Extract post-session keywords from finalized ASR text. */
    public List<String> keywords(String apiBase, String apiKey, String model, String transcript, List<String> localKeywords) throws Exception {
        String localBlock = localKeywords == null || localKeywords.isEmpty()
                ? "(none)"
                : String.join(", ", localKeywords);
        String raw = chat(
                apiBase,
                apiKey,
                model,
                "You extract summary hotwords from finalized meeting text. Use semantic word segmentation over the summary and transcript. "
                        + "Prefer domain terms, product names, user-intent nouns, tasks, model names, and corrected ASR terms. "
                        + "Return only a JSON array of strings. Do not invent facts. Keep Chinese keywords in Chinese, "
                        + "preserve product names, merge duplicates, max 12 items.",
                "Local algorithm keyword candidates:\n" + localBlock
                        + "\n\nTranscript:\n" + transcript
                        + "\n\nReturn only JSON, for example: [\"NotaRitmo\",\"SenseVoice\"]",
                800
        );
        return parseKeywords(raw, 12);
    }

    private String chat(String apiBase, String apiKey, String model, String systemPrompt, String userPrompt, int maxTokens) throws Exception {
        String base = clean(apiBase, DEFAULT_OPENAI_BASE);
        String cleanModel = clean(model, DEFAULT_OPENAI_MODEL);
        if (isAnthropicBase(base)) {
            return anthropicMessages(base, apiKey, cleanModel, systemPrompt, userPrompt, maxTokens);
        }
        return openAiChatCompletions(base, apiKey, cleanModel, systemPrompt, userPrompt, maxTokens);
    }

    static boolean isAnthropicBase(String apiBase) {
        return apiBase != null && apiBase.toLowerCase(Locale.US).contains("anthropic");
    }

    private String openAiChatCompletions(String base, String apiKey, String model, String systemPrompt, String userPrompt, int maxTokens) throws Exception {
        URL url = new URL(base.replaceAll("/+$", "") + "/chat/completions");

        JSONObject body = new JSONObject();
        body.put("model", model);
        body.put("temperature", 0.1);
        body.put("max_tokens", maxTokens);

        JSONArray messages = new JSONArray();
        messages.put(new JSONObject().put("role", "system").put("content", systemPrompt));
        messages.put(new JSONObject().put("role", "user").put("content", userPrompt));
        body.put("messages", messages);

        HttpURLConnection conn = (HttpURLConnection) url.openConnection();
        conn.setRequestMethod("POST");
        conn.setConnectTimeout(20000);
        conn.setReadTimeout(120000);
        conn.setDoOutput(true);
        conn.setRequestProperty("Content-Type", "application/json; charset=utf-8");
        conn.setRequestProperty("Authorization", "Bearer " + apiKey);

        byte[] bytes = body.toString().getBytes(StandardCharsets.UTF_8);
        try (OutputStream out = conn.getOutputStream()) {
            out.write(bytes);
        }

        int code = conn.getResponseCode();
        BufferedReader reader = new BufferedReader(new InputStreamReader(
                code < 400 ? conn.getInputStream() : conn.getErrorStream(),
                StandardCharsets.UTF_8
        ));
        StringBuilder response = new StringBuilder();
        String line;
        while ((line = reader.readLine()) != null) {
            response.append(line);
        }
        if (code >= 400) {
            throw new IllegalStateException("LLM HTTP " + code + ": " + response.substring(0, Math.min(300, response.length())));
        }
        JSONObject json = new JSONObject(response.toString());
        return json.getJSONArray("choices")
                .getJSONObject(0)
                .getJSONObject("message")
                .getString("content");
    }

    private String anthropicMessages(String base, String apiKey, String model, String systemPrompt, String userPrompt, int maxTokens) throws Exception {
        URL url = new URL(anthropicMessagesUrl(base));

        JSONObject body = new JSONObject();
        body.put("model", model);
        body.put("temperature", 0.1);
        body.put("max_tokens", maxTokens);
        body.put("system", systemPrompt);
        body.put("messages", new JSONArray()
                .put(new JSONObject()
                        .put("role", "user")
                        .put("content", userPrompt)));

        HttpURLConnection conn = (HttpURLConnection) url.openConnection();
        conn.setRequestMethod("POST");
        conn.setConnectTimeout(20000);
        conn.setReadTimeout(120000);
        conn.setDoOutput(true);
        conn.setRequestProperty("Content-Type", "application/json; charset=utf-8");
        conn.setRequestProperty("anthropic-version", ANTHROPIC_VERSION);
        conn.setRequestProperty("x-api-key", apiKey);
        conn.setRequestProperty("Authorization", "Bearer " + apiKey);

        byte[] bytes = body.toString().getBytes(StandardCharsets.UTF_8);
        try (OutputStream out = conn.getOutputStream()) {
            out.write(bytes);
        }

        int code = conn.getResponseCode();
        BufferedReader reader = new BufferedReader(new InputStreamReader(
                code < 400 ? conn.getInputStream() : conn.getErrorStream(),
                StandardCharsets.UTF_8
        ));
        StringBuilder response = new StringBuilder();
        String line;
        while ((line = reader.readLine()) != null) {
            response.append(line);
        }
        if (code >= 400) {
            throw new IllegalStateException("LLM HTTP " + code + ": " + response.substring(0, Math.min(300, response.length())));
        }
        JSONArray content = new JSONObject(response.toString()).getJSONArray("content");
        StringBuilder text = new StringBuilder();
        for (int i = 0; i < content.length(); i++) {
            JSONObject item = content.getJSONObject(i);
            if ("text".equals(item.optString("type")) && item.has("text")) {
                if (text.length() > 0) text.append('\n');
                text.append(item.getString("text"));
            }
        }
        return text.toString();
    }

    static String anthropicMessagesUrl(String base) {
        String cleanBase = base.replaceAll("/+$", "");
        if (cleanBase.endsWith("/v1")) {
            return cleanBase + "/messages";
        }
        if (cleanBase.endsWith("/messages")) {
            return cleanBase;
        }
        return cleanBase + "/v1/messages";
    }

    public static Map<Integer, String> parseCorrectedLines(String raw) {
        Map<Integer, String> out = new LinkedHashMap<>();
        if (raw == null || raw.trim().isEmpty()) return out;

        String cleaned = stripMarkdownFence(raw.trim());
        try {
            Object root = parseJsonRoot(cleaned);
            JSONArray array = null;
            if (root instanceof JSONArray) {
                array = (JSONArray) root;
            } else if (root instanceof JSONObject) {
                JSONObject object = (JSONObject) root;
                array = object.optJSONArray("corrections");
                if (array == null) array = object.optJSONArray("lines");
                if (array == null) array = object.optJSONArray("items");
            }
            if (array != null) {
                for (int i = 0; i < array.length(); i++) {
                    Object item = array.opt(i);
                    if (item instanceof JSONObject) {
                        JSONObject object = (JSONObject) item;
                        int oneBased = object.optInt("index", object.optInt("line", i + 1));
                        String text = firstNonEmpty(
                                object.optString("text", ""),
                                object.optString("corrected", ""),
                                object.optString("corrected_text", ""),
                                object.optString("correctedText", "")
                        );
                        addCorrection(out, oneBased - 1, text);
                    } else {
                        addCorrection(out, i, String.valueOf(item));
                    }
                }
                if (!out.isEmpty()) return out;
            }
        } catch (Exception ignored) {
        }
        parseObjectCorrections(cleaned, out);
        if (!out.isEmpty()) return out;

        for (String line : cleaned.split("\\R")) {
            String trimmed = line.trim();
            if (trimmed.isEmpty()) continue;
            int dot = trimmed.indexOf('.');
            int colon = trimmed.indexOf(':');
            int separator = dot > 0 ? dot : colon;
            if (separator <= 0) continue;
            try {
                int idx = Integer.parseInt(trimmed.substring(0, separator).trim()) - 1;
                addCorrection(out, idx, trimmed.substring(separator + 1));
            } catch (NumberFormatException ignored) {
            }
        }
        return out;
    }

    private static void parseObjectCorrections(String cleaned, Map<Integer, String> out) {
        java.util.regex.Matcher matcher = java.util.regex.Pattern
                .compile("\\{([^{}]+)\\}")
                .matcher(cleaned);
        int ordinal = 0;
        while (matcher.find()) {
            String body = matcher.group(1);
            int oneBased = extractIntField(body, "index");
            if (oneBased <= 0) oneBased = extractIntField(body, "line");
            if (oneBased <= 0) oneBased = ordinal + 1;
            String text = firstNonEmpty(
                    extractStringField(body, "text"),
                    extractStringField(body, "corrected"),
                    extractStringField(body, "corrected_text"),
                    extractStringField(body, "correctedText")
            );
            addCorrection(out, oneBased - 1, text);
            ordinal++;
        }
    }

    private static int extractIntField(String body, String key) {
        java.util.regex.Matcher matcher = java.util.regex.Pattern
                .compile("\"" + java.util.regex.Pattern.quote(key) + "\"\\s*:\\s*(\\d+)")
                .matcher(body);
        if (!matcher.find()) return -1;
        try {
            return Integer.parseInt(matcher.group(1));
        } catch (NumberFormatException ignored) {
            return -1;
        }
    }

    private static String extractStringField(String body, String key) {
        java.util.regex.Matcher matcher = java.util.regex.Pattern
                .compile("\"" + java.util.regex.Pattern.quote(key) + "\"\\s*:\\s*\"((?:\\\\.|[^\"\\\\])*)\"")
                .matcher(body);
        if (!matcher.find()) return "";
        return unescapeJsonString(matcher.group(1));
    }

    private static String unescapeJsonString(String value) {
        return value
                .replace("\\n", "\n")
                .replace("\\r", "\r")
                .replace("\\t", "\t")
                .replace("\\\"", "\"")
                .replace("\\\\", "\\");
    }

    public static List<String> parseKeywords(String raw, int maxKeywords) {
        Set<String> seen = new LinkedHashSet<>();
        List<String> out = new ArrayList<>();
        if (raw == null || maxKeywords <= 0) return out;

        String cleaned = stripMarkdownFence(raw.trim());
        int start = cleaned.indexOf('[');
        int end = cleaned.lastIndexOf(']');
        if (start >= 0 && end > start) {
            try {
                JSONArray array = new JSONArray(cleaned.substring(start, end + 1));
                for (int i = 0; i < array.length(); i++) {
                    addKeyword(out, seen, array.optString(i, ""), maxKeywords);
                }
                if (!out.isEmpty()) return out;
            } catch (Exception ignored) {
            }
        }

        for (String piece : cleaned.split("[,，;；\\n]")) {
            addKeyword(out, seen, piece, maxKeywords);
        }
        return out;
    }

    private static Object parseJsonRoot(String cleaned) throws Exception {
        int arrayStart = cleaned.indexOf('[');
        int arrayEnd = cleaned.lastIndexOf(']');
        int objectStart = cleaned.indexOf('{');
        int objectEnd = cleaned.lastIndexOf('}');
        if (objectStart >= 0 && objectEnd > objectStart && (arrayStart < 0 || objectStart < arrayStart)) {
            return new JSONObject(cleaned.substring(objectStart, objectEnd + 1));
        }
        if (arrayStart >= 0 && arrayEnd > arrayStart) {
            return new JSONArray(cleaned.substring(arrayStart, arrayEnd + 1));
        }
        throw new IllegalArgumentException("No JSON root");
    }

    private static String stripMarkdownFence(String text) {
        if (!text.startsWith("```")) return text;
        String[] lines = text.split("\\R");
        StringBuilder builder = new StringBuilder();
        for (String line : lines) {
            String trimmed = line.trim();
            if (trimmed.startsWith("```")) continue;
            if (builder.length() > 0) builder.append('\n');
            builder.append(line);
        }
        return builder.toString().trim();
    }

    private static String firstNonEmpty(String... values) {
        for (String value : values) {
            if (value != null && !value.trim().isEmpty()) return value;
        }
        return "";
    }

    private static void addCorrection(Map<Integer, String> out, int zeroBasedIndex, String raw) {
        String text = raw == null ? "" : raw.trim();
        if (zeroBasedIndex < 0 || text.isEmpty()) return;
        out.put(zeroBasedIndex, text);
    }

    private static void addKeyword(List<String> out, Set<String> seen, String raw, int maxKeywords) {
        if (out.size() >= maxKeywords) return;
        String keyword = raw == null ? "" : raw.trim()
                .replaceAll("^[\\-\\*#\\d\\.\\)\\s]+", "")
                .replaceAll("[\"'`\\[\\]{}]+", "")
                .replaceAll("\\s+", " ")
                .trim();
        while (keyword.endsWith(".") || keyword.endsWith(",") || keyword.endsWith(";")
                || keyword.endsWith("。") || keyword.endsWith("，") || keyword.endsWith("；")) {
            keyword = keyword.substring(0, keyword.length() - 1).trim();
        }
        if (keyword.length() < 2 || keyword.length() > 32 || keyword.matches("\\d+")) return;
        String key = keyword.toLowerCase(Locale.US);
        if (seen.add(key)) {
            out.add(keyword);
        }
    }

    private static String clean(String value, String fallback) {
        return value == null || value.trim().isEmpty() ? fallback : value.trim();
    }
}
