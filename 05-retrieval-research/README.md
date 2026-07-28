# ⑤ 检索与研究 Retrieval / Research

## 一句话定位

读取会议、Artifact和Memory，在权限范围内找到正确证据并回答用户问题。

Memory负责记住什么；这一块负责如何找到、排序、拒答、综合和引用。

## 输入

```json
{
  "query": "Android方案后来为什么从Flutter改成Kotlin？",
  "tenant_id": "tenant_xxx",
  "project_scope": ["android"],
  "meeting_scope": null,
  "time_scope": null,
  "conversation_context": []
}
```

## 输出：SearchResult 与 QueryResult

`SearchResult` 用于会议定位、原文搜索和证据浏览，不调用答案模型：

```json
{
  "query_id": "query_xxx",
  "schema_version": "search-result-v1",
  "meetings": [
    {"meeting_id": "meeting_b", "score": 0.91, "matched_evidence_ids": ["seg_018"]}
  ],
  "evidence": ["seg_018"],
  "degraded": false
}
```

`QueryResult` 在证据可回答且引用验证通过后返回综合答案：

```json
{
  "query_id": "query_xxx",
  "schema_version": "query-result-v1",
  "answer": "两场会议显示方案由Flutter调整为原生Kotlin……",
  "no_answer": false,
  "confidence": 0.92,
  "meetings": ["meeting_a", "meeting_b"],
  "claims": [],
  "citations": [
    {
      "meeting_id": "meeting_b",
      "segment_id": "seg_018",
      "speaker_id": "speaker_02",
      "start_ms": 183200,
      "end_ms": 195800,
      "quote": "首版我们改成原生Kotlin。",
      "playback_status": "valid"
    }
  ]
}
```

## 完整功能点

### 查询理解

- 识别单会议或跨会议意图。
- 识别会议名称。
- 识别项目。
- 识别人员。
- 识别组织和客户。
- 识别产品和型号。
- 识别时间范围。
- 识别数字、金额和日期条件。
- 识别“当前”“之前”“后来”等时态意图。
- 识别比较、总结、变化、原因和待办问题。
- 多轮对话查询改写。
- 对话上下文不得扩大权限范围。

### 多级索引

```text
segment_index
  - 原始证据定位

semantic_chunk_index
  - 连续语义块召回

artifact_index
  - 摘要、决策、待办、风险和主题

claim_index
  - 当前和历史事实

meeting_index
  - 标题、摘要、参与人、时间和项目

entity_index
  - 人名、公司、产品、型号和缩写
```

所有索引均可从权威数据重建。

### 召回

- PostgreSQL FTS。
- BM25。
- 中文分词。
- 精确短语。
- 标题匹配。
- 实体匹配。
- 时间和结构化过滤。
- 向量召回。
- Embedding查询扩展。
- 同义词和缩写扩展。
- Segment和Claim并行召回。
- 单会议范围召回。
- 多会议范围召回。
- 全局范围召回。

### 融合与排序

- RRF。
- 加权融合。
- 词法和向量真实分数。
- Meeting级聚合。
- 一个会议中过多Chunk去重。
- 会议多样性。
- MMR。
- Cross Encoder Reranker。
- 实体覆盖加权。
- 标题和时间加权。
- Top-1与Top-2分差。
- 排序原因记录。

### 单会议问题

- 找到指定会议。
- 获取会议摘要。
- 查询某人说了什么。
- 查询某个时间段。
- 查询决策和待办。
- 查询风险和开放问题。
- 返回对应Segment和音频位置。

### 跨会议问题

- 找到相关会议集合。
- 按时间排序。
- 子问题分解。
- 每场会议分别取证。
- 多场会议比较。
- 多场会议整体总结。
- 决策变化。
- 行动项连续跟踪。
- 冲突观点。
- 趋势和重复问题。
- 会议集合覆盖检查。
- 防止单一会议垄断召回结果。

### no-answer拒答

- 资料中不存在答案。
- 证据主题相近但不能回答问题。
- 指定实体没有出现。
- 指定时间范围没有会议。
- 有答案但用户没有权限。
- 召回服务故障与真正无答案分开。
- 给出拒答原因。
- 提供缩小或扩大范围建议。

拒答判断综合：

- Top-1词法分数。
- Top-1向量相似度。
- Reranker分数。
- Top-1与Top-2分差。
- 实体覆盖率。
- 证据数量。
- 会议覆盖。
- 可回答性或蕴含分数。

阈值必须使用独立校准集，不让LLM单独决定。

### 答案生成

- 确定性答案模板。
- LLM综合答案。
- 每个结论绑定引用。
- 区分原话、摘要和系统推断。
- 当前决策读取Memory状态。
- 冲突信息同时呈现。
- 不使用未召回内容。
- LLM输出后逐结论验证。
- 失败时退回证据列表。

### 引用和播放

- Meeting ID。
- Segment ID。
- Speaker。
- 起止时间。
- 原文Quote。
- 对象是否存在。
- 时间是否位于音频范围。
- Quote是否与Transcript对齐。
- 当前用户是否有权限。
- 短期播放地址。
- HTTP Range或片段播放。
- 引用不可播放时不得作为正式答案证据。

### 可观测与实验

- 保存查询原文和规范化查询。
- 保存权限范围。
- 保存候选及各阶段分数。
- 保存Embedding、索引和Reranker版本。
- 保存阈值和Prompt版本。
- 保存延迟、Token和成本。
- 支持完整离线回放。
- 新算法Shadow评测。
- 指标未通过不得提升为默认版本。

## 数据所有权

本模块权威拥有的只是检索侧运行数据：

- 可重建的 Segment、Artifact、Claim、Meeting 和 Entity 索引。
- 查询解析、召回候选、各阶段分数、排序解释和查询版本。
- 答案生成运行、引用验证结果、拒答原因、延迟、Token 和成本。
- 检索评测集、qrels、阈值、实验配置和用户对答案的反馈引用。

本模块不拥有逐字稿、单会产物、Claim 当前状态、权限主档或聊天历史。索引内容与权威源
冲突时以权威源为准；查询反馈不能直接修改事实。

## 命令、查询与事件

维护命令：

```text
IndexTranscript
IndexArtifacts
IndexMemory
RebuildIndex
RemoveMeetingFromIndex
RunOfflineEvaluation
```

用户查询：

```text
Search
Query
CompareMeetings
SummarizeMeetingSet
ExplainDecisionHistory
```

事件：

```text
IndexUpdated
IndexBuildFailed
QueryCompleted
QueryRefused
CitationValidationFailed
RetrievalFeedbackRecorded
```

`SearchResult` 返回排序后的会议和证据，不强制生成答案；`QueryResult` 在证据可回答且引用
通过验证时才包含综合答案。两者都必须携带实际权限范围和查询配置版本。

## 状态机

```text
RECEIVED
  -> AUTHORIZED
  -> PLANNED
  -> RETRIEVED
  -> RERANKED
  -> ANSWERABILITY_CHECKED
  -> GENERATED
  -> CITATIONS_VALIDATED
  -> COMPLETED
```

证据不足进入 `REFUSED`；索引暂不可用可退化为权威数据库过滤和全文检索；生成失败可返回
`EVIDENCE_ONLY`。任何降级都必须对调用方可见。

## 依赖规则

- 并行读取 Transcript、Artifact 和 Memory 的稳定只读接口，不只读取 Memory。
- 读取查询前由产品模块提供 `TenantScope`，本模块在每次召回和取证时再次约束。
- Embedding、向量库、全文检索、融合、Reranker 和回答模型都是内部 Provider。
- 只写索引、运行日志和反馈，不写 Transcript、Artifact 或 Claim。
- 引用播放通过稳定媒体/产品接口签发，不能直接暴露对象存储路径。

## 错误分类

- 查询为空、范围不合法或指定资源不存在：请求错误。
- 无权限与“有资源但资料无答案”必须分开处理，同时不能泄露越权资源存在性。
- 索引过期或缺失：数据新鲜度错误，尝试权威源降级并触发重建。
- Embedding、Reranker 或 LLM 临时故障：按能力降级，不应直接产生无引用答案。
- 引用越界、版本不一致、原文不匹配或不可播放：引用校验失败，该结论不得发布。
- 召回正常但证据不可回答：正式拒答，不属于系统故障。

## 实时与离线边界

- 会中可以检索 partial Transcript，但结果标记“会中临时”，不与最终会议答案混淆。
- 最终 Transcript、Artifact 或 Memory 版本发布后按事件增量更新索引。
- 修订、替代和删除必须使相关索引项失效，再异步重建。
- 跨会议综合默认只使用 final 数据；显式请求实时会议时才能混入 partial 数据并分层展示。

## 可插拔点

```text
LexicalRetriever
  - PostgreSQL FTS
  - BM25

EmbeddingProvider
  - 本地Embedding
  - API Embedding

VectorStore
  - pgvector
  - 其他向量库

FusionStrategy
  - RRF
  - Weighted Fusion

Reranker
  - 本地Cross Encoder
  - API Reranker

AnswerGenerator
  - 确定性
  - LLM

QueryOrchestrator
  - LangGraph
  - 普通状态机
  - 其他编排
```

## 研究重点

- 中文会议查询的分词、Embedding和Reranker选择。
- Segment、语义Chunk、Artifact与Claim多级召回的最佳组合。
- Meeting级聚合如何避免单个高分片段带偏会议定位。
- 跨会议问题如何拆分子问题并保证会议集合覆盖。
- no-answer阈值如何使用真实正负样本校准。
- 对话上下文如何帮助改写查询但不污染事实和权限。
- 旧决策、当前决策和冲突Claim如何生成可解释答案。
- 本地模型、外部API和确定性算法在质量、延迟、资源及成本上的取舍。
- 引用文字、时间点与音频播放的一致性自动验收。
- 检索配置版本化、离线回放、Shadow流量和灰度提升机制。

## 评测指标

| 指标 | 定义 | 目标 |
|---|---|---:|
| Recall@10 | 标准证据进入前十的比例 | ≥95% |
| MRR@10 | 第一条正确结果的倒数排名 | ≥0.85 |
| nDCG@10 | 分级相关结果的排序质量 | ≥0.90 |
| 会议定位Top-1 | 第一场会议是否正确 | ≥90%，目标95% |
| 跨会议Meeting F1 | 目标会议集合是否找全 | ≥90% |
| 跨会议事实F1 | 综合结论中的事实是否正确 | ≥90% |
| no-answer F1 | 有无答案判断 | ≥90% |
| 无证据误答率 | 无答案仍生成答案 | ≤5% |
| 引用准确率 | 引用是否支持对应结论 | ≥98% |
| 引用可播放率 | 引用能否定位原音频 | 100% |
| 当前决策回答准确率 | 是否引用最新有效Claim | ≥95% |

## 评测数据

必须包含：

- 单一事实。
- 会议定位。
- 指定人员观点。
- 时间范围。
- 数字、金额和型号。
- 同义改写和简称。
- 跨会议比较。
- 跨会议总结。
- 旧决策替代。
- 冲突事实。
- 明确无答案。
- 全库存在但权限范围内不存在。

每个问题标注相关Meeting、Segment、Claim和0–3级相关度，并划分开发集、校准集和
最终测试集。

## 明确边界

- 不生成Transcript。
- 不修改Artifact。
- 不修改Claim当前状态。
- 不把聊天历史当成会议事实。
- 不在证据不足时强行回答。
- 不直接信任LLM生成的引用。
- 不绕过权限进行全库召回。

## 完成标准

- 固定`QueryResult v1`。
- 建立统一qrels和可重复评测Runner。
- 所有检索阶段暴露真实分数。
- no-answer拥有独立负样本和校准集。
- 单会、多会、历史变化都有黄金问题。
- 所有正式答案完成逐结论引用验证。
- 引用可播放率达到100%。
- 更换向量库、Embedding或Reranker不改变产品输出合同。
