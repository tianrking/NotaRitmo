# ② 转写还原 Transcript Engine

## 一句话定位

只解决一件事：

> 谁，在什么时间，说了什么。

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
- 中文、英文和中英混合。
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
- 可重试与不可重试错误分类。

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
- Tingwu原始JSON不能进入下游模块。
- 本地ASR与云ASR必须产生同一个`TranscriptBundle`。
- 这一块不生成摘要、章节、决策和待办。
- 这一块不建立跨会议Memory。
- Speaker编号不是自然人身份。
- 没有词级时间戳时必须明确缺失，不能伪造。

## 研究重点

- Tingwu与本地Qwen ASR的CER、速度、价格和稳定性。
- 复杂多人会议的说话人分离。
- 远场、噪声和重叠语音。
- 热词对专业领域识别的提升。
- 降噪对ASR和Diarization的真实影响。
- 声纹跨设备、跨房间和跨时间稳定性。
- 云端与本地方案的隐私和资源成本。

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

## 完成标准

- 固定`TranscriptBundle v1`。
- 下游只依赖Canonical，不包含任何Provider字段。
- 至少一套云ASR和一套本地候选完成相同黄金集评测。
- 真实多人录音完成CER、DER和SA-WER基线。
- 所有Segment和Word时间合法。
- 声纹候选必须经用户确认。
- 导入标准转写可以完全跳过ASR调试后续模块。
