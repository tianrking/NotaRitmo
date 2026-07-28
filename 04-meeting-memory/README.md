# ④ 跨会议记忆 Meeting Memory

## 一句话定位

这一块才是会议Memory，但它不负责聊天。

它回答：

> 系统应该记住什么、信息来自哪里、什么目前有效、后来发生了什么变化。

## 输入

- 单会议`MeetingArtifactBundle`。
- 原始证据引用。
- 会议时间。
- 项目和组织信息。
- 人员与Speaker确认结果。
- 用户人工修订。
- 删除和权限变更事件。

## 输出：MemoryChangeSet

```json
{
  "meeting_id": "meeting_xxx",
  "schema_version": "memory-change-set-v1",
  "created_claims": [
    {
      "claim_id": "claim_kotlin",
      "subject": "Android首版",
      "predicate": "开发方案",
      "object": "原生Kotlin",
      "status": "active",
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
  ]
}
```

## 核心数据：Claim

```json
{
  "claim_id": "claim_xxx",
  "tenant_id": "tenant_xxx",
  "project_id": "android",
  "kind": "decision",
  "subject": "Android首版",
  "predicate": "开发方案",
  "object": "原生Kotlin",
  "scope": {
    "release": "v1"
  },
  "status": "active",
  "valid_from": "2026-07-20T10:00:00Z",
  "valid_to": null,
  "observed_at": "2026-07-20T12:00:00Z",
  "evidence_ids": ["seg_018"],
  "confidence": 0.95,
  "version": 2
}
```

## 完整功能点

### 记忆写入

- 将事实转换为Claim。
- 将决策转换为Claim。
- 将行动项转换为Claim或Task State。
- 将风险转换为持续状态。
- 将开放问题转换为待跟踪状态。
- 将主题和项目对象建立关联。
- 每个Claim绑定会议、Artifact和Segment证据。
- 只接受证据校验通过的正式数据。
- 无证据内容进入候选区，不直接成为事实。

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
- tenant之间绝不共享实体。

### Claim归一化

- 主体。
- 谓词。
- 对象。
- 业务范围。
- 适用版本。
- 地域或客户范围。
- 生效时间。
- 观察时间。
- 稳定Claim Key。
- 同一命题的多个表达归并。

### 关系

- `supports`：支持或补充已有Claim。
- `supersedes`：新决定替代旧决定。
- `contradicts`：两条Claim相互冲突。
- `follows_up`：后续会议继续处理。
- `related_to`：一般相关。
- `derived_from`：从其他事实推导。
- 每条关系都保存证据和算法版本。

### 时态和版本

- 当前有效Claim。
- 指定时间点有效Claim。
- 旧决策。
- 新决策。
- 生效与失效时间。
- 会议发生时间与系统观察时间分离。
- 延迟导入旧会议后的时间线重算。
- 决策变更历史。
- 行动项延期、完成、取消和重新打开。
- 项目连续状态。

### 状态机

```text
candidate -> active -> superseded
                    -> disputed
                    -> retracted
                    -> stale
```

- `candidate`：尚未正式确认。
- `active`：当前有效。
- `superseded`：被新Claim替代。
- `disputed`：存在未解决冲突。
- `retracted`：被明确撤回。
- `stale`：长期未更新或适用范围失效。

### 人工确认

- 确认新旧决策替代。
- 拒绝错误关系。
- 确认实体归并。
- 拆分错误实体。
- 修正Claim结构。
- 标记冲突已解决。
- 所有人工操作保留审计。
- 人工确认优先于自动判断。

### 删除、权限和隐私

- tenant隔离。
- 用户和项目范围。
- 删除会议。
- 删除音频。
- 删除Person和声纹。
- 删除证据后重新评估Claim。
- 清理向量索引。
- 清理图投影。
- 清理缓存。
- 导出某个用户或租户的全部Memory。

## 权威数据和投影

推荐边界：

```text
权威事实和版本
  - PostgreSQL或其他事务数据库

语义召回投影
  - pgvector或其他向量库

关系发现和图遍历
  - Neo4j
  - Graphiti

实验型Memory Provider
  - Mem0
  - Hindsight
```

Graphiti不是事实源。Mem0和Hindsight可以参与候选发现、对照实验和记忆策略研究，但不能
绕过统一Claim、证据、时态、权限和删除机制。

## 关系判定流程

```text
新Artifact
  -> Claim候选
  -> 实体和Claim Key归一化
  -> 召回同Key或同实体旧Claim
  -> 规则、NLI或LLM关系分类
  -> 硬约束校验
  -> 自动确认或人工审核
  -> 更新权威状态
  -> 发布可重建索引事件
```

关键词、Jaccard和向量相似度只能用于候选召回，不能单独决定`supersedes`。

## 可插拔点

```text
ClaimExtractor
EntityResolver
ClaimKeyGenerator
RelationClassifier
TemporalStateEngine
GraphProjection
MemoryExperimentProvider
HumanReviewPolicy
```

## 明确边界

- 不调用ASR。
- 不生成单会议摘要。
- 不负责用户查询排序。
- 不生成最终自然语言答案。
- 不把向量最近邻直接当成事实。
- 不自动覆盖存在冲突的旧Claim。
- 不允许图数据库成为唯一事实来源。

## 研究重点

- Graphiti、Mem0、Hindsight各自适合解决什么问题。
- 结构化Claim与纯向量Memory的质量差异。
- 新旧决策替代的自动判断。
- 时间、实体和适用范围对Claim Key的影响。
- 用户确认成本与自动化准确率平衡。
- 删除传播和可解释性。
- 大量会议下的增量更新性能。

## 评测指标

- Claim Precision / Recall / F1。
- 实体归并准确率。
- `supports`关系F1。
- `supersedes`关系F1。
- `contradicts`关系F1。
- 当前有效决策准确率。
- 历史时间点快照准确率。
- 行动项连续跟踪准确率。
- 删除传播完整率。
- 人工确认率。
- 自动关系撤销率。

## 完成标准

- 固定Claim、Relation和`MemoryChangeSet v1`。
- 建立“初始决策、替代决策、后续执行”的黄金时间线。
- 当前有效决策准确率目标不低于95%。
- 时态硬约束违规为零。
- 禁用向量库和图数据库后权威Claim仍然正确。
- 同一Artifact重复处理不会生成重复Claim。
- 删除会议后所有关联Memory和投影正确更新。
- Memory独立提供Fixture给检索模块，不依赖聊天功能。
