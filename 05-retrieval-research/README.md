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

## 输出：QueryResult

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

## Memory/RAG质量指标

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
