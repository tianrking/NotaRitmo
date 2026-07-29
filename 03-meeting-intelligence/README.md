# ③ 单会议理解 Meeting Intelligence

## 一句话定位

只分析一场会议，不处理跨会议长期记忆。

它回答：

> 这一场会议讲了什么、决定了什么、谁需要做什么、有哪些风险和未解决问题。

## 实现语言与运行边界

### 语言结论

本模块采用 Go 控制层加 Python 本地模型层，不是纯 Python：

```text
Go Intelligence Controller
├── Input Builder
├── Prompt / Schema / Model Version
├── External LLM Providers
├── Cache / Token / Cost
├── Evidence Validator
├── Quality Gate
└── Artifact Authority
                 │
                 ▼
Python Local Intelligence Service
├── Local LLM
├── NLP / Topic Model
├── Keyword / Clustering
├── Candidate Extraction
└── Model Evaluation
```

Go 负责：

- 验证 `TranscriptBundle`、会议元数据、租户权限和指定输入版本。
- 构造统一语义提取任务；短会议允许单次请求，长会议必须执行分块提取、全局归并和证据验证，
  不能把“统一语义协议”误解为“整场会议只调用一次模型”。
- 管理 Prompt、Schema、模型、规则、算法和评测版本。
- 直接调用 Qwen、OpenAI、Claude 等外部 LLM Provider。
- 调用 Python 本地 LLM/NLP 服务并管理 Deadline、取消、降级和重试。
- 通过输入哈希缓存结果，记录 Token、成本、延迟和 Provider Run。
- 对候选摘要、事实、决策、行动项、风险和七类组件执行 Schema 校验。
- 验证每个正式结论的 `EvidenceRef`、Segment、时间范围、原文和 Transcript 版本。
- 拒绝不存在的负责人、截止日期、数字、人物或引用。
- 执行质量门禁、多模型仲裁和人工复核路由。
- 发布权威 `MeetingArtifactBundle`，并保留旧版本和生产链路。

Python 负责：

- 本地 LLM 加载、量化、批处理、GPU 调度和结构化生成。
- 摘要、章节、议题、事实、决策、行动项、风险、开放问题和人员观点候选提取。
- 关键词、主题聚类、词云权重、树状图和思维导图候选数据。
- 规则、传统 NLP 与模型组合实验。
- 生成候选置信度、模型诊断和评测输出。

Python 禁止：

- 直接把生成文本写入 Artifact 权威表。
- 绕过 Go 的 Evidence 校验发布事实、决策或行动项。
- 自行决定权限、重试、成本策略和产品可见状态。
- 把“模型说得像真的”当成证据。
- 读取当前会议范围之外的数据；跨会议属于 04 和 05。
- 直接向客户端提供会议摘要或问答 API。

### 外部与本地模型路径

外部 LLM：

```text
TranscriptBundle -> Go Input Builder -> External LLM
                 -> Go Schema/Evidence/Quality Validation
                 -> MeetingArtifactBundle
```

本地模型：

```text
TranscriptBundle -> Go Input Builder -> Python Local Model
                 -> Go Schema/Evidence/Quality Validation
                 -> MeetingArtifactBundle
```

两条路径使用相同输入合同、输出 Schema、Evidence 规则和评测集。替换模型只产生新的
`producer_version`，不能改变下游合同。

### 通信与部署

- 小型结构化请求使用 gRPC / Protobuf；超长 Transcript 使用受权限保护的对象 URI 或分块输入。
- Go Temporal Worker 拥有任务状态、重试和版本；Python 不拥有工作流。
- 外部 LLM 密钥和路由策略由 Go Provider 层管理。
- Python 模型进程按 Token 队列、GPU 利用率、Token/s、首 Token 延迟和 P99 扩容。
- 同一输入、模型、Prompt、Schema 和生成参数形成完整缓存键，不能只用会议 ID 缓存。

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

输入必须声明信息覆盖范围，避免把只有音频的分析结果表述成完整会议真相：

```json
{
  "source_coverage": "audio_only",
  "available_sources": ["transcript"],
  "missing_sources": ["slides", "screen", "meeting_chat"],
  "transcript_quality": {
    "asr_confidence": 0.91,
    "speaker_confidence": 0.86,
    "timestamp_quality": "word"
  }
}
```

会议标题、参会名单和日历议程属于上下文，不自动成为会议事实证据。没有在音频中表达的PPT、
屏幕、白板和聊天内容不能由本模块补造。

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
          "transcript_version": 1,
          "speaker_id": "speaker_02",
          "start_ms": 183200,
          "end_ms": 195800,
          "quote": "那就确定第一版使用原生Kotlin。",
          "quote_hash": "...",
          "role": "supporting",
          "support_status": "entailed",
          "verifier": "provider/model/version"
        }
      ],
      "confidence": 0.93,
      "confidence_calibration_version": "meeting-artifact-calibration-v1",
      "model": "...",
      "prompt_version": "meeting-extract-v3"
    }
  ]
}
```

## 完整功能点

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

## 四层语义产物

不同产物的权威程度不同，不能把摘要、主题和证据事实放在同一层：

```text
L0 Source Evidence
  Transcript、Segment、Speaker、时间戳和原文
  由02模块拥有，03模块只引用

L1 Evidence-bound Semantic Events
  assertion、proposal、decision_event、action_event
  risk_event、issue_event、question、answer、speaker_position
  表达“会议中有人这样说或这样决定”，不是客观世界真相

L2 Canonical Meeting Artifacts
  单会议内归并后的决策、行动项、风险、问题、议题和人员观点
  是03模块的正式权威产物

L3 Derived Views
  摘要、章节、时间线、热词、词云、思维导图、树状图和统计
  可以从L1/L2与Transcript重新生成，不作为事实源
```

原有七类输出继续作为兼容视图：

```text
summary
assertions
decisions
action_items
risks
open_questions
topics
```

不再把`facts`理解为已经得到外部世界验证的客观事实；兼容字段`facts`只能表示
`meeting_assertions`，即会议中被明确陈述且有证据支持的命题。

### 决策与行动状态

决策不能只有一段生成文本，至少需要识别：

```text
PROPOSED
DISCUSSED
TENTATIVE
ACCEPTED
REJECTED
DEFERRED
REVOKED_IN_MEETING
```

行动项至少需要识别：

```text
MENTIONED
COMMITTED
ASSIGNED
CONFIRMED
CANCELLED
```

负责人、截止日期、优先级和完成标准分别记录`explicit`、`inferred`或`missing`。
推断结果默认不能进入已确认状态。跨会议的`supersedes`和当前有效性仍属于04模块。

## 长会议语义流水线

```text
TranscriptBundle
  -> 输入与质量检查
  -> 合并语义发言轮次
  -> 议题边界与Token分块
  -> 分块并行提取L1语义事件
  -> 单会议实体、指代与重复项归并
  -> 决策和行动状态解析
  -> 冲突、遗漏与一致性检查
  -> Evidence语义验证
  -> 质量门禁
  -> L2 MeetingArtifactBundle
  -> L3摘要、章节和展示数据
```

- 分块同时考虑Token上限、Speaker轮次和议题边界，不按固定分钟机械切断。
- 相邻块保留受控重叠并在全局阶段去重。
- 摘要优先从已验证L2 Artifact生成，不直接从超长原文自由发挥。
- 同一语义协议可以由多次模型请求完成；统一的是合同，不是调用次数。
- 长上下文模型仍必须参加中间位置召回测试，不能因窗口足够大就跳过分层提取。

## 证据规则

- 每条事实、决策、行动项、风险和开放问题必须绑定Segment。
- Evidence必须声明Transcript版本、原文、原文哈希、Speaker、时间范围和证据角色。
- 证据角色至少区分`supporting`、`contradicting`和`context`。
- 引用时间必须位于Segment和音频范围内。
- 引用文字来自Transcript，不使用模型改写文字冒充原话。
- 结构有效不等于语义支持；必须独立记录`entailed`、`contradicted`、`insufficient`或`unverified`。
- 没有明确负责人时不得猜测负责人。
- 没有截止时间时不得生成日期。
- 推断必须标记`inferred`。
- 无有效证据的模型项不得进入正式Artifact。
- 人工修改保留原始模型结果和修改历史。
- 模型自报置信度不能直接作为产品置信度，必须在固定人工标注集上完成校准并记录校准版本。

Evidence验证分为两层：

1. Go执行确定性的结构验证：ID、版本、时间范围、原文哈希、租户和权限。
2. 规则、NLI/LLM Verifier或人工执行语义验证：证据是否真正支持Artifact。

## Prompt注入与敏感内容

Transcript属于不可信输入。录音中出现“忽略系统规则”“修改输出格式”或类似内容时，
只能作为会议原文分析，不能成为对系统的指令。

- 系统指令、Schema和Transcript使用明确边界隔离。
- 提取模型不获得外部工具、数据库写入和跨会议读取权限。
- 输出必须通过Schema、证据和权限验证后才能发布。
- 黄金集必须包含口述Prompt注入、恶意JSON、伪造系统指令和隐私数据样本。
- 外部Provider调用前执行租户策略、脱敏策略和地域合规检查。

## 数据所有权

本模块权威拥有指定 Transcript 版本下的单会议派生产物：

- 摘要、章节、议题、事实、决策、行动项、风险、开放问题和人员观点。
- 热词、词频、词云数据、思维导图、树状图、时间线和会议质量分析。
- 每项产物的证据、置信度、审核状态、模型、Prompt、Schema、Token、成本和延迟。
- 人工修订后的 Artifact 版本与原始模型候选。

本模块不拥有逐字稿原文、真实人员主档、跨会议当前状态和对话答案。单会决策只是
“这场会议表达了什么”的权威记录，不能直接代表项目当前仍然采用该决策。

## 命令、查询与事件

命令：

```text
AnalyzeMeeting
ReanalyzeMeeting
ValidateArtifacts
SubmitArtifactCorrection
ApproveArtifact
```

查询：

```text
GetArtifacts
GetArtifactVersion
GetMeetingSummary
GetMeetingTimeline
GetArtifactEvidence
```

事件：

```text
MeetingAnalysisStarted
MeetingArtifactsReady
ArtifactQualityWarningRaised
ArtifactCorrected
ArtifactApproved
```

`MeetingArtifactsReady` 必须声明唯一输入 Transcript 版本。若 Transcript 更新，旧产物保留
审计但标记 `STALE`，不能静默继续作为 Memory 和正式答案的来源。

## 状态机

```text
QUEUED
  -> PREFLIGHT
  -> SEGMENTING
  -> EXTRACTING_EVENTS
  -> GLOBAL_RECONCILING
  -> NORMALIZING
  -> EVIDENCE_LINKING
  -> VALIDATING
  -> DERIVING_VIEWS
  -> READY
```

某类产物失败时允许 `PARTIAL`，但必须列出成功、失败和被质量门禁拦截的组件。人工修订进入
新版本；人工批准不覆盖模型原始版本。语义证据不足但值得人工确认的结果进入
`NEEDS_REVIEW`，不能伪装成`READY`正式结果。

## 依赖规则

- 只消费最终或显式允许的 `TranscriptBundle` 版本及会议级上下文。
- LLM、规则、图表生成和交叉验证通过本模块 Provider 接口。
- 所有语义产物只能引用输入 Transcript 中真实存在的 `EvidenceRef`。
- 不读取其他会议，不查询 Memory，不决定某个 Claim 当前是否有效。
- 不建立检索索引、不处理用户自然语言查询、不直接返回客户端私有格式。

## 错误分类

- Transcript 缺失、版本不存在、证据范围越界：不可重试或等待上游修正。
- LLM 限流和临时故障：可重试或按策略切换 Provider。
- 模型配置、Prompt/Schema 不兼容：配置错误，不重复消耗 Token。
- JSON 可解析但证据无效、事实冲突或组件缺失：语义校验失败。
- 音频内容不足以形成决定、负责人或日期：输出“未明确”，不能补造字段。

## 实时与离线边界

- 会中可生成 `ArtifactDelta`、滚动摘要和待办候选，但必须标记 `partial`。
- partial 产物随 Transcript Delta 变化，可以撤回，不默认进入跨会议 Memory。
- 会后基于最终 Transcript 全量重算，并验证所有证据引用。
- 实时提醒可以发现议题跑偏、责任人或日期缺失，但不能自动把候选变成正式组织事实。

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

## 国产模型与实现候选

国产模型必须使用同一批黄金会议、同一Schema和同一评测程序比较，不能根据通用榜单直接
宣布“最好”。模型名称和能力会持续变化，以下是截至2026-07-29的研究基线，生产配置必须
固定具体模型快照，不使用会静默升级的浮动别名。

### 外部API候选

| 候选 | 在本模块中的优先研究角色 | 主要验证点 |
| --- | --- | --- |
| 千问Qwen | 默认主提取基线、摘要、结构化输出 | 中文会议语义、JSON稳定性、长会召回、成本 |
| 智谱GLM | 独立提取对照、Evidence Verifier | 决策状态、否定和反转、结构化输出 |
| DeepSeek | 复杂语义推理、冲突与证据复核候选 | JSON完整性、非Schema字段、延迟与稳定性 |
| Kimi | 超长会议对照实验 | 中间位置召回、遗漏率、成本，不因窗口大跳过分层提取 |
| MiniMax | 长文本和高并发候选 | Schema遵循、中文口语、吞吐和价格 |
| 豆包 | 国内云服务与批量推理候选 | 地域、吞吐、结构化输出、企业接入成本 |

首轮不是六家全部进入生产。推荐固定三条基线：

```text
主提取：Qwen结构化输出能力较稳定的Plus级模型
独立复核：GLM或DeepSeek，必须与主提取Provider不同
本地候选：开源Qwen指令模型
```

当前阿里云官方把`qwen3.7-plus`列为办公、文档摘要和会议纪要的平衡方案，并支持结构化
输出；`qwen3.7-max`当前不应仅因名称更大就作为默认结构化提取器。模型ID只作为当前候选，
最终选择由本项目黄金集决定。

### 本地开源候选

- Qwen3开源指令模型作为第一优先本地基线，按显存测试4B、8B、30B-A3B等档位。
- DeepSeek开源或蒸馏模型用于推理与验证实验，不默认承担全部长会议提取。
- GLM开源权重在许可证、推理框架和显存满足时加入同Schema评测。
- Kimi等超大MoE开源权重更多用于服务器级研究，不能把“权重开放”等同于“单机可经济部署”。
- 本地推理优先使用vLLM、SGLang或同等级服务框架，由Python服务管理批处理、量化和GPU；
  Go仍然拥有任务、Schema、Evidence和正式Artifact。

### 模型分工而不是单模型包办

```text
规则/统计算法
  -> Speaker统计、词频、词云、时间计算、ID和范围校验

主Extractor
  -> L1语义事件候选

Global Reconciler
  -> 指代、重复、决策和行动状态

Independent Verifier
  -> Artifact是否被Evidence支持

Summary Generator
  -> 只消费已验证L2 Artifact与必要原文
```

是否启用思考模式也必须按任务评测。语义冲突和证据复核可以测试思考模式；高并发结构化
抽取优先测试非思考、低温度或确定性生成。无论Provider声称支持JSON还是JSON Schema，
Go都必须执行独立Schema校验。

## 版本和成本

每次运行记录：

```text
canonical_hash
model_provider
model_name
model_snapshot
prompt_version
schema_version
prompt_hash
generation_parameters_hash
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

- 单次全文提取、分块归并和事件优先提取的质量、召回、成本差异。
- 长会议的语义分块、中间位置召回、重叠窗口和全局归并策略。
- 小模型、大模型和规则算法组合。
- 结构证据有效与语义Evidence支持如何分别验证。
- 建议、提案、暂定、接受、拒绝和撤回的状态识别。
- 模糊代词、隐含负责人、相对日期和多人共同承诺的解析。
- 不同行业Profile是否真的提升质量。
- 多模型验证的收益是否值得成本。
- 自动摘要与人工纪要的一致性。
- ASR错误、Speaker错误和时间戳误差对本模块的影响曲线。
- 口述Prompt注入、隐私数据和恶意结构化文本的安全回归。

## 完整评测体系

### FActScore的准确定位

FActScore不是第三模块的完整实现，也不是全部评测。它提供的方法是：

1. 把生成摘要拆成原子事实。
2. 判断每个原子事实能否被指定来源支持。
3. 计算被支持原子事实的比例，即事实精确率。

本项目将其改造成`Transcript-FActScore`，来源限定为当前Transcript和已验证Artifact。
它适合发现摘要幻觉，但单独使用存在明确盲区：

- 不测应该出现但被遗漏的决策，不能替代Recall和Coverage。
- 不测负责人、截止日期和Speaker是否归属正确。
- 不测建议是否被错误写成正式决策。
- 不测引用能否精确定位到可播放时间点。
- 不测Schema、成本、稳定性和置信度校准。

### 指标矩阵

| 维度 | 必测指标 |
| --- | --- |
| 合同 | Schema Valid Rate、必填字段完整率、版本可重现率 |
| 语义事件 | 各类型Precision、Recall、F1，否定与显式性准确率 |
| 决策 | Decision F1、状态准确率、被否决方案误报率 |
| 行动项 | Action F1、负责人/日期/依赖Slot Accuracy、缺失字段拒造率 |
| 人员 | Speaker Attribution Accuracy、观点和行动归属准确率 |
| Evidence | Evidence Precision、Coverage、Entailment Accuracy、时间定位误差 |
| 摘要 | Transcript-FActScore、关键信息Coverage、遗漏率、重复率 |
| 章节 | 议题边界准确率、章节覆盖率、章节时间范围误差 |
| 置信度 | Brier Score或ECE、不同置信区间的真实正确率 |
| 稳定性 | 同输入重复运行一致性、模型/Prompt升级回归率 |
| 鲁棒性 | ASR扰动、Speaker扰动、长会议位置偏差、Prompt注入通过率 |
| 工程 | 每音频小时Token、成本、端到端延迟、P95/P99、失败和降级率 |
| 人工 | 修订率、每场修订耗时、按Artifact类型的修订原因 |

无证据正式Artifact数量、越权发布数量和未标记的人工补造字段数量目标均为零。

### 黄金集与控制变量

```text
Smoke Set
  4场，只证明管道可运行

Development Set
  30至50场，用于Prompt、Schema和模型调优

Locked Test Set
  至少20场，调优过程不可查看答案

Production Regression Set
  持续从经授权的人工修订中扩充，版本化且不可被训练污染
```

- 决策、行动项和Evidence由至少两名标注者独立标注并仲裁。
- 同时保存人工完美Transcript、真实ASR结果和人工扰动Transcript。
- 对模型做A/B时固定Transcript、Schema、Prompt目标、解码参数和评测版本。
- 公共QMSum、MeetingBank和AMI可用于英文长会议预研，但不能替代中文、行业和真实设备数据。

## 实施顺序

这才是第三模块从零到完整可验证能力的顺序；FActScore只出现在第六步的摘要评测中：

1. **冻结语义本体**：定义L1事件、L2 Artifact、状态、显式性和Evidence合同。
2. **先写标注规范**：没有一致的人类定义，就无法判断哪个模型更好。
3. **建立黄金Fixture**：先完成4场Smoke，再建立Development和Locked Test。
4. **建立国产外部模型基线**：先跑Qwen主提取，GLM/DeepSeek独立对照，不急于本地化。
5. **实现长会议流水线**：语义分块、并行提取、全局归并、状态解析和去重。
6. **实现证据与摘要评测**：结构验证、语义Entailment、Transcript-FActScore和Coverage。
7. **生成L3派生视图**：摘要、章节、热词、词云、时间线、思维导图和树状图。
8. **接入本地开源模型**：在同一黄金集上比较质量、显存、吞吐和成本。
9. **加入Profile和人工闭环**：周会、访谈、销售、培训等Profile独立验收。
10. **达到发布门禁**：模型升级只能在锁定测试集和安全回归均通过后发布。

## 完成标准

- 固定`MeetingArtifactBundle v1`。
- 固定L1语义事件、L2正式Artifact和L3派生视图的权威关系。
- 所有正式事实性Artifact带有效证据。
- 正式Artifact同时通过结构验证和语义Evidence验证。
- 不存在的信息保持为空，不由模型补写。
- 同输入和版本可以稳定重现或命中缓存。
- 更换模型不会改变下游数据合同。
- 建立4场Smoke、30至50场Development和至少20场Locked Test。
- 七类兼容视图、L1/L2语义产物和所有L3派生产物均有独立验收。
- 国产外部模型和本地模型均通过相同评测合同，且可在Provider层替换。
- 音频证据可以从Artifact稳定跳转到正确会议、Speaker和时间点。
- Prompt注入、跨租户访问和无证据正式发布的安全测试必须全部通过。

## 研究依据

- [通义听悟自定义Prompt与输入截断](https://help.aliyun.com/zh/tingwu/custom-prompt)
- [阿里云百炼文本模型与当前国产模型能力](https://help.aliyun.com/zh/model-studio/text-generation-model/)
- [千问结构化输出](https://help.aliyun.com/zh/model-studio/qwen-structured-output)
- [智谱结构化输出](https://docs.bigmodel.cn/cn/guide/capabilities/struct-output)
- [DeepSeek JSON Output](https://api-docs.deepseek.com/api/create-chat-completion)
- [QMSum长会议定位后总结](https://aclanthology.org/2021.naacl-main.472/)
- [MeetingBank分段与纪要对齐](https://aclanthology.org/2023.acl-long.906/)
- [Lost in the Middle长上下文位置偏差](https://arxiv.org/abs/2307.03172)
- [FActScore原子事实精确率](https://aclanthology.org/2023.emnlp-main.741/)
- [Google LangExtract分块提取与来源定位](https://github.com/google/langextract)
