package com.example.notaritmo.engine;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.OutputStream;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

public class OpenAiCompatibleLlmClient {

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

    private String chat(String apiBase, String apiKey, String model, String systemPrompt, String userPrompt, int maxTokens) throws Exception {
        String base = apiBase == null || apiBase.trim().isEmpty() ? "https://api.deepseek.com" : apiBase.trim();
        String cleanModel = model == null || model.trim().isEmpty() ? "deepseek-chat" : model.trim();
        URL url = new URL(base.replaceAll("/+$", "") + "/chat/completions");

        JSONObject body = new JSONObject();
        body.put("model", cleanModel);
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
}
