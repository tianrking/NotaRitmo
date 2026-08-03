# PostgreSQL 权威记忆适配器

`repository.py` 是可选 `psycopg` 3 的实现，负责把已经通过单会议理解质量门禁的
MeetingArtifact/Claim 写进 PostgreSQL。它不负责 LLM 抽取，也不负责向量生成。

## 生产职责

PostgreSQL 是以下内容的唯一权威源：

- 会议、Transcript Segment、Artifact 版本和来源。
- Claim 的主体/谓词/值、审核状态、证据状态、有效时间。
- `active`、`superseded`、`disputed`、`retracted` 状态。
- Claim 与证据 Segment 的外键关系。
- `supports`、`supersedes`、`contradicts`、`follows_up` 关系。
- `tenant_id`、事务、唯一约束、删除级联和 RLS。

pgvector、Graphiti、Mem0 都只能从这些表重建投影，不能成为最终事实源。

## 安装与连接

只有真正连接 PostgreSQL 时才安装驱动：

```bash
python -m pip install "psycopg[binary]>=3.1,<4"
export DATABASE_URL='postgresql://meeting_runtime:***@postgres:5432/meeting_memory'
```

执行迁移：

```bash
psql "$DATABASE_URL" -f adapters/postgres/migrations/001_core.sql
psql "$DATABASE_URL" -f adapters/postgres/migrations/002_rls.sql
```

运行时角色必须不是表 Owner，也不能带 `BYPASSRLS`。每个事务由适配器设置：

```sql
SET LOCAL app.tenant_id = 'tenant_alpha';
```

适配器同时使用显式 `WHERE tenant_id = %s` 和数据库 RLS，形成纵深隔离。缺少 psycopg 时构造
适配器会抛出明确的 `PostgresDependencyError`；它不会偷偷退回内存或 SQLite。

## 时间字段

生产 PostgreSQL 表使用 `timestamptz`。`valid_from`、`valid_to`、`started_at`、`ended_at`
必须是 ISO-8601 时间（例如 `2026-08-03T10:30:00Z`）。固定 Fixture 中用会议 ID 代替日期的
规则只属于 SQLite 研究基线，不能直接写入生产表。

## 事务和状态

`ingest_meeting()` 在一个事务中写入会议、片段、Artifact 和 Claim。对于同一租户、同一
`subject + predicate` 的现有 `active` Claim，如果值发生改变，适配器会在 `FOR UPDATE`
锁下把旧 Claim 标为 `superseded`，然后写入新 Claim 并保留证据。复杂实体归并和关系候选仍
需要上层 Promotion Policy/审核，不由 SQL 或 LLM 自动越权。

## 不属于此适配器的功能

- LLM 结构化抽取与模型评估。
- Embedding 生成、pgvector 召回和 reranker。
- HTTP API、Temporal、MinIO 和音频播放 URL。
- 自动跨租户实体合并。

没有 PostgreSQL 时，使用 `baseline/sqlite_repository.py` 做离线研究；这并不代表生产
PostgreSQL 已经部署或验证。
