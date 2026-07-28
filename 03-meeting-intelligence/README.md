# ③ 单会议理解 Meeting Intelligence

## 一句话定位

只分析一场会议，不处理跨会议长期记忆。

它回答：

> 这一场会议讲了什么、决定了什么、谁需要做什么、有哪些风险和未解决问题。

## 输入

标准`TranscriptBundle`，以及可选会议元数据：

```json
{
  "meeting_id": "meeting_xxx",
  "transcript_version": 1,
  "title": "Android项目周会",
  "project_id": "android",
  "participants": [],
  "language": "zh-CN"
}
```

## 输出：MeetingArtifactBundle

```json
{
  "meeting_id": "meeting_xxx",
  "schema_version": "meeting-artifact-bundle-v1",
  "artifacts": [
    {
      "artifact_id": "artifact_xxx",
      "type": "decision",
      "content": "Android首版使用原生Kotlin",
      "structured_data": {
        "subject": "Android首版",
        "decision": "使用原生Kotlin"
      },
      "evidence": [
        {
          "segment_id": "seg_018",
          "start_ms": 183200,
          "end_ms": 195800
        }
      ],
      "confidence": 0.93,
      "model": "...",
      "prompt_version": "meeting-extract-v3"
    }
  ]
}
```

## 完整输出能力

### 核心语义

- 一句话摘要。
- 完整会议摘要。
- 执行摘要。
- 关键事实。
- 决策。
- 行动项。
- 风险。
- 未解决问题。
- 主题和议题。

### 会议组织

- 自动章节。
- 每章标题、摘要和时间范围。
- 议题切换点。
- 会议时间线。
- 重点内容。
- 讨论结论。
- 没有结论的讨论。
- 跑题和重复讨论候选。

### 人员维度

- 每个Speaker的发言内容。
- 发言时长和占比。
- 主要观点。
- 支持、反对和保留意见。
- 被分配的行动项。
- 提及的风险。
- 主持、汇报、决策和观察角色候选。
- 只输出证据支持的角色，不凭职位猜测。

### 行动与决策

- 行动事项。
- 负责人。
- 截止时间。
- 依赖项。
- 优先级候选。
- 完成标准候选。
- 明确决策与建议区分。
- 暂定决策。
- 被否决方案。
- 需要确认的信息。
- 信息缺失时保持`null`。

### 展示数据

- 热词。
- 关键词。
- 词频。
- 词云数据。
- 思维导图节点和边。
- 树状图。
- 主题关系。
- 决策时间线。
- Speaker统计。
- 会议质量评分。

### 质量分析

- 摘要是否覆盖主要议题。
- 决策是否有证据。
- 行动项是否缺负责人。
- 行动项是否缺截止时间。
- 是否存在相互冲突的发言。
- 是否存在大量低置信转写。
- 是否存在未结束议题。
- 模型输出Schema是否合法。

## 七类权威语义组件

优先用一次统一提取生成：

```text
summary
facts
decisions
action_items
risks
open_questions
topics
```

章节、热词、词云、思维导图、说话人统计和时间线尽量从统一结果与Transcript派生，
避免针对每个功能重复发送完整转写。

## 证据规则

- 每条事实、决策、行动项、风险和开放问题必须绑定Segment。
- 引用时间必须位于Segment和音频范围内。
- 引用文字来自Transcript，不使用模型改写文字冒充原话。
- 没有明确负责人时不得猜测负责人。
- 没有截止时间时不得生成日期。
- 推断必须标记`inferred`。
- 无有效证据的模型项不得进入正式Artifact。
- 人工修改保留原始模型结果和修改历史。

## 可插拔点

```text
MeetingExtractor
  - Qwen
  - OpenAI
  - Claude
  - 本地模型
  - 规则算法

ValidationStrategy
  - JSON Schema
  - 规则校验
  - 第二模型审查
  - 多模型交叉验证

ArtifactDeriver
  - 确定性算法
  - 模型辅助

AnalysisProfile
  - 通用会议
  - 项目周会
  - 访谈
  - 销售
  - 培训
  - 自定义
```

## 版本和成本

每次运行记录：

```text
canonical_hash
model_provider
model_name
prompt_version
schema_version
prompt_hash
input_tokens
output_tokens
estimated_cost
latency
cache_hit
```

同一Canonical、模型、Prompt和Schema可以命中缓存；任何版本变化都产生新结果，不能覆盖
历史产物。

## 明确边界

- 不修改原始Transcript。
- 不判断不同会议中的哪条决策当前有效。
- 不建立跨会议实体和Claim。
- 不回答全库用户问题。
- 不直接创建外部任务。
- 可以反复重新分析，不影响原始转写。

## 研究重点

- 一次统一提取与多Prompt提取的质量和成本差异。
- 长会议的上下文压缩与章节化策略。
- 小模型、大模型和规则算法组合。
- 证据绑定如何减少幻觉。
- 不同行业Profile是否真的提升质量。
- 多模型验证的收益是否值得成本。
- 自动摘要与人工纪要的一致性。

## 评测指标

- 摘要事实准确率。
- 摘要覆盖率。
- 决策Precision / Recall / F1。
- 行动项Precision / Recall / F1。
- 负责人和截止时间Slot Accuracy。
- 风险与开放问题F1。
- Evidence Precision。
- Evidence Coverage。
- 无证据Artifact数量，目标为零。
- 人工修订率。
- 每音频小时Token、成本和处理时间。

## 完成标准

- 固定`MeetingArtifactBundle v1`。
- 所有正式事实性Artifact带有效证据。
- 不存在的信息保持为空，不由模型补写。
- 同输入和版本可以稳定重现或命中缓存。
- 更换模型不会改变下游数据合同。
- 建立至少四场人工标注会议黄金集。
- 七类组件和所有派生产物均有独立验收。
