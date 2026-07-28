# ① 媒体接入 Media Intake

## 一句话定位

只负责把外部输入转换为安全、稳定、可重复处理的媒体资产。

它完全不知道转写、摘要、Memory、RAG和用户问答。

## 输入

- MP3。
- MP4。
- WAV。
- M4A、AAC、FLAC、OGG等可评估格式。
- HTTP / HTTPS URL。
- YouTube或其他公开视频链接。
- 客户端上传文件。
- 将来的Android录音。
- 对象存储中已经存在的文件。
- 实时录音结束后形成的媒体对象。

## 输出：MediaAsset

```json
{
  "media_id": "media_xxx",
  "tenant_id": "tenant_xxx",
  "schema_version": "media-asset-v1",
  "source_type": "upload",
  "raw_uri": "object://tenant/raw/meeting.m4a",
  "audio_uri": "object://tenant/normalized/meeting.wav",
  "sha256": "...",
  "duration_ms": 3600000,
  "format": "wav",
  "codec": "pcm_s16le",
  "sample_rate": 16000,
  "channels": 1,
  "quality": {
    "score": 82,
    "snr_db": 18.5,
    "clipping": false,
    "speech_ratio": 0.71
  },
  "processing_version": "media-intake-v1"
}
```

## 完整功能点

### 输入与上传

- 创建上传会话。
- 预签名直传对象存储。
- 分片上传和断点续传。
- 上传完成确认。
- 文件大小和哈希二次校验。
- URL下载。
- URL重定向限制。
- YouTube等平台导入适配器。
- Android录音上传适配。
- 批量导入。
- 重复请求幂等处理。

### 安全验证

- 文件扩展名验证。
- MIME类型验证。
- 魔数和真实容器格式验证。
- 最大文件大小限制。
- 最大音视频时长限制。
- 协议白名单。
- 禁止访问本机、内网、云元数据地址。
- 下载超时、重定向次数和响应大小限制。
- 恶意文件和压缩炸弹防护。
- tenant对象路径隔离。

### 媒体探测

- 使用ffprobe检查是否可解码。
- 提取容器、编码、采样率、声道和位深。
- 读取音视频时长。
- 检测无音轨视频。
- 检测损坏、截断和异常时间基。
- 检测多音轨和多声道。
- 记录原始媒体元数据。

### 规范化

- 使用FFmpeg抽取音轨。
- 转换为统一PCM格式。
- 重采样。
- 单声道转换。
- 按策略选择声道。
- 保留原始文件。
- 保存规范化处理版本。
- 可选音量归一化。
- 可选降噪。
- 可选响度标准化。
- 可选长音频切片，但输出仍保持统一时间轴。

### 音频质量

- VAD。
- 语音和静音占比。
- RMS和响度。
- SNR估计。
- 削波比例。
- DC Offset。
- 过低音量。
- 长时间静音。
- 编码损伤和异常噪声。
- 多声道差异。
- 0–100质量评分。
- 阻断、警告、通过三级质量结果。

### 存储与生命周期

- 原始对象存储。
- 规范化对象存储。
- tenant前缀隔离。
- 服务端加密。
- 临时文件清理。
- 保留期策略。
- 删除传播。
- 对象引用计数。
- 短期访问地址。
- 存储成本记录。

### 幂等与审计

- SHA-256重复检测。
- 同一输入和同一处理版本复用结果。
- 不同处理版本产生新派生资产。
- 保存每一步开始、结束、错误和耗时。
- 保存来源、操作主体和请求ID。
- 失败后可以从安全阶段重试。

## 数据所有权

本模块权威拥有：

- 原始来源描述、上传会话和导入任务。
- 原始媒体与规范化媒体的对象引用、内容哈希和媒体版本。
- 容器、编码、时长、采样率、声道、音轨等技术元数据。
- 输入安全校验、转码步骤、媒体质量报告和删除状态。
- 对象存储中的生命周期策略与派生媒体血缘。

本模块不拥有会议标题、参与人、逐字稿、Speaker、摘要、项目事实或查询索引。产品侧提供
的会议名称和项目归属只作为关联标识，不改变 `MediaAsset` 的职责。

## 命令、查询与事件

命令：

```text
CreateUploadSession
CompleteUpload
ImportRemoteMedia
ProbeMedia
NormalizeMedia
DeleteMedia
```

查询：

```text
GetMedia
GetMediaQuality
GetUploadStatus
IssueMediaPlayback
```

事件：

```text
MediaAccepted
MediaRejected
MediaReady
MediaQualityWarningRaised
MediaDeleted
```

`MediaReady` 只在安全验证、探测、规范化、存储提交和质量报告全部落盘后发布；重复消费同一
事件不能产生第二份逻辑资产。

## 状态机

```text
REGISTERED
  -> UPLOADING
  -> VALIDATING
  -> PROBING
  -> NORMALIZING
  -> READY
```

任一处理状态可以进入 `FAILED`；用户取消进入 `CANCELLED`；删除使用
`DELETION_PENDING -> DELETED`。`QUALITY_WARNING` 是附加标记，不应冒充失败状态。

## 依赖规则

- 只依赖对象存储、下载器、媒体工具和质量分析 Provider。
- 可以接收产品模块建立的租户、用户和关联资源上下文。
- 只向下游提供稳定 URI 和短期访问能力，不泄露存储凭据或供应商字段。
- 不监听 Transcript、Artifact、Memory 或查询事件。
- 不因某个 ASR 的私有格式改变规范化媒体合同。

## 错误分类

- 输入不合法、协议不允许、文件超限和媒体损坏：不可重试。
- 远程来源临时超时、对象存储短暂失败：可退避重试。
- 远程地址永久失效、鉴权失败、格式不支持：等待用户更换输入。
- 转码器配置、存储凭据和地域错误：配置错误，不自动重试。
- 音质差、静音过多或削波：质量警告或质量门禁，不伪装为基础设施错误。

## 实时与离线边界

- 当前权威输出是完整的离线 `MediaAsset`。
- 实时模式可产生带序号和校验和的 `MediaChunk`，但只有 Finalize 后才能形成最终媒体版本。
- 本模块的 VAD 只用于语音占比、静音检测、质量预检和可选粗切片。
- ASR 解码切分、重叠语音、Speaker 边界和语义分段所需的 VAD 属于转写模块。
- 对多声道或多音轨只做检测、保留和规范化；选择如何用于说话人还原由转写模块决定。

## 可插拔点

```text
MediaImporter
  - Upload
  - Remote URL
  - YouTube
  - Android Recording

ObjectStorageProvider
  - MinIO
  - S3
  - OSS
  - 其他兼容对象存储

AudioNormalizer
  - FFmpeg
  - 其他媒体处理引擎

AudioQualityAnalyzer
  - 规则算法
  - 学习型质量模型

DenoiseProvider
  - Disabled
  - Local
  - External API
```

## 明确边界

- 不调用ASR。
- 不处理说话人。
- 不生成Transcript。
- 不生成摘要、章节和待办。
- 不写Memory。
- 不建立向量索引。
- 不回答用户问题。
- 不把存储供应商字段暴露给下游。
- 不把质量预检 VAD 当作最终 ASR 或 Speaker 分段。

## 研究重点

- 不同会议录音格式兼容性。
- 超长媒体的流式处理。
- 手机录音、会议室远场和网络录音质量差异。
- 降噪对ASR字准率和说话人分离的正负影响。
- 单声道转换是否损失远程会议的声道信息。
- 对象存储直传的安全和跨地域性能。
- 媒体去重能节省多少存储和转写费用。

## 评测指标

- 格式接入成功率。
- 损坏文件提前拦截率。
- 重复文件识别准确率。
- 转码成功率。
- 转码速度倍数。
- 峰值内存。
- 质量评分与下游ASR错误率的相关性。
- 每音频小时CPU、存储和处理成本。
- 删除传播完整率。

## 完成标准

- 固定`MediaAsset v1`。
- 覆盖所有目标格式的黄金样本。
- 损坏和恶意输入在进入ASR前失败。
- 同文件重复提交不重复执行昂贵处理。
- 六小时媒体不会整体进入API内存。
- 所有对象带tenant、哈希、版本和生命周期。
- 任意存储Provider替换后，下游合同不变化。
