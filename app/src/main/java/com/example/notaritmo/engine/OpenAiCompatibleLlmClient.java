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
    public String summarize(String apiBase, String apiKey, String model, String transcript) throws Exception {
        String base = apiBase == null || apiBase.trim().isEmpty() ? "https://api.deepseek.com" : apiBase.trim();
        String cleanModel = model == null || model.trim().isEmpty() ? "deepseek-chat" : model.trim();
        URL url = new URL(base.replaceAll("/+$", "") + "/chat/completions");

        JSONObject body = new JSONObject();
        body.put("model", cleanModel);
        body.put("temperature", 0.2);
        body.put("max_tokens", 1800);

        JSONArray messages = new JSONArray();
        messages.put(new JSONObject()
                .put("role", "system")
                .put("content", "你是会议纪要助手。只基于转写文本总结，不编造事实。输出中文 Markdown，包含核心结论、分歧/风险、关键原文证据。"));
        messages.put(new JSONObject()
                .put("role", "user")
                .put("content", "请总结以下实时本地 ASR 转写：\n\n" + transcript));
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
