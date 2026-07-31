# ⑤ 检索与研究 Retrieval / Research

## 一句话定位

读取会议、Artifact和Memory，在冻结的权限与数据快照内找到正确证据、判断能否回答，
并生成可验证的答案或研究结果。

Memory负责记住什么；这一块负责如何找到、排序、拒答、综合和引用。

它不只是“向量库加聊天”。本模块同时提供两条只读能力：

```text
Online Search / Answer
  低延迟会议定位、证据搜索、单会问答和常见跨会问题

Async Research
  面向全部授权会议的集合枚举、子问题研究、覆盖检查、冲突分析和长报告
```

两条链路共享权限、索引、召回、排序、证据和评测能力，但具有不同的延迟预算、停止条件和
结果合同。任何查询结果都不能反写Transcript、Artifact或Meeting Memory。

## 实现语言与运行边界

### 语言结论

本模块采用 Go 查询控制层加 Python 模型层：

```text
Go Retrieval Service
├── Authorization Snapshot
├── Typed Query Planner
├── Index / Memory Watermark
├── Metadata / Current-State Direct Read
├── Lexical / Dense / Graph Candidate Routes
├── Candidate Ledger / Fusion / Diversity
├── No-answer Gate
├── Coverage Gate
├── Answer Claim Ledger
├── Citation Validation
├── Online Query State
└── ResearchRun State
                 │
                 ▼
Python Retrieval Model Service
├── Embedding
├── Cross-encoder Reranker
├── Query Rewrite Candidate
├── Sub-question Candidate
├── Answerability Candidate
├── Local Answer Model
└── Retrieval Evaluation
```

Go 负责：

- 从06建立的可信身份上下文生成不可扩大的Authorization Snapshot，不信任客户端自行声明tenant。
- 冻结本次查询的权限版本、04 Memory Snapshot、Transcript/Artifact版本和索引水位。
- 把问题分类为会议定位、原文查找、单会问答、当前状态、历史变化、跨会比较、集合总结或研究。
- 解析显式过滤条件，区分业务有效时间、系统记录时间、会议时间和普通日期条件。
- 对当前状态和历史变化直接查询04的`CurrentStateView`与`StateTimeline`，再补齐原文证据。
- 按Query Plan选择元数据、结构化SQL、PostgreSQL FTS、BM25 Provider、pgvector或图投影路线。
- 维护每个候选的来源、版本、ACL、各阶段分数和淘汰原因。
- 实现RRF、受控加权融合、Meeting聚合、去重、多样性和每条路线的候选预算。
- 调用 Python Embedding/Reranker 或外部模型 Provider。
- 在任何文本进入模型前过滤无权访问、已删除、版本过期和证据失效的内容。
- 按查询类型校准answerability，决定完整回答、部分回答、拒答或降级为证据列表。
- 对集合查询计算目标会议、目标维度和答案Claim的覆盖率，不允许Top-K冒充全量总结。
- 调用外部答案 LLM，或把候选交给 Python 本地答案模型。
- 把答案拆成原子Answer Claim，逐条验证支持证据、反对证据、原文、版本和时间点。
- 分开校验Citation有效性与音频播放服务状态。
- 通过共享Temporal基础设施持久编排长时间ResearchRun，但不把Temporal当数据权威。
- 发布`SearchResult`、`QueryResult`与`ResearchResult`，记录完整查询和检索配置版本。

Python 负责：

- 查询、Segment、语义窗口、Artifact、State和Entity的Embedding推理。
- Cross-encoder Reranker 和候选相关性分数。
- 查询改写、子问题拆分、answerability和答案生成候选。
- 本地模型加载、批处理、GPU 调度和模型评测。
- 输出分数、向量、候选答案、候选引用和模型诊断。

Python 禁止：

- 绕过 Go 的 `TenantScope` 访问全库数据。
- 自行查询权威私有表或决定当前有效State。
- 把模型生成的引用直接当成有效引用。
- 修改Transcript、Artifact、Observation、Claim、StateVersion或索引源。
- 在无证据时强行生成答案。
- 将对话上下文写回 Meeting Memory。
- 自行扩大会议集合、时间范围、租户范围或Token预算。
- 把Research推断静默保存为04权威事实。

### 确定性检索与模型推理边界

以下能力默认在 Go 中实现，保证可解释、可回放：

- 权限过滤、元数据过滤和 SQL 查询。
- 类型化Query Plan、FTS、向量库客户端、候选融合和Meeting聚合。
- StateSlot、StateVersion、双时态与Scope过滤。
- answerability、coverage和正式状态最终门禁。
- 引用合法性检查和播放状态检查。

以下能力放在 Python 模型服务：

- Embedding。
- Cross-encoder Reranker。
- 本地查询改写模型。
- 本地答案生成模型。

LangGraph可以作为Python Research Planner Provider参加对照实验，但不能拥有权限、检索事实、
State状态、预算或正式运行状态机。稳定查询与研究生命周期由Go控制；移除LangGraph后，
基础Search、Answer、拒答、引用以及确定性Research Plan仍必须工作。

### 通信与部署

- Embedding 和 Reranker 使用批量 gRPC 请求，设置最大候选数、Token 预算和 Deadline。
- 在线Search/Answer、异步Research Worker和离线Indexer分开扩缩容。
- 大批量离线建索引通过后台任务和Generation切换完成，在线查询不得同步重建全量索引。
- Python 模型服务按查询队列、Batch、GPU/CPU 利用率、QPS 和推理 P99 扩容。
- Go Retrieval Service 按查询 QPS、连接数、数据库连接池和端到端 P99 扩容。
- 外部答案模型失败时退化为排序后的证据，不把基础检索可用性绑定在 LLM 上。
- 外部模型可通过LiteLLM或等价网关路由；网关只负责模型调用，不拥有查询状态和证据真相。

## 输入

```json
{
  "request_id": "request_xxx",
  "query": "Android方案后来为什么从Flutter改成Kotlin？",
  "mode": "answer",
  "requested_scope": {
    "project_ids": ["android"],
    "meeting_ids": null,
    "meeting_time": null
  },
  "temporal_intent": {
    "valid_time": null,
    "system_time": null
  },
  "conversation_context_ref": "conversation_xxx"
}
```

`tenant_id`、用户身份、角色、允许访问的项目、会议、字段和证据不接受客户端覆盖，而是由06
鉴权后注入可信上下文。本模块把`requested_scope`与授权范围求交，得到不可扩大的
`AuthorizationSnapshot`。

## 输出合同

`SearchResult` 用于会议定位、原文搜索和证据浏览，不调用答案模型：

```json
{
  "query_id": "query_xxx",
  "schema_version": "search-result-v1",
  "status": "completed",
  "authorization_snapshot_id": "auth_snapshot_xxx",
  "index_generation": "index_gen_042",
  "hits": [
    {
      "hit_type": "meeting",
      "meeting_id": "meeting_b",
      "source_version": 5,
      "matched_evidence_ids": ["seg_018"],
      "score_components": {
        "lexical_rank": 2,
        "dense_rank": 1,
        "fusion_score": 0.0325,
        "reranker_score": 0.91
      }
    }
  ],
  "degradations": []
}
```

`QueryResult` 在证据可回答且引用验证通过后返回综合答案：

```json
{
  "query_id": "query_xxx",
  "schema_version": "query-result-v1",
  "status": "answered",
  "answer": "两场会议显示方案由Flutter调整为原生Kotlin……",
  "meetings": ["meeting_a", "meeting_b"],
  "answer_claims": [
    {
      "answer_claim_id": "answer_claim_001",
      "text": "Android首版方案后来改为原生Kotlin。",
      "claim_type": "current_state",
      "inference_level": "supported_synthesis",
      "calibrated_confidence": 0.92,
      "supporting_citation_ids": ["citation_001"],
      "contradicting_citation_ids": []
    }
  ],
  "coverage": {
    "target_meeting_count": 2,
    "covered_meeting_count": 2,
    "missing_dimensions": []
  },
  "freshness": {
    "memory_snapshot_id": "memory_snapshot_xxx",
    "index_generation": "index_gen_042",
    "stale_sources": []
  },
  "citations": [
    {
      "citation_id": "citation_001",
      "meeting_id": "meeting_b",
      "transcript_version": 4,
      "segment_id": "seg_018",
      "speaker_id": "speaker_02",
      "start_ms": 183200,
      "end_ms": 195800,
      "quote": "首版我们改成原生Kotlin。",
      "citation_valid": true,
      "playback_ready": true
    }
  ],
  "degradations": []
}
```

正式状态不是一个布尔`no_answer`：

```text
answered
partial
insufficient_evidence
not_found_or_inaccessible
degraded
failed
```

对外使用`not_found_or_inaccessible`避免泄漏越权资源是否存在；内部审计可以保存更精确原因。
不能用一个未定义来源的总`confidence`掩盖某些结论证据充分、另一些结论只是推断。

长时间研究输出`ResearchResult`：

```json
{
  "research_run_id": "research_xxx",
  "schema_version": "research-result-v1",
  "status": "completed",
  "question": "总结Android项目过去六个月的决策变化和未完成事项",
  "meeting_universe": {
    "authorized_count": 18,
    "processed_count": 18
  },
  "subquestions": ["决策如何变化", "哪些行动项仍未完成"],
  "answer_claim_ids": ["answer_claim_001"],
  "conflict_sets": [],
  "coverage": {
    "meeting_coverage": 1.0,
    "required_dimension_coverage": 1.0,
    "missing_dimensions": []
  },
  "stop_reason": "coverage_satisfied",
  "citation_ids": ["citation_001"]
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
- 区分用户要求“找资料”“回答问题”还是“研究完整集合”。
- 区分“会议发生时间”“事实有效时间”“系统当时知道什么”。
- 所有模型解析结果是Query Plan候选，显式Scope、权限和预算由Go硬约束。

### 类型化查询计划

不同问题不能无条件走同一套Hybrid RAG：

| 查询类型 | 主路线 | 是否默认生成答案 |
|---|---|---|
| 会议定位 | 标题、参与人、项目、时间和元数据SQL/FTS | 否 |
| 精确原文 | Speaker、时间、数字、型号、短语和Segment词法检索 | 否 |
| 单会议语义问答 | 限定会议后的词法＋Dense＋Reranker | 是 |
| 当前状态 | 04 `CurrentStateView`直接读取＋证据补全 | 是 |
| 历史变化 | 04 `StateTimeline`双时态查询＋相关会议证据 | 是 |
| 跨会议比较 | 先召回Meeting Set，再逐会召回证据和检查覆盖 | 是 |
| 全范围总结 | 枚举全部授权会议，分层Map/Reduce，不使用Top-K代替全集 | Research |
| 开放式研究 | 子问题、迭代召回、Claim Ledger、冲突和停止条件 | Research |

每个`QueryPlan`至少保存：

```text
query_type
authorization_snapshot_id
memory_snapshot_id
index_generation
routes
filters
candidate_budget_per_route
rerank_budget
answer_token_budget
coverage_requirements
stop_conditions
deadline
```

Query Planner可以使用规则、模型或LangGraph生成候选计划，但Go必须验证路线、Scope、预算和
停止条件。会议定位、当前状态等确定性问题不得因为Agent选择错误而跳过权威读取。

### 多级索引

```text
segment_index
  - 不可变Segment和词级时间点，负责最终证据定位

semantic_chunk_index
  - 连续语义窗口和父子关系，负责语义召回

artifact_index
  - 摘要、决策、待办、风险和主题

memory_projection_index
  - Observation、StateSlot、Claim和StateVersion的可重建检索投影

meeting_index
  - 标题、摘要、参与人、时间和项目

entity_index
  - 人名、公司、产品、型号和缩写
```

语义Chunk可以跨多个短Segment建立上下文，但必须保存`parent_segment_ids`和字符/时间范围，
最终引用只能回到权威Transcript Segment或Word。不得把模型生成的Chunk摘要伪装成原话。

所有索引均可从权威数据重建。每条索引记录至少包含：

```text
tenant_id
source_type
source_id
source_version
acl_version
index_schema_version
embedding_version
index_generation
finality
deleted_at
```

一次查询固定一个已激活`index_generation`。新Generation完成一致性校验后原子切换；
重建过程中不允许同一答案混用旧Transcript向量、新Artifact和新Memory状态。

### 词法检索边界

- PostgreSQL原生FTS使用`ts_rank`或`ts_rank_cd`等排名函数，不等同于标准BM25。
- 第一版使用PostgreSQL FTS、精确短语、规范化实体、数字/金额/日期/型号匹配和pg_trgm候选。
- 中文分词器、同义词词典、拼音、人名别名和英文缩写必须版本化并独立评测。
- 真正BM25作为`LexicalRetriever` Provider，可由OpenSearch、专用扩展或其他搜索引擎实现。
- 没有数据证明PostgreSQL基线不满足质量、QPS或运维目标前，不默认增加OpenSearch。

### 召回

- PostgreSQL FTS。
- 可选BM25 Provider。
- 中文分词。
- 精确短语。
- 标题匹配。
- 实体匹配。
- 时间和结构化过滤。
- 向量召回。
- Embedding查询扩展。
- 同义词和缩写扩展。
- Segment、Artifact和Memory Projection并行召回。
- CurrentState和StateTimeline权威直读。
- Graphiti或其他图投影候选召回。
- 单会议范围召回。
- 多会议范围召回。
- 全局范围召回。
- Parent/Child窗口扩展。
- 查询类型决定路线，不要求每次都调用所有Retriever。
- 所有Retriever在候选产生前应用授权和数据版本过滤。

pgvector使用HNSW或IVFFlat近似索引并带租户、项目或权限过滤时，需要测试过滤后的实际Recall。
可以使用过滤列索引、分区、Partial Index和Iterative Scan，不能只看未过滤向量基准。

### 融合与排序

- RRF作为不同分数量纲Retriever的稳定基线。
- 加权融合必须经过校准集验证，不能直接相加BM25、余弦和模型Logit。
- 保存词法、向量、图、结构化匹配的原始分数、Rank和变换后分数。
- Meeting级聚合。
- 一个会议中过多Chunk去重。
- 会议多样性。
- MMR。
- Cross Encoder Reranker。
- 实体覆盖加权。
- 标题和时间加权。
- Top-1与Top-2分差。
- 排序原因记录。
- Reranker只处理受控Top-N，超预算时按查询类型降级。
- 跨会议查询在Chunk排序后执行Meeting Set覆盖和组内取证，不能只保留全局最高分Chunk。
- 每个候选进入Candidate Ledger，支持离线复盘“在哪里丢失了正确证据”。

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
- 分开保存“哪些会议相关”和“每场会议哪些证据相关”的两级qrels与评分。
- 当前结论必须读取04当前状态；历史观点和旧决定只能作为时间线或冲突背景。

### 全范围总结

“总结这个项目全部会议”“所有会议有哪些未完成事项”属于集合查询，不是普通Top-K问答：

```text
枚举Authorization Snapshot内的全部目标Meeting ID
  -> 固定每场会议的Transcript/Artifact版本
  -> 按会议提取所需Artifact和State证据
  -> 分批Map
  -> 按时间、实体、议题和StateSlot归并
  -> Reduce
  -> 计算Meeting与必需维度覆盖
  -> 生成带遗漏声明的结果
```

- 返回`authorized_count`、`processed_count`、失败会议和缺失维度。
- 任何会议处理失败时只能返回`partial`，不能声称“全部”。
- 热门或文本较长的会议不得因为Chunk更多而获得不合理权重。
- Map/Reduce中间摘要是本次ResearchRun的派生材料，不进入04权威Memory。

### 异步Research

- 把开放问题拆成可审计的子问题和预期证据类型。
- 先确定授权Meeting Universe，再按子问题召回，避免边搜边无限扩大范围。
- 维护Answer Claim Ledger、支持证据、反对证据、未解决冲突和信息缺口。
- 支持时间线、项目对比、人员观点对比、风险演变和行动项连续性研究。
- 设置最大迭代、Deadline、模型调用、Token、候选和费用预算。
- 停止原因必须是覆盖满足、预算耗尽、Deadline、用户取消或证据不足之一。
- Temporal负责重试、恢复和长任务状态；Go数据库保存ResearchRun权威状态。
- Research结果不能自动提升为04 Claim，用户要保存结论时必须重新走04 Promotion与审核。

### no-answer拒答

- 资料中不存在答案。
- 证据主题相近但不能回答问题。
- 指定实体没有出现。
- 指定时间范围没有会议。
- 有答案但用户没有权限。
- 召回服务故障与真正无答案分开。
- 给出拒答原因。
- 提供缩小或扩大范围建议。
- 可以回答一部分时返回`partial`并列出缺失维度，不强行二选一。
- 对外把不存在与无权限统一为`not_found_or_inaccessible`，内部原因只进入安全审计。

拒答判断综合：

- Top-1词法分数。
- Top-1向量相似度。
- Reranker分数。
- Top-1与Top-2分差。
- 实体覆盖率。
- 证据数量。
- 会议覆盖。
- 可回答性或蕴含分数。
- 权威State是否存在。
- 索引水位是否满足查询一致性要求。

阈值必须按查询类型使用独立校准集，不让LLM单独决定。除F1外还需要观察False Answer Rate、
False Refusal Rate、Precision-Recall、Brier/ECE和不同覆盖率下的Selective Risk。

### 答案生成

- 确定性答案模板。
- LLM综合答案。
- 先生成原子Answer Claim，再组合最终自然语言答案。
- 每个Answer Claim绑定支持引用、反对引用和推断级别。
- 区分原话、摘要和系统推断。
- 当前决策读取04 `CurrentStateView`，历史变化读取`StateTimeline`。
- 冲突信息同时呈现。
- 不使用未召回内容。
- LLM只能引用本次Evidence Packet中的不透明Citation ID，不能自行编造ID或URL。
- 输出后逐Answer Claim做证据蕴含、范围、时态和引用完整性验证。
- 失败时退回证据列表。
- 答案模型的通用知识不得补充会议内部没有出现的事实；必要背景必须明确标记为外部来源，
  且当前项目默认不启用外部互联网研究。

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
- `citation_valid`验证证据真实性、版本、原文、时间和权限。
- `playback_ready`表示当前是否能签发和访问短期播放地址。
- Citation无效时对应Answer Claim不得发布。
- Citation有效但播放服务暂时故障时可以发布事实答案，并显式返回播放降级原因。
- 播放地址每次签发前重新鉴权，不把对象存储URI、永久URL或跨用户缓存返回客户端。

### 权限、缓存与一致性

- Authorization必须在元数据、FTS、向量、图、Reranker输入和证据补全每个阶段重复约束。
- 无权内容不得先召回后仅在最终答案过滤，避免模型输入、日志、计数和延迟侧信道泄漏。
- 共享索引中的每条记录携带tenant和ACL版本；超大租户可按数据与QPS证据选择分区。
- 缓存键至少包含tenant、Authorization Snapshot、Scope Hash、规范化查询、Index Generation、
  Memory Snapshot、模型和Prompt版本。
- 删除或权限收紧先发布不可绕过的Tombstone/deny记录，再异步清理向量、图和缓存。
- 索引比权威源旧且问题依赖新状态时，优先权威直读或返回`degraded`，不能静默回答旧结论。
- 查询日志和评测样本默认脱敏，不保存完整未授权候选、永久播放URL或外部模型密钥。

### 可观测与实验

- 保存查询原文和规范化查询。
- 保存权限范围。
- 保存候选及各阶段分数。
- 保存Embedding、索引和Reranker版本。
- 保存阈值和Prompt版本。
- 保存Authorization Snapshot、Memory Snapshot、Index Generation和降级路径。
- 保存延迟、Token和成本。
- 分阶段记录召回、融合、Rerank、Answerability、生成和Citation校验耗时。
- 支持完整离线回放。
- 新算法Shadow评测。
- 指标未通过不得提升为默认版本。

## 数据所有权

本模块权威拥有的只是检索侧运行数据：

- 可重建的Segment、Artifact、Memory Projection、Meeting和Entity索引及Generation水位。
- 查询解析、召回候选、各阶段分数、排序解释和查询版本。
- Online Query、ResearchRun、Answer Claim Ledger、覆盖结果和停止原因。
- 答案生成运行、引用验证结果、拒答内部原因、延迟、Token和成本。
- 检索评测集、qrels、阈值、实验配置和用户对答案的反馈引用。

本模块不拥有逐字稿、单会产物、Observation、Claim、StateVersion当前状态、权限主档或
聊天历史。Answer Claim只是一次查询或研究运行的派生结论，不是04 Claim。索引内容与权威源
冲突时以权威源为准；查询反馈和Research结果不能直接修改事实。05拥有内部ResearchRun，
06拥有面向用户的Job、Conversation和通知，两者通过稳定ID和事件关联而不共用私有状态表。

## 命令、查询与事件

维护命令：

```text
IndexTranscript
IndexArtifacts
IndexMemory
BuildIndexGeneration
ValidateIndexGeneration
ActivateIndexGeneration
InvalidateSources
RebuildIndexProjection
RemoveMeetingFromIndex
RunOfflineEvaluation
```

用户查询：

```text
Search
Answer
CompareMeetings
SummarizeMeetingSet
ExplainDecisionHistory
StartResearch
GetResearchRun
CancelResearch
```

事件：

```text
IndexGenerationBuilt
IndexGenerationActivated
IndexBuildFailed
QueryCompleted
QueryRefused
CitationValidationFailed
ResearchStarted
ResearchProgressed
ResearchCompleted
ResearchFailed
RetrievalFeedbackRecorded
```

`SearchResult`返回排序后的会议和证据，不强制生成答案；`QueryResult`在证据可回答且引用
通过验证时才包含综合答案；`ResearchResult`包含Meeting Universe、覆盖、冲突、缺口和停止原因。
三者都必须携带Authorization Snapshot引用、数据水位和查询配置版本。

## 在线查询状态机

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

## ResearchRun状态机

```text
CREATED
  -> AUTHORIZED
  -> UNIVERSE_FROZEN
  -> PLANNED
  -> COLLECTING
  -> SYNTHESIZING
  -> COVERAGE_CHECKED
  -> CITATIONS_VALIDATED
  -> COMPLETED

COLLECTING / SYNTHESIZING
  -> PARTIAL
  -> FAILED
  -> CANCELLED
```

Temporal可以恢复Workflow执行，但`ResearchRun`、预算消耗、授权快照、数据水位和结果版本保存在
Go权威数据库中。重试不得重复计费、重复发布结果或改变已冻结Meeting Universe。

## 依赖规则

- 并行读取 Transcript、Artifact 和 Memory 的稳定只读接口，不只读取 Memory。
- 04接口使用`CurrentStateView`、`StateTimeline`、Observation和授权Evidence，不读取图投影冒充事实。
- 读取查询前由06提供可信身份上下文，本模块生成Authorization Snapshot并在每次召回和取证时约束。
- Embedding、向量库、全文检索、融合、Reranker 和回答模型都是内部 Provider。
- 只写索引、Query/Research运行、日志和反馈，不写Transcript、Artifact或04权威Memory。
- 引用播放通过稳定媒体/产品接口签发，不能直接暴露对象存储路径。
- 01/02/03/04的修订、权限和删除事件通过Outbox或等价可靠事件驱动索引失效与重建。
- 06只调用稳定Search/Answer/Research合同，不直接查询pgvector、图数据库或Reranker。

## 错误分类

- 查询为空、范围不合法或指定资源不存在：请求错误。
- 无权限与“有资源但资料无答案”必须分开处理，同时不能泄露越权资源存在性。
- 索引过期、Generation未激活或源版本不一致：数据新鲜度错误，尝试权威源降级并触发重建。
- Authorization Snapshot失效或权限版本变更：终止旧查询，重新鉴权，不能沿用旧缓存。
- Embedding、Reranker 或 LLM 临时故障：按能力降级，不应直接产生无引用答案。
- 引用越界、版本不一致或原文不匹配：引用无效，该结论不得发布。
- 播放签名或媒体服务暂时失败：返回播放降级，不把有效证据误判为无答案。
- 召回正常但证据不可回答：正式拒答，不属于系统故障。
- Research部分会议处理失败：返回`partial`与失败清单，不能声称完整覆盖。
- 预算或Deadline耗尽：按已有证据返回`partial`或`insufficient_evidence`并保存停止原因。

## 实时与离线边界

- 会中可以检索 partial Transcript，但结果标记“会中临时”，不与最终会议答案混淆。
- 最终Transcript、Artifact或Memory版本发布后按事件增量更新新Index Generation。
- 修订、替代和删除必须使相关索引项失效，再异步重建。
- 跨会议综合默认只使用 final 数据；显式请求实时会议时才能混入 partial 数据并分层展示。
- partial数据不得参与“所有会议”“当前权威决策”等需要稳定全集或正式状态的Research。

## 可插拔点

```text
AuthorityReader
  - TranscriptReader
  - ArtifactReader
  - CurrentStateReader
  - StateTimelineReader

LexicalRetriever
  - PostgreSQL FTS
  - BM25 Provider
  - Exact / Entity / Identifier Search

EmbeddingProvider
  - 本地Embedding
  - API Embedding

VectorStore
  - pgvector
  - 其他向量库

GraphRetriever
  - Graphiti Projection
  - 其他可重建图投影

FusionStrategy
  - RRF
  - Weighted Fusion

Reranker
  - 本地Cross Encoder
  - API Reranker

AnswerabilityProvider
  - 规则与校准模型
  - NLI / Cross Encoder候选

AnswerGenerator
  - 确定性
  - LLM

CitationValidator
CoveragePolicy

QueryOrchestrator
  - Go确定性查询状态机（基线）
  - Go多阶段研究编排
  - Python LangGraph研究Provider（非权威、可关闭）

MemorySystemBaseline
  - Hindsight
  - Mem0
```

## 框架与模型放置

### 检索存储

- **PostgreSQL＋pgvector**：默认基线，适合当前权威数据、结构化过滤、FTS和向量共库研究。
- **OpenSearch或等价BM25引擎**：当中文Analyzer、BM25质量、索引规模、QPS或运维隔离有数据证明时加入。
- **Graphiti**：读取04可重建图投影做时态或关系候选，不能决定当前状态或绕过StateTimeline。
- **独立向量库**：只作为Provider对照；更换后不改变Search/Answer/Research合同。

### 本地Embedding与Reranker候选

| 候选 | 适合研究 | 注意事项 |
|---|---|---|
| Qwen3-Embedding-0.6B / Reranker-0.6B | 第一版低资源中文与多语言基线 | 指令模板、维度和量化必须固定 |
| Qwen3-Embedding-4B / Reranker-4B | 质量优先候选 | GPU、吞吐和P99成本更高 |
| Qwen3-Embedding-8B / Reranker-8B | 离线质量上界实验 | 不预设为在线默认 |
| BGE-M3 | Dense、Sparse、ColBERT多路线对照 | 三种表示的存储与延迟不同 |
| bge-reranker-v2-m3 | 轻量多语言Cross Encoder基线 | 必须在本项目中文会议qrels上验证 |

模型公开榜单只能用于筛选候选，不能代替MeetingRetrievalBench。模型大小、量化、最大长度、
Instruction、Embedding维度、Batch和硬件都进入Run Manifest。

### Memory与编排框架

- 完整项目清单、Star快照、License、第四模块边界和快速落地架构参见
  [开源 AI Memory 项目调研与 NotaRitmo 落地选型](../04-meeting-memory/OPEN_SOURCE_MEMORY_RESEARCH.md)。
- **Hindsight**：以完整Retain/Recall/Reflect系统作为05端到端实验基线，重点对比其语义、
  词法、图、时态召回和Rerank；Reflect输出不是04事实。
- **Mem0**：对比Agent/用户记忆召回、过滤和图记忆，不承担会议权威状态。
- **Supermemory**：复用连接器、多模态摄取、用户画像和通用RAG；自动更新与遗忘不能改变04正式事实。
- **Cognee**：作为图与向量一体化企业知识检索基线，评估其流水线、租户隔离和可观测能力。
- **Graphiti**：对比图关系、时间和Hybrid Retrieval净增益，读取可重建投影。
- **GraphRAG**：只用于离线全集主题与跨会议研究，不进入在线当前状态写入链路。
- **LangGraph**：对比开放式Research子问题规划和迭代工具调用，不掌握权限、预算和运行状态。
- **Agno / Letta**：属于Agent Runtime和产品壳候选，不作为检索权威或会议事实源。
- **RAGChecker/Ragas类工具**：只作为生成与检索诊断Provider，LLM Judge分数不是发布真相。
- **ir_measures**：统一计算qrels上的Recall、MRR、nDCG等确定性IR指标。

## 研究重点

- Query Type路由相对“所有问题统一Hybrid”的质量和延迟收益。
- 中文会议查询的分词、精确标识符、Embedding和Reranker选择。
- Segment、语义窗口、Artifact与Memory Projection多级召回的最佳组合。
- PostgreSQL FTS＋pgvector与真实BM25 Provider的净增益和运维成本。
- Meeting级聚合如何避免单个高分片段或长会议带偏会议定位。
- 跨会议问题如何拆分子问题并保证Meeting Set和必要维度覆盖。
- 全范围总结如何证明处理了全部授权会议，而不是只取热门Top-K。
- answerability阈值如何按查询类型用真实正负样本校准。
- 对话上下文如何帮助指代消解但不污染事实、Scope和权限。
- 旧决策、当前决策、Scope变化和冲突State如何生成可解释答案。
- 本地模型、外部API和确定性算法在质量、P99、资源、成本及隐私上的取舍。
- 引用文字、时间点、Transcript版本与音频播放状态的一致性自动验收。
- Index Generation、离线回放、Shadow流量、删除传播和灰度提升机制。

## 评测指标

| 评测面 | 核心指标 | 主要错误 |
|---|---|---|
| Meeting召回 | Recall@K、MRR、nDCG、Top-1 | 找错会议或正确会议排名过低 |
| Evidence召回 | Segment/Claim Recall@K、Claim Coverage | 找到会议但漏掉回答所需证据 |
| Meeting Set | Set Precision/Recall/F1、Coverage | 跨会问题漏会议或混入无关会议 |
| Rerank净增益 | Delta nDCG、Delta MRR、正确证据淘汰率 | Reranker把召回到的证据排掉 |
| Answer Claim | Precision、Recall、F1、Completeness | 答错、漏答或混入外部知识 |
| Grounding | Faithfulness、Unsupported Claim Rate | 结论没有Evidence Packet支持 |
| Citation | Support、Completeness、Span/Time Accuracy | 引用不支持结论或时间点错误 |
| Answerability | False Answer、False Refusal、Selective Risk | 无答案硬答或有答案拒答 |
| 当前状态 | Current State Exact Match | 使用旧决定、错误Scope或历史观点 |
| 双时态 | Valid/System-time Answer Accuracy | 混淆当时有效与系统当时所知 |
| 全集研究 | Meeting/Dimension Coverage、Partial Honesty | 漏会议却声称“全部” |
| 权限安全 | Cross-tenant/Restricted Leak Count | 检索、模型、日志或计数泄漏 |
| 新鲜度删除 | Stale Answer、Deleted Residue Count | 修订或删除后仍返回旧内容 |
| 系统性能 | P50/P95/P99、QPS、Token、Cost、Cache Hit | 质量提升但延迟或成本不可接受 |

引用音频可播放率作为产品SLO单独统计；Citation真实性不依赖播放服务瞬时健康。跨租户泄漏、
已删除内容复活、伪造Citation ID和正式Answer Claim无引用属于硬约束，目标必须为零。

## MeetingRetrievalBench

第五块必须能在不运行真实01、02、03、04、06的情况下，读取冻结的Transcript、Artifact、
Memory Snapshot、权限和媒体Fixture独立测试。

每个问题至少标注四层黄金数据：

```text
Meeting qrels
  哪些会议相关，0至3级相关度

Evidence qrels
  哪些Segment、Artifact、Observation、Claim或StateVersion支持答案

Answer Claim Gold
  期望原子结论、可接受表达、必须覆盖和不得出现的内容

Policy Gold
  可见范围、对外状态、应否拒答、删除与播放期望
```

查询切片必须包括：

- 会议标题、参与人、时间、项目和模糊会议定位。
- 指定Speaker原话、时间范围、数字、金额、日期、型号、简称和拼写变体。
- 单会事实、摘要、决策、行动项、风险、开放问题和人物观点。
- 当前状态、历史状态、迟到会议、Scope变化、旧决定替代和冲突。
- 跨会议比较、因果追问、行动项连续性、风险演变和Meeting Set覆盖。
- 全部会议总结、部分会议失败、空项目和超大会议集合。
- 明确无答案、主题相近但不可回答、证据互相矛盾。
- 全库存在但当前权限不可见、权限中途收紧、跨租户同名实体。
- Transcript、Artifact、Memory和索引版本不一致。
- 删除、Tombstone、播放服务故障和Embedding/Reranker/LLM降级。
- 多轮指代消解、恶意Prompt、要求越权扩大范围和伪造Citation。

数据集分层：

- **Smoke**：确定性短查询，用于每次提交的秒级回归。
- **Development**：用于Query Plan、索引、模型和阈值实验。
- **Calibration**：只用于answerability与置信度校准，不用于训练。
- **Locked Test**：开发期间不可见，用于版本验收。
- **Adversarial/Security**：权限、删除、注入、乱序、冲突和降级。

使用Oracle分解错误来源：

```text
真实Retriever + 真实Generator
Oracle Evidence + 真实Generator
真实Retriever + Oracle Answer Claims
```

这样可以区分答案失败来自召回、Rerank、覆盖、Answerability还是生成，而不是只看最终总分。
LLM Judge和RAGChecker可辅助诊断，Locked Test的关键结论需要确定性检查或人工复核。

具体准确率和P99目标必须在首版黄金集、无模型基线和本地模型基线完成后锁定。不能先写一组
没有数据依据的“95%”；一旦版本门槛锁定，本发布周期不得根据测试结果下调。

## 实施顺序

1. 同步04合同并冻结`SearchResult v1`、`QueryResult v1`、`ResearchResult v1`。
2. 冻结Query Type、Authorization Snapshot、Query Plan、Evidence和Answer Claim Schema。
3. 先建立MeetingRetrievalBench、qrels、Oracle实验和评测Runner。
4. 实现会议定位、精确原文、CurrentState和StateTimeline四条确定性基线。
5. 实现Index Generation、版本水位、权限预过滤、删除Tombstone和可重建索引。
6. 实现PostgreSQL FTS＋pgvector＋RRF基线，记录完整Candidate Ledger。
7. 分别对照Qwen3、BGE-M3、BM25 Provider和Cross Encoder，每次只改变一个变量。
8. 校准各Query Type的Answerability、Partial和Degraded状态。
9. 实现原子Answer Claim、Evidence Packet和Citation验证，再接可替换答案LLM。
10. 实现Meeting Set覆盖和全集Map/Reduce，再实现可恢复ResearchRun。
11. 最后以Shadow方式对照Graphiti、Hindsight、Mem0和LangGraph，测不到净增益即可关闭。

## 明确边界

- 不生成Transcript。
- 不修改Artifact。
- 不修改Observation、Claim或StateVersion当前状态。
- 不把聊天历史当成会议事实。
- 不在证据不足时强行回答。
- 不直接信任LLM生成的引用。
- 不绕过权限进行全库召回。
- 不把Top-K结果称为全部会议。
- 不把Answer Claim或Research推断直接写入04。
- 不允许向量库、图数据库、LangGraph、Hindsight或Mem0成为权限与事实权威。
- 不让播放服务临时失败改变事实证据真假。

## 完成标准

- 固定Search、Answer、Research三个合同及其版本、权限、覆盖和降级语义。
- 建立统一qrels、Answer Claim Gold、Policy Gold和可重复评测Runner。
- 所有检索阶段暴露原始分数、Rank、融合结果、淘汰原因和配置版本。
- answerability拥有独立负样本、Calibration集和按Query Type锁定的阈值。
- 单会、多会、当前状态、双时态、全集研究、无答案和无权限都有黄金问题。
- 所有正式Answer Claim完成逐结论引用、范围、时态和证据完整性验证。
- 全范围Research能证明Meeting Universe和必要维度覆盖，失败时诚实返回Partial。
- 跨租户泄漏、删除内容复活、伪造引用和无证据正式结论为零。
- Index Generation可原子切换、失效、重建并与权威源验证等价。
- 更换词法引擎、向量库、Embedding、Reranker、Answer LLM或Research Planner不改变产品合同。
- 禁用所有Python模型、图和Agent Memory框架后，确定性搜索、权威State查询和证据浏览仍可工作。

## 研究参考

- [PostgreSQL Text Search](https://www.postgresql.org/docs/current/textsearch-controls.html)：原生FTS查询和排名。
- [pgvector](https://github.com/pgvector/pgvector)：PostgreSQL向量检索、过滤和Iterative Scan。
- [OpenSearch Hybrid Search](https://docs.opensearch.org/latest/vector-search/ai-search/hybrid-search/index/)：BM25与向量混合检索候选。
- [Qwen3 Embedding](https://github.com/QwenLM/Qwen3-Embedding)：多尺寸Embedding与Reranker候选。
- [BGE-M3](https://huggingface.co/BAAI/bge-m3)：Dense、Sparse与Multi-vector对照。
- [Graphiti](https://github.com/getzep/graphiti)：时态图与Hybrid Retrieval候选。
- [Hindsight](https://github.com/vectorize-io/hindsight)：Retain、Recall、Reflect与端到端Memory检索基线。
- [Mem0](https://github.com/mem0ai/mem0)：Agent和用户记忆实验基线。
- [LangGraph Agentic RAG](https://docs.langchain.com/oss/python/langgraph/agentic-rag)：Research Planner实验参考。
- [ir_measures](https://github.com/terrierteam/ir_measures)：标准qrels评测指标。
- [RAGChecker](https://github.com/amazon-science/RAGChecker)：Claim级Retriever与Generator诊断。
- [LongMemEval](https://arxiv.org/abs/2410.10813)：跨会话、时态更新和拒答问题设计参考。
