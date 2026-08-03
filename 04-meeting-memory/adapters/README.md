# 生产存储与检索适配层

这里是 `04-meeting-memory` 的可插拔基础设施边界，不是本地基线本身。

## 权威边界

| 组件 | 角色 | 当前状态 |
| --- | --- | --- |
| SQLiteRepository | Windows/WSL 单机研究基线 | 已实现并可离线测试 |
| PostgreSQLRepository | 生产权威事实、证据、状态和租户边界 | 适配器与迁移 SQL 已提供；需要真实 PostgreSQL 才能运行 |
| pgvector | 语义召回投影 | SQL 与 Retriever 已提供；需要启用 pgvector 和 Embedding Provider |
| PostgreSQL FTS | 词法召回/Hybrid 的一条检索分支 | 由核心表的 GIN 索引提供 |
| Graph/Mem0 等 | 可重建的候选投影/实验 Provider | 不属于本目录的事实权威 |

PostgreSQL 是生产必选项；SQLite 只用于固定 Fixture、开发和回归测试。pgvector 是检索增强，
不是记忆事实源。即使向量索引损坏，PostgreSQL 中的 Claim、状态和证据也必须保持完整，并可
从权威表重建投影。

## 目录

```text
adapters/
├── postgres/
│   ├── repository.py              # 可选 psycopg 3 的 Repository 实现
│   ├── migrations/001_core.sql    # 权威表、证据、约束和全文索引
│   ├── migrations/002_rls.sql     # tenant_id RLS 策略
│   └── README.md
├── pgvector/
│   ├── retriever.py               # 可选 pgvector 语义检索适配器
│   ├── migrations/003_embeddings.sql
│   └── README.md
└── tests/test_sql_contract.py     # 不连接数据库的静态契约测试
```

## 运行边界

这些文件不会自动安装 psycopg、启动 PostgreSQL、创建 Docker 容器或下载模型。生产部署时：

1. 准备 PostgreSQL 15+，并在数据库中按顺序执行 `postgres/migrations/001_core.sql`、
   `postgres/migrations/002_rls.sql`。
2. 如果需要语义召回，再安装与目标 pgvector 版本匹配的扩展，执行
   `pgvector/migrations/003_embeddings.sql`。
3. 应用使用非 Owner、非 `BYPASSRLS` 角色连接，并在每个事务设置 `app.tenant_id`。
4. 将 `DATABASE_URL` 传给 `PostgreSQLRepository`，将同一连接配置传给
   `PgVectorRetriever`。

连接配置示例见各子目录 README。没有真实数据库时应继续使用 `SQLiteRepository`，不能把
“适配器能导入”当成“PostgreSQL 已部署”。
