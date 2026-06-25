package com.example.notaritmo.engine;

public interface ModelDownloadListener {
    void onProgress(String fileName, int percent, long downloadedBytes, long totalBytes);

    void onComplete(String modelPath);

    void onError(String message);
}
