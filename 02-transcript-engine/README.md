# ② 转写还原 Transcript Engine

## 一句话定位

只解决一件事：

> 谁，在什么时间，说了什么。

## 实现语言与运行边界

### 语言结论

本模块采用 Go 控制层加 Python 本地模型层，不是纯 Python：

```text
Go Transcript Controller
├── TingwuTranscriptionProvider
├── FutureCloudTranscriptionProvider
├── LocalTranscriptionProvider Client
├── Provider Routing / Cache / Cost
├── Schema Validation / Normalization
└── Transcript Authority / Versioning
                  │
                  ▼
Python Local Model Service
├── ASR
├── VAD Model
├── Diarization
├── Overlap Detection
├── Speaker Embedding
├── Forced Alignment
└── Model-specific Post-processing
```

Go 负责：

- 接收 `TranscribeMedia`，验证租户、媒体版本、幂等键和处理策略。
- 根据能力、语言、地域、隐私、质量、成本和健康状态选择 Provider。
- 直接调用听悟或未来的云 ASR，并归档 Provider 原始响应引用。
- 调用 Python 本地模型服务，但不感知其框架、Checkpoint 和 GPU 实现。
- 管理任务提交、轮询、Deadline、取消、退避重试、降级和 Provider 切换。
- 记录输入哈希、Provider、模型版本、延迟、成本和质量数据。
- 把所有 Provider 结果转换为统一候选结构。
- 生成稳定的 Speaker、Segment、Word ID 和最终版本。
- 校验时间范围、文本非空、区间顺序、词与 Segment 归属及媒体版本。
- 发布权威 `TranscriptBundle` 和 `TranscriptReady`。
- 接收经授权的文字、时间轴和 Speaker 修订，创建新 Transcript 版本。

Python 负责：

- 本地模型加载、预热、批处理、显存管理和推理。
- ASR、VAD、Diarization、Overlap Detection、Speaker Embedding 和 Forced Alignment。
- 模型所需的特征提取、长度分桶、音频切片和模型特定后处理。
- 返回候选 Segment、Word、Speaker、时间戳、分数和模型诊断信息。
- 离线评测 WER/CER、DER、JER、SA-WER、时间戳偏差和 RTF。

Python 禁止：

- 创建最终产品 `meeting_id`、权威 Segment ID 或租户关系。
- 直接写入 Transcript 权威业务表。
- 自行将某次候选结果发布为正式 Transcript。
- 决定用户是否有权读取音频、声纹或转写。
- 把完整音频或逐字稿写入普通日志。
- 直接向客户端返回听悟或本地模型的原始结构。

### 两条执行路径

云端路径：

```text
MediaAsset -> Go -> Tingwu/Cloud ASR -> Go Normalize/Validate -> TranscriptBundle
```

本地路径：

```text
MediaAsset URI -> Go -> Python Model Service -> Go Normalize/Validate -> TranscriptBundle
```

无论走哪条路径，下游只能读取相同的 `TranscriptBundle`。听悟是 Go 控制层中的一个
`TranscriptionProvider`，后续模块永远不能读取听悟原始 JSON。

### 通信与部署

- Go 与 Python 使用版本化 gRPC / Protobuf 或等价内部合同。
- 音频通过受限 MinIO URI 传递，不通过 RPC 搬运长音频字节。
- Go Temporal Worker 拥有耐久任务状态；Python 是可取消、可健康检查的模型服务。
- Python 按模型和 GPU 扩容，不按租户启动独立模型。
- 多租户请求可以共享模型副本和 Batch，但缓存键、日志、结果和对象路径必须隔离。
- 扩容指标使用待处理音频分钟数、RTF、GPU 利用率、显存、Batch 等待和处理 P95/P99。

## 多语言、方言与可训练 ASR 战略

### 听悟公开语言边界

以下矩阵基于 2026-07-29 可查到的听悟官方指南、API Schema 和发布记录。它描述的是公开承诺，
不是对每种口音、噪声和会议环境准确率的保证：

| 听悟模式 | 公开语言范围 | 约束 | 本项目状态 |
|---|---|---|---|
| 已知单语种 | 中文 `cn`、英文 `en`、粤语 `yue`、日语 `ja`、韩语 `ko` | 实时指南中中文支持 8K/16K，其余四种只支持 16K | 可建立正式验收 |
| 离线自动单语种 `auto` | 当前离线指南列中、英、日、粤、韩 | 仅离线、仅 16K；一个文件选择一个单语模型 | 可建立正式验收 |
| 多语混说 `multilingual` | 中、英、粤、日、韩、德、法、俄 | 仅 16K；使用 `LanguageHints` 限定语言集合 | 可建立正式验收 |
| 中英自由说 `fspk` | 中文与英文 Code-switch | 仍出现在较旧 CreateTask Schema | 兼容配置，不作为新默认 |
| 离线泰语 | 2024-09/10 发布记录声明新增单语及 auto 泰语 | 当前离线指南的 auto 范围仍未列泰语 | 必须真实 API 验收后才能标记支持 |
| 听悟 `fun-asr` | 设置 `Transcription.Model=fun-asr` 且 `SourceLanguage=multilingual` | 2025-09 发布；听悟文档未完整枚举其语言和方言清单 | 独立实验 Profile，不能自动继承宣传范围 |

官方来源：

- [听悟离线语种选择、auto 与 multilingual](https://help.aliyun.com/zh/tingwu/offline-transcribe-of-audio-and-video-files/)
- [听悟实时语种选择与 LanguageHints](https://help.aliyun.com/zh/tingwu/interface-and-implementation)
- [听悟 CreateTask API Schema](https://help.aliyun.com/zh/tingwu/api-tingwu-2023-09-30-createtask)
- [听悟发布记录：泰语、multilingual 与 fun-asr](https://help.aliyun.com/zh/tingwu/release-notes)

这些官方页面存在版本不同步：CreateTask Schema 仍主要列 `cn/en/fspk/ja/yue`，当前指南已经
列出 `ko/auto/multilingual`，发布记录又声明泰语和 `fun-asr`。因此不能只依赖静态枚举判断
产品能力，必须同时记录文档来源、真实任务是否接受、输出语言和黄金集质量。

### 方言边界

听悟默认接口明确列出的中文非普通话语种只有粤语。当前听悟指南没有完整承诺吴语、闽南语、
客家话、赣语、湘语、晋语、四川话、河南话等方言的默认识别范围。

阿里云百炼的 Fun-ASR 产品文档单独声明其主版本支持普通话、粤语、吴语、闽南语、客家话、
赣语、湘语、晋语，以及中原、西南、冀鲁、江淮、兰银、胶辽、东北、北京、港台等地区口音，
并支持多种外语；但这不能直接证明听悟包装的 `fun-asr` Profile 在任务参数、说话人分离、
词级时间戳和全部方言上具有完全相同的能力。必须分别验收：

- 听悟是否接受该语言/方言参数。
- 返回文本是否保留原语言而非错误映射到普通话。
- Word 时间戳、Speaker 和标点是否仍然完整。
- CER/WER、方言字词准确率和 SA-WER 是否达到门槛。
- 听悟摘要等下游能力是否支持该转写语言；不能用“ASR 可识别”推导“所有听悟功能可用”。

参考：[百炼 Fun-ASR 语言与方言范围](https://help.aliyun.com/zh/model-studio/asr-model/)。

### 能力注册表

Go 控制层维护版本化 `LanguageCapabilityRegistry`，不在代码中散落语言判断：

```json
{
  "provider": "tingwu",
  "provider_model": "fun-asr",
  "mode": "offline",
  "language": "de",
  "dialect": null,
  "mixed_language": true,
  "sample_rates": [16000],
  "word_timing": "verified",
  "diarization": "verified",
  "hotword": "unsupported",
  "fine_tuning": "unsupported",
  "acceptance_status": "experimental",
  "last_verified_at": "2026-07-29",
  "evidence_run_ids": ["run_xxx"],
  "source_documents": ["tingwu-release-notes-2025-09"]
}
```

`acceptance_status` 只能是：

```text
documented
api_accepted
quality_verified
experimental
unsupported
regressed
```

只有 `quality_verified` 可以成为指定语言、方言和场景的生产默认。文档宣传、HTTP 任务创建成功、
返回了非空文本，都不能单独等同于质量通过。

### Provider 路由

```text
语言/方言已知
  ├── Tingwu Profile 已 quality_verified
  │      └── TingwuProvider
  ├── Tingwu fun-asr Profile 仅 documented/api_accepted
  │      └── Shadow 或用户明确允许的实验流量
  ├── Local ASR 已 quality_verified
  │      └── LocalMultilingualASRProvider
  ├── 其他云 Provider 已 quality_verified
  │      └── FutureCloudTranscriptionProvider
  └── 无合格 Provider
         └── LANGUAGE_UNSUPPORTED，拒绝伪造转写
```

语言未知时先执行受控语言识别或短片段探测，再选择 Provider。不能把不支持的语言强制作为中文、
英文或 `multilingual` 提交后接受乱码式结果。翻译和 LLM 也不能恢复 ASR 已经丢失的原始内容。

### 为什么必须建设自己的 ASR 服务

听悟适合作为商业基线和已覆盖场景的生产 Provider，但它不能保证：

- 所有目标语言和方言均可识别。
- 每种语言都有热词、领域词典和相同的 Speaker/时间戳能力。
- 用户可以上传训练数据并微调听悟模型。
- 固定录音卡、房间、口音和行业术语能够专门适配。
- 模型升级不会导致某个语言或方言回归。
- 数据必须留在本地时仍可使用。

听悟公开 API 没有用户自助 ASR 训练接口。百炼当前 Fun-ASR 模型页同样将“模型调优”标记为
不支持。因此，为了产品可承诺的语言、方言、隐私和可训练能力，本模块必须提供自己的
`LocalMultilingualASRProvider`，但不要求第一天替换听悟，也不要求从零预训练模型。

```text
Python Local ASR Service
├── Multilingual Base Model
├── Language / Dialect Router
├── Adapter Registry
│   ├── Language Adapter
│   ├── Dialect / Accent Adapter
│   ├── Domain Adapter
│   └── Device / Acoustic Adapter
├── Context / Hotword Biasing
├── Inference and Dynamic Batching
├── Model Version and Rollback
└── Offline Evaluation
```

基础模型、Adapter 和训练工具都必须满足目标商业许可证。只开放推理权重但没有训练 Recipe 的
模型不能被文档标记为“可微调方案”；推理效果好与可训练、可复现是两项独立验收。

### 微调不是每种语言复制一个完整模型

默认策略是共享多语言基础模型，再根据真实数据选择：

```text
多语言基础模型
├── 不微调：语言提示 + 上下文 + 热词
├── 语言 Adapter：基础语言长期不足
├── 方言/口音 Adapter：目标方言持续错误
├── 领域 Adapter：人名、产品、型号和专业术语
└── 声学 Adapter：固定录音卡、房间、远场和噪声条件
```

只有在 Adapter 无法达到目标、语言之间存在明显负迁移、算力允许并且数据足够时，才评估独立
完整模型。不能因为产品支持十种语言，就预先维护十份完整权重。

微调启动条件：

1. Tingwu、未微调本地模型、热词和上下文方法已经在同一黄金集完成基线。
2. 错误能够归因于目标语言、方言、领域或声学条件，而不是标注错误和 Speaker 错配。
3. 已经具有合法、经过人工校验的音频与逐字稿。
4. 训练、开发和最终测试按会议与 Speaker 隔离，避免同一人泄漏。
5. 明确主要指标、非目标语言回归门槛、资源预算和回滚模型。
6. 训练框架、基础权重和数据许可证允许商业训练与部署。

### 微调数据合同

```json
{
  "sample_id": "sample_xxx",
  "tenant_id": "tenant_xxx",
  "audio_uri": "object://training/audio.wav",
  "audio_hash": "sha256:...",
  "start_ms": 0,
  "end_ms": 18240,
  "language": "zh",
  "dialect": "zh-southwestern-mandarin",
  "transcript_raw": "我们先看一下这个版本",
  "transcript_normalized": "我们先看一下这个版本",
  "speaker_id": "gold_speaker_01",
  "device_profile": "recorder_card_v1",
  "acoustic_tags": ["far_field", "meeting_room", "air_conditioner"],
  "domain_tags": ["software", "android"],
  "annotation_status": "double_checked",
  "consent_scope": "model_training",
  "split": "train"
}
```

训练数据必须区分产品使用授权与模型训练授权。删除请求需要传播到原始音频、切片、Manifest、
训练缓存和后续可识别的训练版本；声纹数据不能因参加 ASR 训练而默认获得额外授权。

### 多语言与方言验收

每个语言/方言单独报告，不允许只使用总体平均分：

- 每语言 CER/WER 和置信区间。
- 方言内 CER/WER、普通话错误映射率和专有词准确率。
- Code-switch 边界准确率和语言混入率。
- 每语言 DER、SA-WER、Speaker 数量误差和时间戳误差。
- 近场、远场、噪声、重叠和固定录音卡分桶。
- 未微调基础模型、热词、Adapter、完整微调和听悟的成对比较。
- 非目标语言回归、灾难性遗忘和语言路由错误率。
- RTF、GPU 显存、吞吐、启动时间和每音频小时成本。

ASR 微调只改善文字识别，不自动改善 Diarization、Overlap Detection、声纹或 Forced Alignment。
这些子能力继续按各自黄金标注和指标独立替换。

## 输入

标准`MediaAsset`：

```json
{
  "media_id": "media_xxx",
  "audio_uri": "object://tenant/normalized/meeting.wav",
  "duration_ms": 3600000,
  "sample_rate": 16000,
  "channels": 1
}
```

为了独立调试下游，也允许导入已经符合Schema的标准转写。

## 输出：TranscriptBundle

```json
{
  "meeting_id": "meeting_xxx",
  "schema_version": "transcript-bundle-v1",
  "media_id": "media_xxx",
  "language": "zh-CN",
  "language_profile": {
    "requested_mode": "single",
    "detected_languages": ["zh-CN"],
    "dialect": null,
    "provider_capability_version": "tingwu-default-2026-07-29"
  },
  "speakers": [
    {
      "speaker_id": "speaker_01",
      "person_id": null,
      "identity_status": "anonymous"
    }
  ],
  "segments": [
    {
      "segment_id": "seg_001",
      "speaker_id": "speaker_01",
      "start_ms": 10200,
      "end_ms": 15600,
      "text": "我们决定先完成 Android 上传。",
      "language": "zh-CN",
      "dialect": null,
      "confidence": 0.94,
      "words": []
    }
  ],
  "quality": {
    "word_timing_available": true,
    "diarization_available": true,
    "low_confidence_ratio": 0.04
  },
  "canonical_hash": "..."
}
```

## 完整功能点

### ASR

- 离线文件转写。
- 将来的实时流式转写。
- 听悟已验收语言的单语、自动语种和多语混说。
- 自建 ASR 扩展听悟未覆盖或未通过质量验收的语言、方言和口音。
- 多语言基础模型、语言/方言/领域/声学 Adapter 和版本化微调。
- Segment 级语言、方言候选和 Code-switch 边界。
- 标点恢复。
- 数字、日期、金额和单位规范化。
- 专有名词和英文缩写识别。
- 热词和领域词典。
- 会前上下文注入。
- 低置信文本标记。
- Provider任务提交、查询、取消和恢复。
- Provider原始结果归档。
- 转写结果版本管理。

### 时间还原

- Segment起止时间。
- Word起止时间。
- 句子切分。
- 长句重分段。
- 断句与说话人边界协调。
- 时间戳漂移检查。
- Segment不得超出媒体时长。
- Word必须落在合理Segment范围。
- 长音频切片后统一回全局时间轴。

### 说话人分离

- 估计说话人数。
- 匿名Speaker聚类。
- 同一人的跨片段一致性。
- 短插话处理。
- 重叠语音检测。
- 多声道辅助分离。
- 同一人被拆成多个Speaker的候选合并。
- 不同人被错误合并的人工拆分。
- DER、JER和SA-WER评测。

### 声纹和真人身份

- 声纹注册。
- 从高质量片段提取Embedding。
- 跨会议Speaker候选匹配。
- 同租户和同模型版本比较。
- Top-K候选。
- 用户确认和拒绝。
- Person与Speaker绑定。
- 模型升级后的重新匹配。
- 声纹删除和Speaker解绑。
- 声纹不作为身份认证。
- 绝不把匿名Speaker自动当成真人。

### 文本后处理

- 人名、公司名、产品名和型号纠错。
- 同音词纠错。
- 数字、金额和日期专项校验。
- 英文大小写与缩写规范化。
- 口头语是否保留的策略。
- 原始文本和修订文本并存。
- 人工编辑历史。
- 修改后的Canonical新版本。

### 质量与错误

- ASR整体置信度。
- 低置信Segment列表。
- 无语音和过短语音。
- 说话人数量异常。
- 时间戳缺失。
- Provider结果不完整。
- 语言不匹配。
- 语言或方言不支持。
- Provider 文档支持但真实质量未通过。
- 多语言路由错误和语言混入。
- 可重试与不可重试错误分类。

## 数据所有权

本模块权威拥有：

- ASR 原始运行记录和规范化逐字稿版本。
- Segment、Word、标点、语言、置信度和全局媒体时间轴。
- 匿名 Speaker 聚类、重叠语音标记和每段 Speaker 归属。
- 声纹特征版本、候选匹配和已确认的 `speaker_id -> person_id` 映射引用。
- Transcript 人工修订、合并、拆分、重新对齐和版本血缘。

真实人员主档、成员权限和确认操作由产品模块拥有；本模块负责生成候选并把经过授权确认的
映射应用到新 Transcript 版本。匿名声纹永远不能自动升级为真实身份。

## 命令、查询与事件

命令：

```text
TranscribeMedia
ReprocessTranscript
AlignTranscript
SubmitTranscriptCorrection
ConfirmSpeakerIdentity
DeleteVoiceprint
```

查询：

```text
GetTranscript
GetTranscriptVersion
GetTranscriptSegments
GetSpeakerCandidates
GetTranscriptionQuality
```

事件：

```text
TranscriptionStarted
TranscriptPartialUpdated
TranscriptReady
TranscriptQualityWarningRaised
TranscriptCorrected
SpeakerIdentityCandidateRaised
SpeakerIdentityConfirmed
```

`TranscriptReady` 必须指向不可变 Transcript 版本；任何文字、边界、时间戳或 Speaker
修订都创建新版本，并显式触发下游产物失效和重算。

## 状态机

```text
QUEUED
  -> PREPARING
  -> TRANSCRIBING
  -> ALIGNING
  -> DIARIZING
  -> NORMALIZING
  -> VALIDATING
  -> READY
```

某 Provider 只支持部分能力时可以进入 `PARTIAL`，并列出缺失的词级时间戳、说话人分离或
置信度。低质量不是成功的同义词，必须附带 `QualityReport`。

## 依赖规则

- 只消费 `MediaAsset` 或受控导入的标准 Transcript Fixture。
- ASR、对齐、Diarization、Overlap Detection、Speaker Embedding 都通过 Provider 接口。
- 下游只能读取规范化 Transcript，不能解析听悟或其他 Provider 原始 JSON。
- 可以读取经授权的术语、人名读音和声纹注册信息，但不能读取产品模块的私有用户表。
- 不调用单会理解、Memory、向量库、图数据库或回答模型。

## 错误分类

- 媒体引用不存在、时间轴越界、导入 Schema 不合法：不可重试。
- Provider 限流、临时网络失败和异步任务暂时不可用：可重试或切换 Provider。
- 密钥、地域、模型名、配额策略错误：配置错误，不盲目重试。
- 无语音、语言不支持、音质不足：业务质量错误或人工检查。
- Provider 返回完成但片段缺失、时间戳重叠失真：合同校验失败，不能发布 Ready。

## 实时与离线边界

- 实时 `TranscriptDelta` 可以修订，使用稳定流序号和临时 Segment ID。
- Finalize 后执行全局对齐、Speaker 重聚类、标点和热词纠错，生成最终 Segment ID。
- 会中临时 Speaker 不保证与会后 Speaker 编号一致；客户端必须通过映射事件更新。
- 只有最终 Transcript 默认触发正式单会议理解和跨会议记忆。
- 本模块负责转写语义所需的 VAD、ASR 切片、Speaker Change 和 Overlap Detection。

## 可插拔点

```text
TranscriptionProvider
  - TingwuTranscriptionProvider
  - LocalQwenASRProvider
  - 其他云ASR

DiarizationProvider
  - ASR内置
  - 独立本地模型
  - 多声道方案

VoiceprintProvider
  - CAM++
  - 其他Speaker Embedding
  - Disabled

TranscriptPostProcessor
  - 规则
  - 语言模型辅助
  - 人工词典

HotwordProvider
  - 手工词表
  - 项目资料自动生成
```

## Provider统一接口

```text
submit(MediaAsset, Options) -> ProviderTask
wait(ProviderTask) -> ProviderResult
normalize(ProviderResult) -> TranscriptBundle
cancel(ProviderTask) -> ProviderTaskStatus
```

## 重要边界

- Tingwu只是这一块的一个Provider。
- Tingwu未通过验收的语言和方言不能因任务创建成功而标记为产品支持。
- 听悟 `fun-asr` 和百炼直调 Fun-ASR 是两个独立 Provider Profile，不能共享未经验证的能力结论。
- 听悟和云端 Fun-ASR 不开放用户微调时，自建可训练 ASR 承担定制语言、方言和声学适配。
- Tingwu原始JSON不能进入下游模块。
- 本地ASR与云ASR必须产生同一个`TranscriptBundle`。
- 这一块不生成摘要、章节、决策和待办。
- 这一块不建立跨会议Memory。
- Speaker编号不是自然人身份。
- 没有词级时间戳时必须明确缺失，不能伪造。
- 不把匿名 Speaker 或高相似度声纹候选自动当成真实人员。

## 首个重点研究模块结论

当前最值得先建立真实评测基线的是本模块，原因不是它编号靠前，而是：

- Transcript 是后续证据、摘要、Claim、检索和音频跳转的共同来源。
- 漏字、错字、Speaker 错配和时间戳漂移会被下游成倍放大。
- ASR、Diarization、对齐和声纹方案差异大，技术不确定性高。
- AliMeeting、AISHELL-4 等公开中文会议数据同时提供音频、转写和 Speaker 标注，可以立即
  独立评测，不需要等待其他模块实现。
- Tingwu 可以作为商业端到端基线，本地 Provider 可以逐个替换，正好适合控制变量实验。

这不是提前认定 Tingwu 或某个本地模型最好，而是先建立一套能持续回答“哪个方案在哪类
会议上更好、快多少、贵多少、为什么失败”的实验系统。

## 模块内部的五个独立子实验

```text
E1 语音识别：音频 -> 文字
E2 强制对齐：音频 + 固定文字 -> 词或字时间戳
E3 匿名说话人分离：音频 -> Speaker 时间区间
E4 结果融合：固定文字时间戳 + 固定 Speaker 区间 -> Speaker Attribution
E5 真人候选匹配：单 Speaker 高质量片段 -> Person Top-K 候选
```

五个子实验分别评价。只有单项结论稳定后才比较完整组合，禁止第一次实验就同时更换 ASR、
VAD、对齐、Diarization、降噪、热词和后处理。

## 首轮方案池

方案池分为“基线、首选候选、对照候选、研究候选”，不把尚未运行真实数据的模型写成默认方案。

### 商业端到端基线

| 方案 | 首轮角色 | 使用能力 | 需要验证 |
|---|---|---|---|
| Tingwu 默认模型 | 商业基线 `C0` | ASR、Speaker、段落、Word 时间戳、热词 | 每语言 CER、DER、时间误差、长音频稳定性、成本、数据边界 |
| Tingwu `fun-asr` | 扩展云端基线 `C1` | `Model=fun-asr`、`SourceLanguage=multilingual` | 语言/方言真实范围、Speaker/时间戳完整性、与百炼直调能力差异 |

官方文档表明 Tingwu 转写可以开启说话人分离、设置人数或不定人数、关联热词词表，并返回
`SpeakerId` 及 Word 起止毫秒时间。它适合做统一商业基线，但官方字段存在不等于真实会议
质量已经通过，仍必须使用同一黄金数据实测。

### 本地 ASR 与对齐

| 方案 | 首轮角色 | 优点 | 限制与风险 |
|---|---|---|---|
| Qwen3-ASR-1.7B | 本地 ASR 首选候选 `A1` | 中文、中英混合、方言、离线与流式、Apache-2.0 | 必须实测会议 CER、长音频切片和 GPU 峰值 |
| Qwen3-ForcedAligner-0.6B | 本地对齐首选候选 `T1` | 中文字/词级时间戳，与 Qwen ASR 同工具链 | 官方说明单次对齐最长 5 分钟，必须切片并回写全局时间轴 |
| Paraformer + FSMN-VAD + CT-Punc | 速度对照 `A2` | 中文链路成熟、组件可拆、适合低资源与吞吐对照 | 语义鲁棒性、专业词和中英混合必须实测 |
| Fun-ASR-Nano | 第二轮候选 | FunASR 当前旗舰 LLM-ASR 方向 | 工具代码与模型权重许可分开，先审查权重许可和运行资源 |
| `fa-zh` | 轻量对齐对照 `T2` | 中文时间预测、组件较小 | 与 Qwen ForcedAligner 的精度必须单独标注比较 |
| 可训练多语言基础模型 | 微调候选 `AF1` | 可建立语言、方言、领域和声学 Adapter | 必须先验证训练 Recipe、权重许可证、复现性和非目标语言回归 |

Qwen3-ASR 官方同时提供 Transformers、vLLM、流式推理和独立 Forced Aligner。首轮只使用
离线推理，不把不同运行后端和不同模型同时作为一个变量。FunASR 是工具箱，不把
SenseVoice、Paraformer、Fun-ASR-Nano 和 CAM++ 混称为一个模型。

### 匿名说话人分离

| 方案 | 首轮角色 | 优点 | 限制与生产判断 |
|---|---|---|---|
| Tingwu 内置 Diarization | 商业基线 `D0` | 与其 ASR 直接集成 | 无法单独控制内部 VAD、Embedding 和聚类 |
| pyannote `community-1` | 本地首选候选 `D1` | 本地离线、支持 Speaker 数范围和重叠语音，公开中文会议基准 | 模型需接受 Hugging Face 使用条件，许可证为 CC-BY-4.0 |
| 3D-Speaker | 中文对照 `D2` | 可拆 VAD、分段、Embedding、聚类和可选重叠检测 | 参数多，必须固定 Recipe；不能把其声纹分数直接当真人身份 |
| pyannote `precision-2` | 商业质量上界 `D3` | 官方公开基准在 AliMeeting 等数据上优于 community-1 | 外部 API、成本与数据传输，需要单独授权 |
| NeMo Sortformer 4spk | 研究候选 `D4` | 端到端、直接建模多人活动和重叠 | 当前模型限制最多 4 人且为 CC-BY-NC-4.0，不能作为商业默认 |

pyannote 官方公开基准显示，模型在 AISHELL-4 和 AliMeeting 上的 DER 差异明显；这证明
Diarization 不能凭演示音频选型。NeMo 同时提供端到端 Sortformer 和可拆的级联方案，但
首轮只把 Sortformer 放在 2–4 人研究切片中，不纳入可商用默认候选。

### 真人候选匹配

| 方案 | 首轮角色 | 评测用途 |
|---|---|---|
| CAM++ | 轻量基线 `V0` | 中文 Speaker Embedding、Top-K、EER/minDCF |
| ERes2NetV2 | 中文首选候选 `V1` | 与 CAM++ 使用同一注册片段和测试片段比较 |
| WeSpeaker 模型 | 独立工具链对照 `V2` | 验证 Embedding、校准和跨设备泛化 |

真人候选匹配晚于匿名 Diarization 评价，但可以使用人工切好的单 Speaker 片段独立并行测试。
声纹只输出候选和分数；任何 Provider 都不能绕过用户确认。

## 第一批评测数据

### 公开黄金数据

| 数据集 | 用途 | 首批范围 | 关键覆盖 |
|---|---|---|---|
| AliMeeting | 中文会议主基线 | Eval 全集，再扩 Test | 2–4 人、远场/近场、重叠、15–30 分钟会议 |
| AISHELL-4 | 复杂多人压力集 | Test 分层子集，再扩全集 | 4–8 人、远场、快速轮换、噪声和重叠 |

两个数据集均来自 OpenSLR，许可证为 CC BY-SA 4.0。AliMeeting 总计约 118.75 小时并提供
远场、近场和高质量转写；AISHELL-4 总计约 120 小时、211 场、每场 4–8 人并提供转写与
Speaker 活动标注。首轮不需要下载全部训练集，先用 Eval/Test 建立可重复基线。

### 私有真实产品数据

公开数据不能代替实际录音。必须逐步建立经授权的私有评测集，至少分层覆盖：

- 手机近讲、桌面远场、会议室麦克风和网络会议录音。
- 1 人、2 人、3–4 人、5 人以上。
- 普通话、中英混合、口音和目标方言。
- 听悟明确支持语言、文档冲突语言、目标扩展语言和明确不支持语言。
- 单语、多语混说、Code-switch、相近语言混入和未知语种路由。
- 安静、中度噪声、强噪声、回声、视频播放声和重叠语音。
- 10 分钟以内、10–60 分钟、1 小时以上。
- 人名、公司名、产品名、型号、金额、日期和英文缩写。

首批只需标注高信息密度片段，不必先标完整长会议：

```text
30 分钟 Smoke 集
  -> 4 小时 Baseline 集
  -> 20 小时 Representative 集
  -> 持续收集 Failure Regression 集
```

每次发现真实失败，就把该片段脱敏、授权、标注后加入只增不删的回归集。

## 黄金标注格式

每个音频样本至少记录：

```json
{
  "sample_id": "ali_eval_xxx",
  "audio_uri": "fixture://audio/ali_eval_xxx.wav",
  "duration_ms": 1200000,
  "language_slices": ["zh-CN"],
  "speaker_count": 3,
  "reference_transcript": "fixture://reference/ali_eval_xxx.stm",
  "reference_rttm": "fixture://reference/ali_eval_xxx.rttm",
  "reference_words": "fixture://reference/ali_eval_xxx.ctm",
  "slices": ["far_field", "overlap_medium", "speaker_3"],
  "license": "CC-BY-SA-4.0",
  "split": "test"
}
```

要求：

- 文本保留原始版本和统一 Normalization 版本。
- Speaker 标注使用 RTTM 或可无损转换格式。
- 时间戳黄金集只需覆盖人工精标子集，但必须包含短插话和重叠区间。
- 调参集与最终测试集严格分开；最终测试集不能用于阈值搜索。
- 私有样本记录授权、脱敏、保留期和禁止外发标记。

## 控制变量实验矩阵

| 实验 | 固定项 | 唯一主要变量 | 输出指标 |
|---|---|---|---|
| E1-ASR-Intrinsic | Oracle 语音区间、同一文本规范化 | ASR 模型 | CER/WER、数字/实体准确率、RTF、资源 |
| E1-ASR-Longform | 同一规范化音频、同一切片策略 | ASR 模型 | 长会议 CER、漏段率、重复率、稳定性 |
| E2-Alignment | 人工正确文本、同一音频片段 | Aligner | 起止 MAE/P95、覆盖率、越界率 |
| E3-Diarization | 同一 16k 单声道音频、同一 Speaker 提示 | Diarization Provider | DER、JER、Overlap F1、人数准确率 |
| E4-Attribution | 固定 Word 时间戳、固定 Speaker 区间 | 融合算法 | 词 Speaker 准确率、cpCER/tcpCER |
| E5-Voiceprint | 固定注册/查询片段与租户候选库 | Embedding/校准模型 | Top-K、EER、minDCF、误接受 |
| E6-End-to-End | 同一原始音频和合同 | 完整组合 | CER、DER、tcpCER、证据可播放率、成本 |

重要规则：

- 比较 ASR 时不得同时切换 VAD、热词、降噪和后处理。
- 比较 Diarization 时不使用 ASR 文字参与判定，除非单独定义“语义辅助”实验。
- 比较 Aligner 时使用人工正确文本，避免把 ASR 错字算成对齐错误。
- 比较后处理时同时报告 Raw CER 和 Normalized CER，禁止用文本改写隐藏识别错误。
- DER 必须固定是否包含重叠语音、是否使用 collar；不同口径不得放在同一排行榜。
- 中文会议使用字符级 CER；MeetEval 输入字符 Token 后报告 cpCER/tcpCER，并记录转换版本。
- 每次运行保存数据哈希、代码、模型、权重许可、参数、硬件、延迟、显存、Token 和 API 成本。

## 首轮完整组合

只跑三个有明确作用的组合，不做全部候选的笛卡尔积：

```text
C0 商业基线
Tingwu ASR + Tingwu Word Time + Tingwu Diarization

L1 本地质量候选
Qwen3-ASR-1.7B + Qwen3-ForcedAligner-0.6B
  + pyannote community-1
  + 确定性 Word/Speaker 区间融合

L2 本地效率对照
Paraformer + FSMN-VAD + fa-zh + 3D-Speaker/CAM++
  + 确定性 Word/Speaker 区间融合
```

首轮统一关闭：

- 降噪。
- 自动热词。
- LLM 纠错。
- 跨会议声纹自动匹配。
- 多模型投票。

这些能力分别在基线建立后作为单一变量加入。否则即使 L1 胜出，也无法解释提升来自哪一项。

## 候选升级门槛

不预先拍脑袋写一个绝对 CER 或 DER 即宣布完成。先运行 `C0`、`L1`、`L2` 建立基线，再冻结
各场景门槛。任何候选成为默认方案前必须满足：

- `TranscriptBundle` Schema、时间范围和证据引用校验 100% 通过。
- 主指标在最终测试集不劣于当前默认，目标场景有实际可感知提升。
- 不以普通场景平均分掩盖重叠、多人、专业词或长会议关键切片退化。
- 结果可重复，失败可定位，可恢复错误与不可恢复错误分类正确。
- 记录每音频小时延迟、GPU/CPU/内存峰值、API 成本和存储成本。
- 权重和数据许可证允许目标用途。
- 私有音频外发、声纹保存和删除路径符合租户与隐私策略。
- 完整组合升级后，下游证据 ID 和播放时间点回归通过。

## 官方研究依据

- [Tingwu 语音转写、说话人分离、热词和返回结构](https://help.aliyun.com/zh/tingwu/voice-transcription/)
- [Tingwu 离线语言、auto、multilingual 与 LanguageHints](https://help.aliyun.com/zh/tingwu/offline-transcribe-of-audio-and-video-files/)
- [Tingwu 实时语言与多语混说](https://help.aliyun.com/zh/tingwu/interface-and-implementation)
- [Tingwu CreateTask API Schema](https://help.aliyun.com/zh/tingwu/api-tingwu-2023-09-30-createtask)
- [Tingwu 发布记录：泰语、multilingual 与 fun-asr](https://help.aliyun.com/zh/tingwu/release-notes)
- [百炼 Fun-ASR 支持语言、方言与模型调优边界](https://help.aliyun.com/zh/model-studio/asr-model/)
- [Qwen3-ASR 与 Forced Aligner](https://github.com/QwenLM/Qwen3-ASR)
- [FunASR](https://github.com/modelscope/FunASR)
- [pyannote.audio](https://github.com/pyannote/pyannote-audio)
- [pyannote community-1 模型卡与公开基准](https://huggingface.co/pyannote/speaker-diarization-community-1)
- [3D-Speaker](https://github.com/modelscope/3D-Speaker)
- [WeSpeaker](https://github.com/wenet-e2e/wespeaker)
- [NVIDIA NeMo Speaker Diarization](https://docs.nvidia.com/nemo-framework/user-guide/latest/nemotoolkit/asr/speaker_diarization/intro.html)
- [MeetEval 会议转写评测](https://github.com/fgnt/meeteval)
- [pyannote.metrics](https://github.com/pyannote/pyannote-metrics)
- [AliMeeting](https://www.openslr.org/119/)
- [AISHELL-4](https://www.openslr.org/111/)

## 研究重点

- 商业基线与本地组合在真实中文会议上的质量、延迟、成本和隐私取舍。
- 听悟默认、听悟 `fun-asr`、百炼直调和自建 ASR 的语言/方言能力差异。
- 多语言基础模型、Adapter 与完整微调在目标语言上的收益及非目标语言回归。
- 复杂多人、远场、短插话、快速轮换和重叠语音。
- Word 时间戳与 Speaker 区间融合对最终 Speaker Attribution 的影响。
- 热词、降噪和文本后处理作为独立变量的真实收益与副作用。
- 声纹跨设备、房间、时间和语言的稳定性及校准。

## 评测指标

- CER / WER。
- DER / JER。
- SA-WER。
- Word时间戳误差。
- Speaker数量误差。
- 实体准确率。
- 低置信Segment召回率。
- 声纹Top-K Recall。
- 声纹误接受率和误拒绝率。
- 实时率RTF。
- 每音频小时成本。
- Provider失败和恢复成功率。
- 每语言/方言 CER/WER、Code-switch 边界准确率和语言混入率。
- 语言路由准确率、未知语言拒绝率和不支持语言误接受率。
- 微调目标语言提升、非目标语言回归和模型回滚成功率。

## 完成标准

- 固定`TranscriptBundle v1`。
- 下游只依赖Canonical，不包含任何Provider字段。
- 冻结音频 Sample Manifest、文本 Normalization、RTTM/CTM 转换和数据切分版本。
- `C0`、`L1`、`L2` 在同一 AliMeeting、AISHELL-4 和私有真实黄金集完成评测。
- 语言能力注册表固定版本，所有生产语言均有 `quality_verified` 证据运行。
- 至少一个听悟未覆盖或未达标的目标语言/方言完成本地基线；是否微调由误差分析决定。
- 任何微调版本都有数据 Manifest、基础权重、训练配置、评测报告、许可证和可回滚模型。
- E1–E5 可以分别替换一个 Provider 并独立运行，不需要启动完整会议产品。
- 真实多人录音完成 Raw/Normalized CER、DER、JER、cpCER/tcpCER 和时间误差基线。
- 所有Segment和Word时间合法。
- 每次运行保存质量、错误切片、RTF、CPU、内存、显存、API成本和许可证信息。
- 未运行最终测试集前，任何候选都不得在文档中标记为默认最优方案。
- 声纹候选必须经用户确认。
- 导入标准转写可以完全跳过ASR调试后续模块。
