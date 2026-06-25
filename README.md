<div align="center">

# 🎙️ NotaRitmo

### 本地优先的 Android 语音实验室 · On-Device Voice Pipeline

*A local-first meeting & dictation voice lab — audio never leaves the device for ASR.*

<img src="https://img.shields.io/badge/Platform-Android_8.0%2B-3DDC84?style=for-the-badge&logo=android&logoColor=white" alt="Android">
<img src="https://img.shields.io/badge/Min_SDK-26_(API_26)-3DDC84?style=for-the-badge&logo=android&logoColor=white" alt="Min SDK">
<img src="https://img.shields.io/badge/Target_SDK-36-34A853?style=for-the-badge&logo=googleandroid&logoColor=white" alt="Target SDK">
<br>
<img src="https://img.shields.io/badge/Kotlin-2.2.21-7F52FF?style=for-the-badge&logo=kotlin&logoColor=white" alt="Kotlin">
<img src="https://img.shields.io/badge/Java-11-F89820?style=for-the-badge&logo=openjdk&logoColor=white" alt="Java">
<img src="https://img.shields.io/badge/Gradle-AGP_9.2-02303A?style=for-the-badge&logo=gradle&logoColor=white" alt="Gradle">
<br>
<img src="https://img.shields.io/badge/Inference-ONNX_Runtime-00A4EF?style=for-the-badge&logo=onnx&logoColor=white" alt="ONNX Runtime">
<img src="https://img.shields.io/badge/Speech-Sherpa--ONNX-FF6B35?style=for-the-badge&logo=googletagmanager&logoColor=white" alt="sherpa-onnx">
<img src="https://img.shields.io/badge/UI-Material_3-00897B?style=for-the-badge&logo=materialdesign&logoColor=white" alt="Material">
<br>
<img src="https://img.shields.io/badge/Privacy-Raw_audio_stays_local-2E7D32?style=for-the-badge&logo=protonmail&logoColor=white" alt="Privacy">
<img src="https://img.shields.io/badge/LLM-Optional_(SaaS)-FFA000?style=for-the-badge&logo=openai&logoColor=white" alt="LLM">
<img src="https://img.shields.io/badge/Status-Active_Development-1E88E5?style=for-the-badge&logo=git&logoColor=white" alt="Status">

</div>

---

## 📖 项目简介

**NotaRitmo** 是一个 **本地优先 (local-first)** 的 Android 语音处理应用，专为**会议记录、听写与转写**设计。
它通过 **sherpa-onnx + ONNX Runtime** 在设备端完成**全部语音识别链路**——从麦克风采集、实时流式 ASR、到停录后的精细化转写、说话人分离、标点恢复与声纹匹配。

> 🔒 **核心理念：原始音频默认不出设备。** 只有最终转写文本（可选）才会发送给外部 LLM 做摘要/纠错，音频本身永不外传。

### ✨ 核心能力

| 能力 | 说明 |
|------|------|
| 🎤 **实时流式 ASR** | 麦克风采集 16kHz 单声道 PCM，本地 Zipformer 实时出字，边说边显示 |
| 🧠 **双层转写** | 实时 Zipformer 保证低延迟；停录后 SenseVoice 对完整音频重新解码，提升最终准确率 |
| 🗣️ **说话人分离** | 本地 pyannote 分段 + 3D-Speaker 声纹嵌入，多人会议自动区分说话人 |
| 😊 **情绪 / 事件 / 语种标签** | SenseVoice 为每段输出语种、情绪与音频事件标签 |
| ✍️ **标点恢复** | 离线 CT-Transformer 模型补全逗号、句号等标点 |
| 🔉 **静音切除 (VAD)** | Silero VAD 在精修前切分语音段、剔除静音 |
| 🧬 **声纹注册与匹配** | 本地余弦相似度匹配已注册说话人，身份对齐 |
| 📂 **音频导入转写** | 通过系统选择器导入文件，本地 `MediaCodec` 解码后走同一套精修流水线 |
| 🗂️ **本地音频库** | 自动扫描录音与导入音频，支持再次转写、单条删除与一键清空 |
| 🏷️ **关键词 / 热词** | 本地领域词抽取 + 纠错高亮词 + LLM 总结热词分层展示 |
| ☁️ **可选 LLM 摘要/纠错** | 对接 OpenAI-compatible 或 Anthropic-compatible 文本端点，仅传入最终文本；先纠错，再总结与提取热词 |

---

## 🧰 技术栈 · Tech Stack

<div align="center">

<table>
<tr>
<td align="center" width="50%">

**🏗️ 平台 & 语言**

![Android](https://img.shields.io/badge/Android-3DDC84?logo=android&logoColor=white)
![Kotlin](https://img.shields.io/badge/Kotlin-7F52FF?logo=kotlin&logoColor=white)
![Java](https://img.shields.io/badge/Java_11-F89820?logo=openjdk&logoColor=white)
![Gradle](https://img.shields.io/badge/Gradle-02303A?logo=gradle&logoColor=white)
![Version Catalog](https://img.shields.io/badge/Version_Catalog-TOML-6A4C93?logo=pre-commit&logoColor=white)

</td>
<td align="center" width="50%">

**🧠 端侧 AI / 语音**

![Sherpa-ONNX](https://img.shields.io/badge/Sherpa--ONNX-FF6B35?logo=googletagmanager&logoColor=white)
![ONNX Runtime](https://img.shields.io/badge/ONNX_Runtime-00A4EF?logo=onnx&logoColor=white)
![Zipformer](https://img.shields.io/badge/Zipformer-2196F3?logo=streamlit&logoColor=white)
![SenseVoice](https://img.shields.io/badge/SenseVoice-E91E63?logo=alibaba&logoColor=white)
![Silero VAD](https://img.shields.io/badge/Silero_VAD-9C27B0?logo=v&logoColor=white)
![Pyannote](https://img.shields.io/badge/Pyannote_3.0-7E57C2?logo=pytorch&logoColor=white)
![3D-Speaker](https://img.shields.io/badge/3D--Speaker_eres2net-00897B?logo=three.js&logoColor=white)

</td>
</tr>
<tr>
<td align="center" width="50%">

**🎨 UI & AndroidX**

![Material 3](https://img.shields.io/badge/Material_3-00897B?logo=materialdesign&logoColor=white)
![AppCompat](https://img.shields.io/badge/AppCompat_1.7.1-073042?logo=google&logoColor=white)
![Core KTX](https://img.shields.io/badge/Core--KTX_1.16-039BE5?logo=google&logoColor=white)
![MediaCodec](https://img.shields.io/badge/MediaCodec-decode-FF6F00?logo=google&logoColor=white)

</td>
<td align="center" width="50%">

**🛠️ 构建 / 测试 / 模型分发**

![AGP](https://img.shields.io/badge/AGP_9.2.1-02303A?logo=android&logoColor=white)
![JUnit4](https://img.shields.io/badge/JUnit_4.13.2-25A162?logo=junit5&logoColor=white)
![Espresso](https://img.shields.io/badge/Espresso_3.7-3DDC84?logo=espresso&logoColor=white)
![Hugging Face](https://img.shields.io/badge/Model_DL-HuggingFace-FFD21E?logo=huggingface&logoColor=black)
![hf-mirror](https://img.shields.io/badge/Mirror-hf--mirror.com-FF9800?logo=fastly&logoColor=white)

</td>
</tr>
</table>

</div>

> 💡 UI 采用**纯代码编程式构建**（`MaterialCardView` + `LinearLayout`），无 XML 布局，保证运行时灵活渲染时间线卡片。

---

## 🏛️ 系统架构

### 分层架构总览

```mermaid
graph TB
    classDef ui fill:#E3F2FD,stroke:#1976D2,stroke-width:2px,color:#0D47A1
    classDef session fill:#F3E5F5,stroke:#7B1FA2,stroke-width:2px,color:#4A148C
    classDef engine fill:#FFF3E0,stroke:#E65100,stroke-width:2px,color:#BF360C
    classDef audio fill:#E8F5E9,stroke:#2E7D32,stroke-width:2px,color:#1B5E20
    classDef data fill:#FCE4EC,stroke:#C2185B,stroke-width:2px,color:#880E4F
    classDef native fill:#263238,stroke:#000,stroke-width:2px,color:#fff

    subgraph UI["📱 表现层 · UI Layer"]
        MA["MainActivity<br/>权限 · 视图 · 渲染<br/>(无算法代码)"]
    end

    subgraph SESS["🎯 编排层 · Session"]
        VSC["VoiceSessionController<br/>会话生命周期<br/>引擎回调 → 时间线状态"]
    end

    subgraph ENG["⚙️ 引擎层 · Engine"]
        RT["SherpaRealtimeAsrEngine<br/>流式 Zipformer"]
        REF["SherpaSenseVoiceRefiner<br/>离线精修"]
        DIA["SherpaSpeakerDiarizer<br/>说话人分离"]
        VAD["SherpaVadSegmenter<br/>静音切分"]
        VP["SherpaVoiceprintExtractor<br/>声纹嵌入"]
        PUNC["SherpaPunctuationRestorer<br/>标点恢复"]
        OAT["OfflineAudioTranscriber<br/>文件转写"]
        KW["KeywordExtractor<br/>本地关键词/热词"]
        LLM["OpenAiCompatibleLlmClient<br/>纠错/摘要/热词"]
        DL["SherpaModelDownloader<br/>模型分发"]
    end

    subgraph AUD["🔊 音频层 · Audio"]
        PB["PcmSessionBuffer<br/>磁盘缓存 PCM(避免堆溢出)"]
        DEC["AndroidAudioDecoder<br/>MediaCodec → 16kHz mono"]
    end

    subgraph DAT["💾 数据层 · Data / Voiceprint"]
        RI["RecordingItem · TranscriptSegment"]
        VS["LocalVoiceprintStore<br/>本地余弦相似度匹配"]
    end

    subgraph NAT["🧩 原生层 · Native (arm64-v8a)"]
        JNI["com.k2fsa.sherpa.onnx<br/>JNI Bindings"]
        ORT["ONNX Runtime<br/>libonnxruntime.so"]
    end

    MA --> VSC
    VSC --> RT
    VSC --> REF
    RT --> REF
    RT --> PB
    REF --> DIA
    REF --> VAD
    REF --> VP
    REF --> PUNC
    OAT --> REF
    OAT --> DEC
    VSC --> RI
    REF --> RI
    RI --> KW
    KW --> LLM
    VP --> VS
    VS --> RI
    DL -.->|准备模型| ENG
    MA --> LLM

    RT --> JNI
    REF --> JNI
    DIA --> JNI
    VAD --> JNI
    VP --> JNI
    PUNC --> JNI
    JNI --> ORT

    class MA,UI ui
    class VSC,SESS session
    class RT,REF,DIA,VAD,VP,PUNC,OAT,KW,LLM,DL,ENG engine
    class PB,DEC,AUD audio
    class RI,VS,DAT data
    class JNI,ORT,NAT native
```

### 🔄 实时 ASR 运行流水线

```mermaid
flowchart LR
    classDef capture fill:#E8F5E9,stroke:#2E7D32,stroke-width:2px,color:#1B5E20
    classDef realtime fill:#E3F2FD,stroke:#1976D2,stroke-width:2px,color:#0D47A1
    classDef cache fill:#FFF8E1,stroke:#F9A825,stroke-width:2px,color:#F57F17
    classDef refine fill:#FFF3E0,stroke:#E65100,stroke-width:2px,color:#BF360C
    classDef output fill:#F3E5F5,stroke:#7B1FA2,stroke-width:2px,color:#4A148C
    classDef ui fill:#FCE4EC,stroke:#C2185B,stroke-width:2px,color:#880E4F

    MIC(["🎙️ 麦克风"]) --> AR["AudioRecord<br/>16kHz · mono · PCM-16"]
    AR -->|每 100ms 采样| STREAM["OnlineStream<br/>acceptWaveform"]

    AR -.->|同步写入| BUF[("PcmSessionBuffer<br/>磁盘缓存文件")]

    STREAM --> DEC["Zipformer<br/>encoder→decoder→joiner"]
    DEC --> EP{"端点检测<br/>Endpoint?"}
    EP -->|否 - 中间结果| PARTIAL["onPartial<br/>实时出字"]
    EP -->|是 - 最终结果| FINAL["onFinal<br/>重置流"]
    PARTIAL --> UI1["📱 实时时间线"]
    FINAL --> UI1

    UI1 -.->|用户点击 Stop| STOP(("⏹ 停录"))
    STOP --> READ["读取磁盘 PCM<br/>readFloats()"]
    BUF -.-> READ
    READ --> REFINEX["进入精修分支<br/>(见下方决策图)"]

    class MIC,AR,STREAM,DEC capture
    class EP,PARTIAL,FINAL realtime
    class BUF,READ cache
    class STOP refine
    class UI1,UI ui
```

### 🧭 精修阶段 · 分段决策与回退

> 停录后，应用按"模型可用性"自动选择最强可用路径，逐级回退。

```mermaid
flowchart TD
    classDef check fill:#ECEFF1,stroke:#546E7A,stroke-width:2px,color:#263238
    classDef branch fill:#E3F2FD,stroke:#1976D2,stroke-width:2px,color:#0D47A1
    classDef refine fill:#FFF3E0,stroke:#E65100,stroke-width:2px,color:#BF360C
    classDef tag fill:#F3E5F5,stroke:#7B1FA2,stroke-width:2px,color:#4A148C
    classDef done fill:#E8F5E9,stroke:#2E7D32,stroke-width:2px,color:#1B5E20

    PCM(["📦 捕获的完整 PCM"]) --> Q1{"声纹/分离<br/>模型就绪?"}

    Q1 -->|是| DIA["SherpaSpeakerDiarizer<br/>pyannote 分段 + 聚类"]
    Q1 -->|否| Q2{"Silero VAD<br/>就绪?"}

    Q2 -->|是| VAD["SherpaVadSegmenter<br/>切语音段 · 去静音"]
    Q2 -->|否| WHOLE["整段录音<br/>作为单一输入"]

    DIA --> LOOP["🔄 逐段循环"]
    VAD --> LOOP
    WHOLE --> LOOP

    LOOP --> SV["SenseVoice 精修<br/>model.int8.onnx"]
    SV --> TAGS["提取标签<br/>语种 · 情绪 · 事件"]
    TAGS --> VP{"声纹模型<br/>就绪?"}

    VP -->|是| EMB["3D-Speaker 嵌入<br/>→ 本地声纹匹配<br/>(阈值 0.58)"]
    VP -->|否| SKIP["跳过身份匹配"]

    EMB --> NORM["LocalTermNormalizer<br/>本地术语归一"]
    SKIP --> NORM
    NORM --> PUNC["PunctuationRestorer<br/>补全标点"]
    PUNC --> POLISH["TranscriptText<br/>清洗 & 抛光"]
    POLISH --> OUT(["✅ 最终分段时间线<br/>替换实时文本"])

    class PCM check
    class Q1,Q2,VP branch
    class DIA,VAD,WHOLE,LOOP,SV,EMB,NORM,PUNC,POLISH refine
    class TAGS tag
    class OUT done
```

### 📂 导入文件转写流水线

```mermaid
flowchart LR
    classDef pick fill:#E3F2FD,stroke:#1976D2,stroke-width:2px,color:#0D47A1
    classDef store fill:#FFF8E1,stroke:#F9A825,stroke-width:2px,color:#F57F17
    classDef decode fill:#E8F5E9,stroke:#2E7D32,stroke-width:2px,color:#1B5E20
    classDef reuse fill:#FFF3E0,stroke:#E65100,stroke-width:2px,color:#BF360C
    classDef out fill:#FCE4EC,stroke:#C2185B,stroke-width:2px,color:#880E4F

    PICK(["📁 系统文件选择器<br/>audio/* "]) --> COPY["复制到<br/>app 私有目录"]
    COPY --> CODEC["AndroidAudioDecoder<br/>MediaCodec 解码"]
    CODEC --> RESAMPLE["重采样<br/>→ 16kHz mono PCM"]
    RESAMPLE --> PIPE["OfflineAudioTranscriber<br/>复用精修流水线<br/>(分离/VAD → SenseVoice → 标点)"]
    PIPE --> TL(["📝 离线转写时间线"])

    class PICK pick
    class COPY store
    class CODEC,RESAMPLE decode
    class PIPE reuse
    class TL out
```

### 📥 模型分发与回退策略

```mermaid
flowchart TD
    classDef start fill:#ECEFF1,stroke:#546E7A,stroke-width:2px,color:#263238
    classDef local fill:#E8F5E9,stroke:#2E7D32,stroke-width:2px,color:#1B5E20
    classDef net fill:#E3F2FD,stroke:#1976D2,stroke-width:2px,color:#0D47A1
    classDef fallback fill:#FFF3E0,stroke:#E65100,stroke-width:2px,color:#BF360C
    classDef done fill:#F3E5F5,stroke:#7B1FA2,stroke-width:2px,color:#4A148C

    TAP(["👆 点击<br/>Download ASR model"]) --> ASSET{"assets 内<br/>已打包模型?"}
    ASSET -->|是| COPY["从 APK assets<br/>复制到运行目录<br/>(离线 · 不联网)"]
    ASSET -->|否| HF["优先 Hugging Face<br/>huggingface.co"]

    HF --> OK1{"下载成功?"}
    OK1 -->|否| MIRROR["回退镜像<br/>hf-mirror.com"]
    OK1 -->|是| INSTALL
    MIRROR --> OK2{"下载成功?"}
    OK2 -->|否| ERR(["❌ 提示重试"])
    OK2 -->|是| INSTALL

    COPY --> INSTALL["VoiceModelRegistry<br/>扫描校验完整性"]
    INSTALL --> READY(["✅ 模型就绪<br/>完全离线可用"])

    class TAP start
    class COPY,ASSET local
    class HF,MIRROR,OK1,OK2 net
    class ERR fallback
    class INSTALL,READY done
```

---

## 📁 项目结构 · Project Structure

```
NotaRitmo/
├── app/
│   └── src/main/
│       ├── AndroidManifest.xml          # RECORD_AUDIO + INTERNET 权限
│       ├── java/com/example/notaritmo/
│       │   ├── MainActivity.java        # 📱 表现层:纯代码构建 Material UI
│       │   │
│       │   ├── session/                 # 🎯 编排层(会话边界)
│       │   │   ├── VoiceSessionController.java
│       │   │   └── VoiceSessionListener.java
│       │   │
│       │   ├── engine/                  # ⚙️ 引擎层(全部本地算法)
│       │   │   ├── SherpaRealtimeAsrEngine.kt      # 流式 Zipformer 实时识别
│       │   │   ├── SherpaSenseVoiceRefiner.kt      # SenseVoice 离线精修
│       │   │   ├── SherpaSpeakerDiarizer.kt        # 说话人分离
│       │   │   ├── SherpaVadSegmenter.kt           # Silero VAD 切分
│       │   │   ├── SherpaVoiceprintExtractor.kt    # 声纹嵌入
│       │   │   ├── SherpaPunctuationRestorer.kt    # 标点恢复
│       │   │   ├── OfflineAudioTranscriber.kt      # 文件转写(复用流水线)
│       │   │   ├── SherpaModelDownloader.java      # 模型分发
│       │   │   ├── SherpaPackagedModelInstaller.kt # APK 内置模型安装
│       │   │   ├── OpenAiCompatibleLlmClient.java  # 可选 OpenAI/Anthropic 文本 LLM
│       │   │   ├── KeywordExtractor.kt             # 本地关键词/热词抽取
│       │   │   ├── LocalTermNormalizer.kt          # 本地术语归一
│       │   │   ├── TranscriptText.kt               # 文本清洗
│       │   │   └── SenseVoiceTags.kt               # 标签映射
│       │   │
│       │   ├── ui/                      # 🎛️ 自定义轻量 UI 控件
│       │   │   └── KeywordFlowLayout.java          # 关键词自动换行布局
│       │   │
│       │   ├── audio/                   # 🔊 音频层
│       │   │   ├── PcmSessionBuffer.kt             # 磁盘缓存 PCM(长会话)
│       │   │   └── AndroidAudioDecoder.kt          # MediaCodec 解码
│       │   │
│       │   ├── data/                    # 💾 领域数据
│       │   │   ├── RecordingItem.java
│       │   │   └── TranscriptSegment.java
│       │   │
│       │   ├── voiceprint/              # 🧬 声纹层
│       │   │   ├── LocalVoiceprintStore.kt         # 本地余弦相似度匹配
│       │   │   └── VoiceprintMatch.kt
│       │   │
│       │   └── models/                  # 📦 模型注册
│       │       ├── VoiceModelBundle.kt
│       │       ├── VoiceModelRegistry.kt
│       │       └── VoiceModelStatus.kt
│       │
│       ├── jniLibs/arm64-v8a/           # 🧩 原生库(arm64-v8a)
│       │   ├── libonnxruntime.so        # ~24.6 MB
│       │   ├── libsherpa-onnx-jni.so
│       │   ├── libsherpa-onnx-c-api.so
│       │   └── libsherpa-onnx-cxx-api.so
│       │
│       └── java/com/k2fsa/sherpa/onnx/  # 🧩 sherpa-onnx JNI 绑定
│           ├── OnlineRecognizer.kt      # 流式识别器
│           ├── OfflineRecognizer.kt     # 离线识别器
│           ├── OfflineSpeakerDiarization.kt
│           ├── Vad.kt
│           ├── OfflinePunctuation.kt
│           └── ...
│
├── gradle/libs.versions.toml            # 版本目录
├── docs/ARCHITECTURE.md                 # 架构文档
├── tools/
│   ├── download-sherpa-zipformer-zh.ps1 # 开发者模型下载脚本
│   └── download-sherpa-paraformer.ps1
└── README_NOTARITMO.md                  # 模型准备详细说明
```

---

## 🧠 端侧模型清单 · On-Device Models

全部模型均在本机推理，首次使用由应用自动下载到应用外部文件目录。

| 用途 | 模型 | 关键文件 | 作用 |
|------|------|----------|------|
| 🟦 **实时识别** | `sherpa-onnx-streaming-zipformer-zh-int8-2025-06-30` | `encoder.int8.onnx` · `decoder.onnx` · `joiner.int8.onnx` · `tokens.txt` | 流式低延迟中文出字 |
| 🟧 **离线精修** | `sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17` | `model.int8.onnx` · `tokens.txt` | 多语种精修 + 语种/情绪/事件标签 |
| 🟪 **静音检测** | `silero-vad` | `silero_vad.onnx` | 切分语音段、剔除静音 |
| 🟩 **标点恢复** | `sherpa-onnx-punct-ct-transformer-zh-en-vocab272727-2024-04-12` | `model.onnx` | 补全逗号、句号 |
| 🟥 **说话人分段** | `sherpa-onnx-pyannote-segmentation-3-0` | `model.int8.onnx` | 多人会议说话人切分 |
| 🟫 **声纹嵌入** | `3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k` | `*.onnx` | 声纹向量 + 身份匹配 |

> 模型存放路径:`/sdcard/Android/data/com.example.notaritmo/files/models/<模型名>/`

---

## 🔒 设计原则 · Reliability Rules

```mermaid
mindmap
  root((NotaRitmo<br/>设计原则))
    隐私优先
      原始音频默认不出设备
      LLM 仅接收最终文本
      声纹/录音本地存储
    关注点分离
      MainActivity 不含算法代码
      VoiceSessionController 是唯一编排边界
      引擎层持有全部 ASR 算法
    内存安全
      长会话 PCM 落盘
      不在 Java/Kotlin 堆持有长音频
    模型一致性
      新模型必须先进入下载/打包逻辑
      再被引擎引用
```

---

## 🚀 快速开始 · Getting Started

### 环境要求

- **Android Studio**(支持 AGP 9.2 / Kotlin 2.2)
- **JDK 11+**
- **真机**:`arm64-v8a` 架构,Android 8.0(API 26)及以上

### 1️⃣ 构建安装

```powershell
# 构建 debug APK
.\gradlew assembleDebug

# 安装到设备
adb install -r .\app\build\outputs\apk\debug\app-debug.apk
```

### 2️⃣ 下载模型(应用内一键)

1. 打开应用,点击 **`Download ASR model`**
2. 应用会先扫描本地模型；已存在就直接显示 `Found`，不会重复下载
3. 缺失文件会自动从 Hugging Face 下载,失败回退 `hf-mirror.com`
4. 下载完成后,**完全离线**可用 ✅

### 3️⃣ 开始使用

- **`Start live ASR`** — 实时听写,边说边出字,停录后自动精修
- **`Import audio`** — 导入本地音频文件离线转写
- **`1. Correct transcript with LLM`** — (可选)结合完整上下文、热词/术语表和本地关键词纠正 ASR 文本，红色标识修正点
- **`2. Summarize + extract hotwords`** — (可选)对纠正后的最终文本做摘要，并提取黄色总结热词
- **`Transcribe again`** — 对本地库里的录音/导入音频重新跑离线转写
- **`Delete audio` / `Clear audio`** — 删除单条音频或清空已保存音频，不影响模型文件

### 🛠️ 开发者模式:手动准备模型

```powershell
# 项目根目录运行(PowerShell)
.\tools\download-sherpa-zipformer-zh.ps1

# 或手动 adb push 到设备模型目录
adb push .\models\sherpa-onnx-streaming-zipformer-zh-int8-2025-06-30 `
  /sdcard/Android/data/com.example.notaritmo/files/models/
```

> 📦 **打包进 APK**:把模型放到 `app/src/main/assets/models/<模型名>/` 下,应用会自动复制到运行目录且不联网(生产构建建议在 Gradle 加 `noCompress += "onnx"`,代价是 APK 体积增大数百 MB)。

---

## 🗺️ 路线图 · Roadmap

- [x] 实时 Zipformer 流式 ASR
- [x] SenseVoice 离线精修 + 标签
- [x] Silero VAD 静音切除
- [x] 说话人分离 + 声纹匹配
- [x] 离线标点恢复
- [x] 音频文件导入转写
- [x] 本地音频库: 再次转写、单条删除、清空音频
- [x] 本地关键词/热词抽取 + 纠错高亮 + 总结热词
- [x] 可选 LLM 纠错
- [x] 可选 LLM 摘要 + 热词提取
- [ ] **TTS**:接入 sherpa-onnx TTS 或 Android 系统 TTS
- [ ] **声纹注册 UI**:在主资源面板暴露注册入口

---

## 📜 许可证 · License

本项目代码目前未声明开源许可证。如需使用,请联系仓库所有者 **[@tianrking](https://github.com/tianrking)**。

> 第三方组件(sherpa-onnx、ONNX Runtime、Silero VAD、SenseVoice、pyannote、3D-Speaker 等)遵循其各自的许可证。

---

<div align="center">

<sub>Built with ❤️ for on-device, privacy-respecting speech recognition.</sub>
<br>
<sub>🎙️ **NotaRitmo** — *Local-first meeting voice lab.*</sub>

</div>
