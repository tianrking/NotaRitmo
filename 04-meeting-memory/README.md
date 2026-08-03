# ④ 跨会议记忆 Meeting Memory

## 一句话定位

这一块才是会议Memory，但它不负责聊天。

它回答：

> 系统应该记住什么、信息来自哪里、什么目前有效、后来发生了什么变化。

它不是聊天历史、向量数据库、跨会议搜索或一个直接回答问题的Agent。它把多场会议产生的
证据化Artifact维护成可追溯、可纠错、带时间、权限和当前状态的组织记忆。自然语言检索、
跨会议总结和最终答案属于05模块。

开源 Memory 生态的功能对比、选型结论、快速上线方案和与六个模块的组合方式，参见
[开源 AI Memory 项目调研与 NotaRitmo 落地选型](OPEN_SOURCE_MEMORY_RESEARCH.md)。调研结论是
复用一个主 Memory Provider 承接通用能力，由本模块保留一个薄的审核、证据、版本、权限和
当前状态控制面，而不是从零重写完整 Memory 平台。

## LLM 提取与规则约束边界

Mem0 的 `infer=true` 可以把输入的 Transcript 或 Artifact 交给配置的 LLM，提取候选
Memory，再进行 Embedding、向量存储和召回；`infer=false` 则绕过生成式 LLM，直接保存调用方
提供的文本或 Claim。这里的“提取”是记忆形成，不是 ASR，也不是完整会议摘要。

必须明确：Mem0 的自定义 Prompt、`custom_instructions` 和模型输出格式属于**软约束**。它们能
引导模型提取“正式决定、行动项、负责人、截止时间和风险”，但不能像数据库约束或编译器一样
保证每次都遵守。LLM 仍可能漏提、误归类、丢失时间点或把建议写成事实；不同模型、版本和
上下文长度也会改变结果。

因此本模块禁止把 Mem0 或任意 LLM 的输出直接写入当前有效状态。正式流程必须是：

```text
Transcript / MeetingArtifactBundle
  -> LLM 结构化抽取
  -> CandidateClaim / CandidateState
  -> Schema、字段、租户和证据校验
  -> 人工审核或明确 Promotion Policy
  -> PostgreSQL Observation / Claim / StateVersion
  -> Mem0、pgvector、FTS、Graphiti 等可重建投影
```

硬约束由 Go + PostgreSQL 实现，而不是由 Prompt 承担：

- Schema、枚举、必填字段、时间区间和 `evidence_id` 合法性。
- `tenant_id`、来源权限、删除传播和按用户授权。
- `source_key/claim_id` 幂等、唯一约束和并发版本。
- `supports`、`supersedes`、`contradicts` 的时间与 Scope 规则。
- 当前状态快照、历史时间线、审核状态和回滚。

没有证据的模型输出只能进入候选或人工队列；不能进入 `MemorySnapshot`。更换 LLM 或重新运行
提取时，原始 Transcript、Artifact 和已审核 Claim 必须保留，不能把模型重跑当成事实覆盖。

这意味着 Memory Formation 和 Memory Retrieval 必须分开评测：前者测 LLM 按 Schema 提取事实
的质量，后者在固定 Gold Claim 上测召回、过滤、时态和删除。Mem0 可以关闭、替换或从
PostgreSQL 权威数据重建，不是本模块的事实权威。

本模块区分四类信息：

```text
Episodic Observation
  某场会议在某个时间产生了什么有证据的语义记录

Semantic Claim
  多种表达归一化后形成的命题

Temporal State
  决策、行动、风险和问题在指定范围与时间点的状态

Derived Memory View
  当前快照、历史时间线和项目状态视图
```

## 实现语言与运行边界

### 语言结论

本模块的权威实现必须使用 Go。PostgreSQL 保存权威事实；Python 只允许作为实体归并、关系
发现和图实验的候选 Provider：

```text
Go Memory Service
├── Memory Promotion Policy
├── Observation Ledger
├── StateSlot / Claim Registry
├── Decision / Action / Risk / Question State
├── Bitemporal Validity
├── Entity Registry
├── Evidence Validation
├── Supersede / Contradict Rules
├── Tenant / ACL / Deletion Propagation
├── PostgreSQL Transactions
└── Projection Rebuild
                 │
                 ▼
Optional Python Candidate Services
├── Entity Resolution Candidate
├── Contradiction Candidate
├── Relation Candidate
├── Graphiti Experiment
└── Mem0 / Hindsight Experiment
```

Go 负责：

- 按Memory Promotion Policy决定哪些单会议Artifact有资格进入长期记忆。
- 把被接纳的Artifact版本转换为不可变Observation，再形成候选Claim和状态变更。
- 管理实体注册表、规范名称、别名、租户边界和合并历史。
- 管理StateSlot，识别“同一主体、谓词和适用范围下的不同历史值”。
- 校验每条Observation、Claim和状态变化的Artifact、Transcript、Segment、时间点和媒体证据。
- 分开管理审核状态、证据状态、时间有效性和新鲜度，不使用单字段混合表达。
- 实现Decision、Action、Risk和Question四类业务状态机。
- 判定并写入 `supports`、`supersedes`、`contradicts` 和 `follows_up`。
- 同时管理业务有效时间、系统记录时间和会议断言时间，保留完整变更历史。
- 使用 PostgreSQL 事务、唯一约束、乐观锁和 Outbox 发布一致变更。
- 管理人工批准、拒绝、纠错、回滚、来源权限、删除传播、审计和保留期。
- 生成权威`MemorySnapshot`与`StateTimeline`。
- 从权威数据重建向量、全文和图投影。

Python 候选 Provider 可以负责：

- 实体相似度、别名、同义词和跨会议实体合并候选。
- StateSlot候选、新旧Claim相似、支持、冲突和替代关系候选。
- Graphiti时态图与关系发现对照实验。
- Mem0、Hindsight或其他Agent Memory项目的Shadow实验。
- 候选关系的解释、分数、模型版本和离线评测。

Python 候选 Provider 必须返回类似：

```json
{
  "candidate_type": "supersedes",
  "source_claim_id": "claim_kotlin",
  "target_claim_id": "claim_flutter",
  "confidence": 0.91,
  "evidence_ids": ["seg_018"],
  "producer_version": "relation-model-v1"
}
```

该响应只是候选。Go 必须再次验证租户、实体、证据、时间、规则和当前状态，才能形成
`MemoryChangeSet`。

Python、Graphiti、Neo4j、Mem0 和 Hindsight 禁止：

- 成为当前有效事实的唯一权威源。
- 未经 Go 服务直接改变 Claim 状态。
- 通过图距离、Embedding 相似度或 LLM 判断覆盖 PostgreSQL 权威状态。
- 绕过租户、权限、人工确认、审计和删除传播。
- 直接回答用户自然语言问题。
- 把聊天历史静默升级为会议事实。
- 把`Reflect`、摘要或模型推测静默升级为组织事实。
- 在没有可逆记录的情况下直接合并或删除实体。

### 存储与部署

- PostgreSQL 是 Observation、Entity、StateSlot、Claim、StateVersion、审核、权限和版本的权威存储。
- PostgreSQL使用时间范围、排他约束、唯一约束、外键和事务维护硬不变量。
- 每张权威表包含`tenant_id`，应用鉴权之外使用Row-Level Security进行纵深防御。
- 正式服务连接不得使用表Owner或`BYPASSRLS`角色；关键表启用`FORCE ROW LEVEL SECURITY`。
- Neo4j 或其他图数据库只保存可重建关系投影和候选边。
- pgvector 只保存可重建向量投影。
- Go Memory Service 是唯一正式写入入口。
- Python 候选服务按需部署，可以完全关闭而不影响确定性 Memory 状态机运行。
- 图或向量投影失败时，权威 Memory 仍保持完整，并通过重建任务恢复。

## 输入

- 指定版本且通过03质量门禁的单会议`MeetingArtifactBundle`。
- 原始证据引用。
- 会议时间。
- 项目和组织信息。
- 人员与Speaker确认结果。
- 用户人工修订。
- 删除和权限变更事件。

03的所有产物不会自动进入Memory。默认接纳策略：

| 03产物 | 04处理方式 |
| --- | --- |
| 正式决策 | 必须生成Decision候选 |
| 行动项 | 生成独立Action State候选 |
| 风险 | 生成Risk State候选 |
| 开放问题 | 生成Question State候选 |
| 稳定项目事实 | 根据证据、范围和新颖性生成Claim候选 |
| Speaker个人观点 | 保存为带归属Observation，不自动成为组织事实 |
| 摘要、章节、热词、词云、思维导图 | 不进入权威Memory |
| LLM问答或聊天结果 | 默认不进入；用户明确保存时仍作为独立来源类型审核 |

Memory Promotion Policy至少检查：

```text
artifact_type
evidence_status
explicitness
scope
durability
novelty
source_authority
permission
retention_policy
```

Promotion失败不代表03分析失败，只表示该产物不应污染长期记忆。

## 写入输出：MemoryChangeSet

```json
{
  "meeting_id": "meeting_xxx",
  "schema_version": "memory-change-set-v1",
  "idempotency_key": "tenant/artifact/version/importer",
  "created_observations": [
    {
      "observation_id": "obs_xxx",
      "artifact_id": "artifact_xxx",
      "artifact_version": 3,
      "asserted_at": "2026-07-20T10:30:00Z",
      "evidence_ids": ["seg_018"]
    }
  ],
  "created_claims": [
    {
      "claim_id": "claim_kotlin",
      "state_slot_id": "android/development-framework/release-v1",
      "value": "原生Kotlin",
      "review_state": "human_approved",
      "evidence_state": "supported",
      "valid_from": "2026-07-20",
      "evidence_ids": ["seg_018"]
    }
  ],
  "relations": [
    {
      "source": "claim_kotlin",
      "type": "supersedes",
      "target": "claim_flutter"
    }
  ],
  "projection_events": ["memory_projection_xxx"]
}
```

## 读取输出：MemorySnapshot 与 StateTimeline

```json
{
  "schema_version": "memory-snapshot-v1",
  "tenant_id": "tenant_xxx",
  "scope": {"project_id": "android"},
  "as_of_valid_time": "2026-07-28T12:00:00Z",
  "as_of_system_time": "2026-07-28T12:05:00Z",
  "current_state_versions": ["state_version_kotlin"],
  "disputed_claims": [],
  "latest_change_id": "change_xxx"
}
```

`MemorySnapshot`回答指定范围和时间点什么当前有效；`StateTimeline`返回一个StateSlot中
候选、接受、冲突、修订、替代、撤回以及每次变化的证据。读取结果不能只有最终文本，
必须保留StateSlot ID、Claim ID、StateVersion ID、双时态、状态和证据。

## 五类权威核心数据

### Observation：不可变会议观察

Observation记录“指定会议Artifact版本表达了什么”，是Artifact进入Memory后的不可变摄取记录：

```json
{
  "observation_id": "obs_xxx",
  "tenant_id": "tenant_xxx",
  "meeting_id": "meeting_xxx",
  "artifact_id": "artifact_xxx",
  "artifact_version": 3,
  "artifact_type": "decision",
  "asserted_at": "2026-07-20T10:30:00Z",
  "ingested_at": "2026-07-28T12:00:00Z",
  "evidence_ids": ["seg_018"],
  "source_acl_id": "acl_xxx"
}
```

重跑03产生新Artifact版本时创建新Observation，并通过变更关系标记旧Observation，不物理覆盖。

### Entity：规范实体

Entity表示人、组织、项目、产品、版本、客户、型号等稳定对象。实体归并必须：

- 保存规范名称、别名、来源、租户、版本和审核记录。
- 区分Speaker候选与已确认Person。
- 支持错误合并后的可逆拆分。
- 通过映射关系归并，不破坏原始Observation。
- tenant之间不自动共享实体，即使名称和Embedding相同。

### StateSlot：可变化状态槽位

StateSlot由`subject + predicate + normalized_scope`组成，表示一类可以随时间变化的业务状态：

```json
{
  "state_slot_id": "slot_android_framework_v1",
  "subject_entity_id": "entity_android",
  "predicate": "development_framework",
  "scope": {
    "release": "v1"
  },
  "scope_hash": "..."
}
```

`object/value`不能进入StateSlot Key。Flutter和Kotlin是同一槽位的不同时期值；如果把值放进
Key，系统将无法可靠判断替代关系。不同发布版本、客户、地域和环境的Scope必须允许并存。

### Claim：规范命题

```json
{
  "claim_id": "claim_kotlin",
  "tenant_id": "tenant_xxx",
  "state_slot_id": "slot_android_framework_v1",
  "kind": "decision",
  "value": "原生Kotlin",
  "polarity": "positive",
  "modality": "decided",
  "review_state": "human_approved",
  "evidence_state": "supported",
  "confidence": 0.95,
  "confidence_calibration_version": "memory-relation-calibration-v1",
  "version": 2
}
```

Claim表达归一化命题；Observation保存具体来源。一个Claim可以有多个独立Observation支持，
删除一个来源时不能错误删除仍有其他有效证据的Claim。

### StateVersion：双时态版本

每个StateVersion至少维护：

```text
valid_time
  业务世界中的有效区间

system_time
  权威系统从何时到何时采用这一版本

asserted_at
  来源会议中何时表达，不替代上述两个时间轴
```

例如旧会议延迟导入：

```text
asserted_at = 2026-01-10
valid_from = 2026-01-15
system_from = 2026-07-01
```

从而分别回答“当时实际有效什么”“系统当时知道什么”和“系统现在回看认为当时是什么”。
未知业务生效时间可以使用会议时间作为受控回退，但必须记录`valid_time_inferred=true`。

## 完整功能点

### 记忆写入

- 先把被Promotion接受的Artifact转换为不可变Observation。
- 将稳定项目断言转换为Claim候选。
- 将决策转换为Decision State候选。
- 将行动项转换为Action State候选，不强行压成普通三元组。
- 将风险转换为Risk State候选。
- 将开放问题转换为Question State候选。
- 将主题和项目对象建立关联。
- 每个Claim和状态变化通过Observation绑定会议、Artifact和Segment证据。
- 只接受证据校验通过的正式数据。
- 无证据内容进入候选区，不直接成为事实。
- Artifact重算、人工修订和模型升级必须产生可审计差异，不静默覆盖既有Memory。
- 幂等键至少包含`tenant_id + artifact_id + artifact_version + importer_version`。

### 实体归并

- 人名和别名。
- 公司和组织。
- 项目和子项目。
- 产品和版本。
- 型号和缩写。
- 同名不同实体区分。
- 跨会议实体候选。
- 用户确认合并或拆分。
- 实体别名历史。
- 归并决策版本和可逆映射。
- False Merge和False Split进入独立评测。
- tenant之间绝不共享实体。

### Claim归一化

- 主体。
- 谓词。
- 值、极性和模态。
- 业务范围。
- 适用版本。
- 地域或客户范围。
- 生效时间。
- 会议断言时间、业务有效时间和系统记录时间。
- 稳定StateSlot Key。
- 独立Claim ID和Observation ID。
- 同一命题的多个表达归并。
- 同一StateSlot中的不同值进入关系判定，不依靠全文向量搜索决定状态。

### 关系

- `supports`：支持或补充已有Claim。
- `supersedes`：新决定替代旧决定。
- `contradicts`：两条Claim相互冲突。
- `amends`：新Claim修改旧Claim的一部分。
- `narrows_scope`：仅缩小适用范围，不全局替代。
- `follows_up`：后续会议继续处理。
- `resolves`：解决风险或开放问题。
- `reopens`：重新打开已完成行动项或已解决问题。
- `blocks` / `depends_on`：行动项和风险依赖。
- `related_to`：只作为可重建发现投影，不改变权威状态。
- `derived_from`：从其他事实推导。
- 每条关系都保存证据和算法版本。
- `contradicts`通常对称，`supersedes`、`amends`和`follows_up`有方向。
- Speaker观点冲突不自动等于组织决策冲突；只有符合来源权威和状态规则的Artifact才能改变当前状态。

### 时态和版本

- 当前有效Claim。
- 指定时间点有效Claim。
- 指定系统记录时间点的Memory视图。
- 旧决策。
- 新决策。
- 生效与失效时间。
- 会议断言时间、业务有效时间和系统记录时间分离。
- 延迟导入旧会议后的时间线重算。
- 决策变更历史。
- 行动项延期、完成、取消和重新打开。
- 项目连续状态。
- 乱序导入后必须收敛到与按事件时间顺序导入一致的结果。

### 正交状态维度

```text
review_state
  candidate -> auto_approved / human_approved / rejected

evidence_state
  supported / disputed / insufficient / retracted

temporal_position
  future / current / historical / expired

freshness
  fresh / aging / stale
```

`current`由审核、证据、有效区间和Scope共同计算，不作为可以被模型随意写入的单一状态。
`superseded`体现为方向关系和旧StateVersion有效区间结束；`stale`只是新鲜度，不代表内容错误；
`disputed`也不自动代表失效。

### 四类业务状态机

```text
DecisionState
  PROPOSED -> TENTATIVE -> ACCEPTED -> AMENDED / SUPERSEDED / REVOKED

ActionState
  OPEN -> IN_PROGRESS -> BLOCKED -> DONE / CANCELLED
                                  DONE -> REOPENED

RiskState
  IDENTIFIED -> ACCEPTED -> MITIGATING -> RESOLVED / MATERIALIZED

QuestionState
  OPEN -> PARTIALLY_ANSWERED -> ANSWERED / DEFERRED
                             ANSWERED -> REOPENED
```

四类状态共享Entity、Observation、Evidence、双时态和审核机制，但保留各自的业务不变量。

### 人工确认

- 确认新旧决策替代。
- 拒绝错误关系。
- 确认实体归并。
- 拆分错误实体。
- 修正Claim结构。
- 标记冲突已解决。
- 所有人工操作保留审计。
- 人工确认优先于自动判断。
- 人工确认改变的是指定版本和Scope，不允许无范围地覆盖整个项目历史。
- 人工修正形成黄金数据候选，但必须经过授权、脱敏和数据版本管理。

### 删除、权限和隐私

- tenant隔离。
- 用户和项目范围。
- 每条Observation保存来源ACL，Claim保存所有来源和可见范围推导结果。
- 多来源派生Memory默认采用不弱于最严格来源的权限。
- 不得通过“存在一条隐藏证据”或统计数量泄漏受限会议信息。
- 删除会议。
- 删除音频。
- 删除Person和声纹。
- 删除证据后重新计算Claim支持数、状态、关系和可见范围。
- 一个Claim仍有其他独立有效证据时只移除对应支持，不错误删除整个Claim。
- 最后一条有效证据删除后，Claim必须撤销、隐藏或进入人工队列。
- 清理向量索引。
- 清理图投影。
- 清理缓存。
- 保存不含原始敏感内容的删除墓碑和重建水位，防止投影重建时复活已删除内容。
- 删除传播覆盖异步任务、导出、副本和备份保留策略。
- 导出某个用户或租户的全部Memory。

## 权威数据和投影

推荐边界：

```text
权威事实和版本
  - PostgreSQL
  - Observation、Entity、StateSlot、Claim和StateVersion

语义召回投影
  - pgvector
  - PostgreSQL FTS或其他可重建全文索引

关系发现和图遍历
  - Neo4j
  - Graphiti

主要归属05的实验型Agent Memory Provider
  - Mem0
  - Hindsight
```

Graphiti最接近本模块的时态图与来源追踪需求，但仍作为Shadow Projection和候选关系Provider，
不能成为事实源。Mem0主要面向用户、Session和Agent记忆；Hindsight的Recall与Reflect主要属于
05检索研究。二者在04只参与Shadow摄取和候选发现实验，不能绕过统一Observation、Claim、
证据、时态、权限和删除机制。任何Reflect或Mental Model输出都只能作为可重建Derived Insight。

## 关系判定流程

```text
新Artifact版本
  -> Memory Promotion
  -> 不可变Observation
  -> 实体和StateSlot候选归一化
  -> Claim或业务状态候选
  -> 召回同StateSlot或同实体历史
  -> 规则、NLI或LLM关系分类
  -> Scope、来源权威、证据、时态和权限硬约束
  -> 自动确认或人工审核
  -> PostgreSQL事务写入Observation、关系和StateVersion
  -> Outbox发布可重建投影事件
```

关键词、Jaccard、图距离和向量相似度只能用于候选召回，不能单独决定`supersedes`。
文本冲突也不等于状态替代；新Artifact必须表达同一StateSlot、兼容Scope和足够来源权威，
并且其业务状态允许改变当前值。

## 数据所有权

本模块权威拥有：

- Canonical Entity、别名、归并、拆分和消歧审核记录。
- 不可变Observation和Artifact摄取版本。
- StateSlot、Claim、四类业务状态、有效时间、记录时间、来源、证据和版本。
- `supports`、`supersedes`、`contradicts`、`follows_up` 等经校验关系。
- 当前有效视图、历史时间线、冲突队列和人工确认结果。
- 来源ACL推导、删除、撤销、重算和投影构建水位。

本模块不拥有单会摘要、逐字稿、向量搜索结果、聊天历史和最终自然语言答案。图数据库、
向量索引和记忆框架中的节点只是投影；权威 Claim 与实体状态必须能够不依赖这些投影恢复。

## 命令、查询与事件

写入命令：

```text
PromoteArtifacts
ImportObservations
ResolveEntity
ResolveStateSlot
ConfirmMemoryCandidate
RejectMemoryCandidate
RecomputeMeetingMemory
ApplyMemoryCorrection
DeleteMeetingMemory
RebuildMemoryProjection
```

读取查询：

```text
GetCurrentState
GetStateAsOfValidTime
GetStateAsOfSystemTime
GetStateTimeline
GetObservation
GetEntity
GetOpenConflicts
GetMemorySnapshot
```

事件：

```text
ObservationImported
MemoryCandidateRaised
StateVersionActivated
StateVersionClosed
ClaimDisputed
EntityResolved
MemoryCorrectionRequired
MemorySourceDeleted
MemoryProjectionInvalidated
MemoryDeleted
```

`MemoryChangeSet` 是一次写入结果，不是 Memory 的唯一读取合同。消费者读取
`CurrentStateView`、`StateTimeline` 或 `MemorySnapshot`，并得到业务状态、审核状态、
证据状态、有效时间、记录时间、版本、权限和证据。

## 双时态与硬不变量

每个正式 StateVersion 至少维护：

- **valid_time**：这项状态在业务世界中从何时到何时有效。
- **system_time**：系统从何时到何时把这个版本视为已知记录。
- **asserted_at**：来源在什么时候表达了这项内容。

例如7月25日导入一场7月10日旧会议，发现7月10日至7月18日之间曾经采用Flutter：

```text
valid_time  = [7月10日, 7月18日)
system_time = [7月25日, ...)
asserted_at = 7月10日会议中的发言时间
```

因此不能用`created_at`代替业务有效时间，也不能因为晚导入旧会议而错误覆盖当前状态。

必须由数据库约束或同等强度的事务逻辑保证：

- 同一`tenant_id + state_slot_id + exclusive_scope`不能存在两个重叠的当前有效版本。
- 未通过审核门槛或证据门槛的候选不能进入正式当前视图。
- 每个正式版本至少可追溯到一个仍然有效且用户有权访问的Observation和原文证据。
- 历史版本不可原地覆盖；修正必须产生新版本并关闭旧`system_time`。
- 相同输入集合无论按什么顺序到达，最终状态必须收敛一致。
- 同一幂等键只能产生一个逻辑ChangeSet。
- 并发更新使用可串行化事务重试、悲观锁或带版本号的乐观锁，不允许静默丢失更新。

PostgreSQL实现时优先使用`tstzrange`、排斥约束、唯一约束、外键和事务内校验。
仅靠应用层`SELECT`后再`INSERT`不能可靠阻止并发重叠。

## 依赖规则

- 只消费达到约定质量级别的、带版本的`MeetingArtifactBundle`、有效证据引用和授权元数据。
- 摘要、章节、热词、词云和思维导图属于Derived View，默认不得直接提升为权威Memory。
- 可以读取 Transcript 证据做验证，但不能修订 Transcript 或 Artifact。
- 实体归并、关系发现、图遍历和记忆框架都通过候选 Provider 参与。
- 候选Provider只能返回带理由、置信度和来源的Proposal，不能直接写状态表。
- 只有本模块能改变权威Memory状态；产品模块只能提交经过鉴权的审核命令。
- Retrieval只读本模块公开的授权视图，不能通过向量或图投影反写权威事实。
- 图、向量、缓存和实验Memory均为可重建投影，不得向PostgreSQL权威表回写“真相”。

## 错误分类

- Artifact 或证据不存在、租户不匹配、版本过期：拒绝写入。
- 内容未通过Promotion Policy：返回结构化拒绝原因，不视为基础设施失败。
- 同一幂等键重复提交：返回既有 ChangeSet。
- 同一StateSlot并发修订：事务重试或版本冲突，不能覆盖其他写入。
- StateSlot或Scope不能唯一判定：进入人工队列，不猜测归并。
- 实体或关系置信度不足：进入候选或人工队列，不视为基础设施失败。
- 权限推导失败：不得发布该Memory视图。
- 图、向量或缓存投影失败：权威提交可成功，但标记投影过期并通过Outbox重建。
- 删除投影传播失败：权威删除墓碑先阻断所有读取，残留投影进入高优先级清理队列。
- 权威数据库提交失败：整体失败，不能发布任何已提交事件。

## 实时与离线边界

- 默认只接收基于最终 Transcript 的正式 Artifact。
- 会中候选可进入隔离的 ephemeral 空间，用于提醒，不影响当前有效视图。
- 会后最终产物到达时重新进行实体归并、关系判定和时态更新。
- 被人工确认的紧急实时决定可以进入正式状态，但必须保留确认人、时间和原始证据。

## 可插拔点

```text
MemoryPromotionPolicy
ObservationImporter
EntityResolver
StateSlotResolver
ClaimNormalizer
RelationClassifier
DecisionStateEngine
ActionStateEngine
RiskStateEngine
QuestionStateEngine
ACLResolver
DeletionPropagation
ProjectionProvider
MemoryExperimentProvider
HumanReviewPolicy
```

## 明确边界

- 不调用ASR。
- 不生成单会议摘要。
- 不把摘要、聊天回答或模型反思直接提升成事实。
- 不负责通用聊天机器人的个人偏好记忆。
- 不负责用户查询排序。
- 不生成最终自然语言答案。
- 不把向量最近邻直接当成事实。
- 不自动覆盖存在冲突或Scope不兼容的旧Claim。
- 不做不可逆的实体合并。
- 不允许图数据库成为唯一事实来源。

## 研究重点

- Promotion Policy怎样在召回率和Memory污染率之间取平衡。
- Entity、StateSlot和Scope怎样归一化而不错误合并。
- `supports`、`supersedes`、`contradicts`、`amends`、`narrows_scope`怎样判定。
- 乱序导入、迟到证据和历史修正能否收敛到同一双时态结果。
- Decision、Action、Risk、Question四种业务对象是否需要不同状态机和晋升规则。
- 权限继承、受限证据聚合、删除传播和防复活机制。
- Graphiti候选关系相对规则、Embedding、NLI和LLM带来的净增益。
- 用户确认成本、自动化覆盖率和错误回退速度。
- 大量会议下的增量更新、时间点查询和投影重建性能。

Mem0和Hindsight的主要优势是Agent/用户记忆的摄取、召回、反思和个性化，应在05检索研究中
与自建Hybrid RAG对照；04只允许它们作为Shadow Provider输出候选。Graphiti可在04重点验证
时态边和关系发现，但必须证明关闭它后权威状态仍正确。

## 评测指标

| 评测面 | 核心指标 | 主要错误 |
|---|---|---|
| Memory Promotion | Precision、Recall、污染率 | 把建议、观点或摘要错当组织事实 |
| 实体归一化 | B-cubed F1、False Merge、False Split | 同名人合并、同一项目拆散 |
| StateSlot归一化 | Pairwise F1、Scope准确率 | 不同版本误归槽、同一状态分裂 |
| Claim与关系 | Claim F1、各Relation Macro-F1 | 替代、修订、冲突、支持关系错判 |
| 当前状态 | Current State Exact Match | 旧决策仍显示为当前、新决策未生效 |
| 双时态 | Valid-time/System-time Snapshot Accuracy | 迟到会议改坏当前状态、无法重现旧认知 |
| 业务状态 | Decision/Action/Risk/Question Transition F1 | 完成后重开、风险解除等状态错误 |
| 乱序一致性 | Permutation Convergence Rate | 相同会议不同导入顺序产生不同结果 |
| 证据谱系 | Evidence Coverage、可追溯率、可播放率 | Claim没有原文或时间点 |
| 权限隔离 | Cross-tenant Leak Count、Restricted-source Leak Count | 从聚合结果推断隐藏会议 |
| 删除闭环 | Delete Closure、Projection Residue Count | 删除后向量、图、缓存或导出仍可见 |
| 幂等与并发 | Duplicate Count、Lost Update Count | 重试产生重复Claim、并发覆盖 |
| 人工审核 | Review Rate、Acceptance Rate、Median Review Time | 自动化率虚高或审核成本失控 |
| 投影恢复 | Rebuild Equivalence、Rebuild Time | 图或向量重建后与权威状态不一致 |

`Recall@K`、MRR、nDCG、no-answer拒答率和最终问答准确率属于05检索研究。04只对
“应当记住什么、当前什么有效、依据是什么”负责，不能用最终问答分数掩盖Memory本身错误。

## MeetingMemoryBench

第四块必须能在完全不运行01、02、03、05、06的情况下独立测试。Fixture直接提供
版本化Artifact、Transcript证据、租户、项目、权限和期望时间线。

最小黄金场景必须覆盖：

1. Flutter只是建议，不能成为已接受决策。
2. 后续会议正式接受Kotlin，同Scope旧方案被关闭并保留历史。
3. 再后续会议补充理由，只增加`supports`，不重复创建决策。
4. Android v1和v2的方案Scope不同，可以同时有效。
5. 旧会议迟到导入，只修正历史有效区间，不覆盖今天的当前状态。
6. 删除一场来源会议，但同一Claim仍有另一条独立证据。
7. 删除最后一条证据后，Claim从公开视图撤销且所有投影不可检索。
8. 两个同名人员不能自动合并；同一人的别名可人工确认和拆分回滚。
9. 行动项从OPEN到DONE后又REOPENED，完整保留每次状态变化。
10. 某人的反对观点形成Attributed Observation，但不自动变成组织决策冲突。
11. 受限会议参与了Memory计算，未授权用户既看不到内容，也不能从数量或措辞推断其存在。
12. 相同Artifact重复、并发和任意顺序导入，最终权威状态一致且无重复数据。

建议分层维护数据集：

- Smoke：5条短时间线，用于每次提交的秒级确定性回归。
- Development：至少30条时间线，每条3至10场会议，用于调参和错误分析。
- Locked Test：独立标注且开发阶段不可见，用于版本验收，避免在少量样例上过拟合。
- Adversarial：同名实体、否定、反问、模糊时间、Scope变化、权限混合、乱序和删除。

每个样例需要保存输入版本、期望Observation、StateSlot、Claim、关系、四类状态、
valid/system时间线、ACL结果、删除结果和标注分歧。模型、Prompt、规则和Provider版本
必须进入评测报告，保证结果可复现。

## 实施顺序

1. 先按[开源项目调研](OPEN_SOURCE_MEMORY_RESEARCH.md)部署Supermemory与Mem0，用同一批中文会议
   Smoke Fixture做限时对比，只选择一个主Provider进入快速上线链路。
2. 跑通“导入会议→候选事实→人工审核→项目搜索”，不等待完整知识图谱和所有状态机。
3. 冻结Observation、Entity、StateSlot、Claim、StateVersion五类权威对象及四类业务聚合。
4. 先写标注规范和MeetingMemoryBench，明确建议、观点、决定、行动、风险、问题的边界。
5. 实现最薄PostgreSQL控制面、幂等、证据、审核、租户隔离和删除传播。
6. 实现确定性的Promotion Policy、Observation导入和证据校验，不接图数据库。
7. 分别实现Decision、Action、Risk、Question状态机及时间点查询。
8. 实现可回滚Entity Resolver、StateSlot Resolver、Scope和人工审核。
9. 以Shadow方式加入规则、Embedding、NLI、LLM关系分类，逐项测净增益。
10. 再接Graphiti做候选关系和图遍历A/B测试；Hindsight、GraphRAG和LangGraph留在05对照。
11. 完成权限继承、乱序导入、并发写入和投影重建故障测试，输出稳定读取合同给05。

## 完成标准

- 固定五类权威schema、四类业务状态、Relation、读取视图和`MemoryChangeSet v1`。
- 建立可复现的Smoke、Development、Locked Test和Adversarial数据集。
- 禁用LLM、向量库和图数据库后，确定性权威状态和历史仍可完整读取。
- 双时态、幂等、并发、租户隔离和权限硬约束违规为零。
- 相同输入任意顺序导入的最终状态一致，历史修正可解释。
- 同一Artifact重复处理不会生成重复Observation、Claim或状态版本。
- 删除会议后，权威视图立即不可见，异步投影最终无残留且不会在重建时复活。
- 当前状态、历史快照、证据谱系和四类业务状态达到在黄金集上预先锁定的门槛。
- Graphiti、LLM或实验Memory Provider均可单独关闭、替换和重建。
- Memory独立提供Fixture和授权读取合同给05，不依赖聊天功能。

具体准确率目标必须在首版黄金集和规则基线产生后锁定，不能先写一个没有样本依据的
“95%”。发布门槛一旦锁定，本版本周期内不得跟随测试结果下调。

## 研究参考

- [开源 AI Memory 项目调研与 NotaRitmo 落地选型](OPEN_SOURCE_MEMORY_RESEARCH.md)：15个开源项目、
  功能分类、模块映射、快速上线组合和统一验收方案。
- [Graphiti](https://github.com/getzep/graphiti)：时态知识图谱、实体和关系候选。
- [Mem0](https://github.com/mem0ai/mem0)：Agent与用户记忆摄取、检索和图记忆实验。
- [Hindsight](https://github.com/vectorize-io/hindsight)：Recall、Reflect和Mental Model实验。
- [LongMemEval](https://arxiv.org/abs/2410.10813)：长期交互记忆评测设计参考，覆盖04与05，不能替代本模块业务时间线评测。
- [Zep论文](https://arxiv.org/abs/2501.13956)：时态知识图用于Agent Memory的系统与评测参考。
- [PostgreSQL Range Types](https://www.postgresql.org/docs/current/rangetypes.html)：有效区间和排斥约束。
- [PostgreSQL Row Security](https://www.postgresql.org/docs/current/ddl-rowsecurity.html)：租户与行级权限的纵深防护。
