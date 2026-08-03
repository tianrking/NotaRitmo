# 04 会议记忆架构决策

本文冻结 04「跨会议记忆」与 03、05、横向 LLM Provider 的职责边界。它是研究期和生产化阶段的共同判定依据，不把实验组件的存在误认为生产能力。

## 决策总表

| 能力 | 生产决定 | 研究期可选项 | 说明 |
| --- | --- | --- | --- |
| 03 单会议 LLM 结构化抽取 | 推荐启用；必须经过 Schema、证据和租户校验 | 可关闭，使用 FixtureRuleExtractor、规则或人工导入 | LLM 只产出候选，不能直接写当前记忆 |
| 04 Claim Ledger | 多用户生产必选 PostgreSQL | InMemory、SQLite 仅用于本地开发、固定 Fixture 和适配器回归 | PostgreSQL 保存 Observation、Claim、StateVersion、证据、权限和审核状态 |
| pgvector 语义召回 | 不是数据真相的硬依赖，但跨会议自然语言问题推荐启用 | 关闭时由 FTS/词法检索提供可解释 fallback | 向量可删除、可重建，不能覆盖 Claim 状态 |
| 真实 LLM Loop 评估 | 研发发布门禁必做 | 业务运行时可以通过配置关闭，回到确定性抽取/模板回答 | 评估通过前不能宣称模型质量或默认开启 |
| llm-providers | 横向基础设施，供 03/04/05 复用 | Fixture Replay、静态 Provider、SaaS/兼容接口适配器 | 不是第七个业务模块；不拥有事实、权限或状态 |

## 权威处理流程

上游只需要提供通过合同校验的 TranscriptBundle；04 不负责 ASR、说话人分离或客户端。

    TranscriptBundle
      -> 03 单会议理解（可用 LLM；也可离线关闭）
      -> MeetingArtifactBundle + evidence_segment_ids
      -> Candidate Observation / Candidate Claim
      -> Go Schema、证据、租户、权限、时间和幂等校验
      -> Memory Promotion Policy
      -> PostgreSQL Claim Ledger（生产权威）
      -> StateSlot / StateVersion / supports / supersedes / contradicts
      -> 可重建 FTS、pgvector、Graphiti 等投影
      -> 05 Hybrid RAG 召回与重排
      -> no-answer 策略 + 证据引用 + 当前/历史状态回答

不满足证据、权限或 Schema 的模型结果只能停留在候选/人工审核队列，不能污染 MemorySnapshot。原始 Transcript、Artifact 和已审核 Claim 不能因模型重跑而覆盖。

## 生产必选边界

### 03：结构化抽取

生产推荐使用 LLM 统一提取摘要、事实、决策、行动项、风险、开放问题和 Claim 候选；请求必须带：

- tenant_id、meeting_id、schema_version
- Prompt、模型和 Provider 版本
- 输入哈希、Token、成本、延迟和错误元数据
- 每个结论对应的 evidence_segment_ids

03 可以在没有外部模型凭证时关闭 LLM，使用规则、固定 Artifact 或人工结果继续验证 04/05。关闭 LLM 不等于允许没有证据的自由文本直接写入长期记忆。

### 04：PostgreSQL Claim Ledger

面向多用户的生产系统必须以 PostgreSQL 作为唯一权威写入入口。至少需要：

- Observation、Entity、StateSlot、Claim、StateVersion、Evidence、审核和删除记录。
- 每条权威记录带 tenant_id，应用授权之外启用 PostgreSQL RLS/强制 RLS。
- 唯一键、外键、乐观锁、事务和 Outbox 保证幂等、并发和变更传播。
- 保留旧 Claim 和完整双时态历史；新值通过 supersedes 或 contradicts 关联，不能物理覆盖。
- 向量、全文和关系图都是投影，失败后可从 Claim Ledger 重建。

InMemory 和 SQLite 不承担多用户生产安全、跨进程并发或灾备职责；它们只证明 Repository 契约可替换。

### 05：Hybrid RAG 与 pgvector

跨会议问题通常包含同义表达、因果和历史变化，生产推荐同时保留：

    PostgreSQL FTS / lexical
      + pgvector embedding
      -> 分数融合
      -> 可选 reranker
      -> Claim/segment 候选
      -> evidence/no-answer policy

pgvector 可以关闭，系统仍必须保留 FTS/词法 fallback，以便离线运行、精确术语查询和向量服务故障时降级。无论是否启用向量，召回结果都必须重新通过租户、状态、证据和引用可播放性校验。

### LLM Loop 研发门禁

真实 SaaS LLM 或用户 OpenAI-compatible endpoint 接入前，必须在固定 Fixture/Gold 上记录：

- 单会议抽取 Precision、Recall、证据绑定率。
- Claim 抽取 Precision、Recall、实体归并和当前状态准确率。
- Recall@K、MRR/nDCG、会议定位、跨会议问题准确率。
- no-answer 拒答率、引用可播放率、旧决策被新决策替代准确率。
- 删除残留率、跨租户泄漏率、延迟、Token、成本和失败重试。

这些评估是研发发布门禁，不能用 Fixture Replay 的 100% 当作真实模型质量。业务运行时可以把 LLM Loop 关闭，使用确定性 fallback；关闭时输出必须标注实现模式和模型元数据。

## 横向 llm-providers 边界

llm-providers/ 只统一请求、响应、Schema、输入哈希、Prompt/模型版本、Token/成本、超时、重试、缓存和脱敏元数据。它可以适配：

- 离线 Fixture Replay/Static Provider。
- 外部 SaaS。
- 用户自建的 OpenAI-compatible HTTP endpoint。
- 将来的其他协议适配器。

它不负责：

- 选择哪条 Claim 成为当前有效。
- 判断用户是否有权看到某段证据。
- 写 PostgreSQL 权威表。
- 绕过 no-answer 或删除策略。
- 对 Android、Linux 或 Web 暴露产品 API。

因此它是横向基础设施，不改变六个业务模块的编号和依赖方向。

## 验收门槛

一个 04/05 组合只有同时满足下列条件，才可称为可生产候选：

1. 所有 Artifact、Claim、Evidence 和状态变更通过版本化 Schema；每条答案引用可定位到同租户的 meeting_id/segment_id/speaker_id/start_ms/end_ms。
2. 同一 StateSlot 最多一个当前有效版本；历史版本不可变，supersedes/contradicts 有证据、时间和权限依据。
3. 任何查询先租户过滤，再召回、重排和答案生成；跨租户泄漏率必须为零。
4. 无足够证据时返回 no_answer，不得用 LLM 常识补全；拒答样本和阈值有固定回归测试。
5. FTS 可独立运行；pgvector、reranker、图投影和 LLM 关闭时，系统仍能启动并返回可解释降级结果。
6. 重试、重复导入、模型重跑和投影重建不产生重复 Claim 或丢失历史。
7. 固定 Fixture 的质量指标不能低于已登记基线；真实 LLM Loop 必须有独立报告和成本记录。
8. 删除、权限撤销和租户隔离有端到端回归；权威表、缓存、向量、全文和图投影无残留。

## 当前实现与缺口

当前仓库已经包含 04 的 Python 研究基线和适配器：

- baseline/：FixtureRuleExtractor、MemoryStore、MeetingMemoryService，以及 Extractor、Repository、Retriever、Answerer、LLMProvider 协议。
- baseline/sqlite_repository.py：标准库 SQLite 本地 Repository，验证业务层不依赖 Python 字典或某一个数据库。
- baseline/hybrid_retrievers.py：可注入 secondary Retriever 的词法融合基线；尚未实现真正 Embedding/pgvector。
- baseline/llm.py 与 answerers.py：Offline/Static Provider 和受证据约束的可选答案 Provider，默认不联网。
- 固定 Fixture、离线评测、当前/历史状态、证据、no-answer 和租户隔离测试。

仍然缺少或未达到生产门槛：

- Go 权威 Memory Service 和 PostgreSQL Claim Ledger/RLS。
- 真实 PostgreSQL FTS + pgvector、Embedding、Reranker 和删除重建流程。
- 真实 SaaS LLM 的质量、费用、重试和回放报告。
- 多进程并发、Temporal、HTTP API、认证、审计和对象存储播放链路。
- 真实 ASR 误差对证据、Speaker 和时间戳的端到端影响。

因此当前状态是：04 已有可运行、可评测、可插拔的 Python 研究基线；生产必选的 Go/PostgreSQL/多用户能力仍是明确缺口，不能把本地基线描述成完整生产服务。
