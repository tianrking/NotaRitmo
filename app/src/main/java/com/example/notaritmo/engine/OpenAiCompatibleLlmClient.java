package com.example.notaritmo.engine;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.OutputStream;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
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
                "你是会议纪要助手。只基于转写文本总结，不编造事实。输出中文 Markdown，包含核心结论、分歧/风险、关键原文证据。",
                "请总结以下实时本地 ASR 转写：\n\n" + transcript,
                1800
        );
    }

    /**
     * Layer ④: LLM post-correction. Feed the transcript plus the user domain
     * glossary (hotwords) and ask the model to rewrite only entity / proper-noun
     * / term spellings to match the glossary, preserving spoken meaning, order,
     * and tone. Runs only when the user configures an LLM endpoint; it never
     * touches raw audio. The transcript is a numbered list so callers can map
     * corrected lines back onto their segments.
     */
    public String correct(String apiBase, String apiKey, String model, String transcript, String glossary) throws Exception {
        String glossaryBlock = (glossary == null || glossary.trim().isEmpty())
                ? "(未提供领域词表，仅做通用专有名词纠错)"
                : glossary.trim();
        return chat(
                apiBase,
                apiKey,
                model,
                "你是语音转写后纠错助手。给定按行编号的转写文本和一个领域词表(热词)，"
                        + "只把实体名、专有名词、术语、产品名修正为词表中的标准写法。"
                        + "保持原意、语序和口语风格，不增删内容，不改非实体词，不要解释。"
                        + "严格逐行输出，格式与输入完全一致：每行以 \"编号. \" 开头，编号与输入一一对应。",
                "领域词表(标准写法)：\n" + glossaryBlock + "\n\n请逐行纠错以下转写(保持编号与行数)：\n\n" + transcript,
                2200
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
                "You extract concise hotword keywords from finalized ASR transcript text. "
                        + "Return only a JSON array of strings. Do not invent facts. "
                        + "Keep Chinese keywords in Chinese, preserve product names, merge duplicates, max 12 items.",
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
        return apiBase != null && apiBase.toLowerCase().contains("anthropic");
    }

    private String openAiChatCompletions(String base, String apiKey, String model, String systemPrompt, String userPrompt, int maxTokens) throws Exception {
        URL url = new URL(base.replaceAll("/+$", "") + "/chat/completions");

        JSONObject body = new JSONObject();
        body.put("model", model);
        body.put("temperature", 0.2);
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
        body.put("temperature", 0.2);
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
        String key = keyword.toLowerCase();
        if (seen.add(key)) {
            out.add(keyword);
        }
    }

    private static String clean(String value, String fallback) {
        return value == null || value.trim().isEmpty() ? fallback : value.trim();
    }
}
