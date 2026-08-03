# pgvector 语义检索适配器

`PgVectorRetriever` 是检索候选的可选 Provider。它不写入 Claim 状态、不做权限决定，也不
生成最终答案。它依赖 PostgreSQL 中已经存在的 `segment_embeddings` 与 `claim_embeddings`
投影。

## 何时启用

- 研究 Fixture/Windows 基线：优先使用词法 `LexicalRetriever` 和 SQLite，保证可重复、无需大模型和数据库。
- 生产 Hybrid RAG：先 PostgreSQL FTS 召回，再用 pgvector 语义召回；必要时在两路候选上增加
  reranker。pgvector 关闭时，必须由编排层显式选择词法降级，不能静默掩盖数据库故障。
- Embedding 模型变化时，按 `model_id + dimensions + content_hash` 重建投影。不同维度不能
  混在同一个 `vector(n)` 列中。

## 依赖与迁移

```bash
python -m pip install "psycopg[binary]>=3.1,<4"
psql "$DATABASE_URL" -f adapters/postgres/migrations/001_core.sql
psql "$DATABASE_URL" -f adapters/postgres/migrations/002_rls.sql
psql "$DATABASE_URL" -f adapters/pgvector/migrations/003_embeddings.sql
```

`003_embeddings.sql` 默认使用 1536 维和 cosine 距离，适合一个固定 Embedding Provider。
若选择 1024/768 维模型，应复制迁移为独立表/索引并同步 `dimensions` 检查，不能把维度
不一致的向量强行写入。

## Provider 接口

```python
class MyEmbedder:
    model = "embedding-model-v1"
    dimensions = 1536

    def embed(self, text: str) -> list[float]:
        ...

retriever = PgVectorRetriever(
    database_url,
    embedder=MyEmbedder(),
    fallback=lexical_retriever,       # 仅在显式 allow_fallback=True 时生效
    allow_fallback=True,
)
```

返回格式与 `baseline.Retriever` 一致：`segments` 和 `claims` 各包含 `score` 与原始 JSON。
查询始终带 `tenant_id`，并在事务中设置 RLS 上下文。`current_state` 查询只检索 active
Claim；历史查询是否包含 superseded Claim 由上层 Research 模块编排。

## 生产限制

- 本目录不生成 Embedding；模型、批处理、重试、成本和版本由上层任务编排负责。
- SQL 投影可删除并重建，PostgreSQL 核心表不能被向量任务覆盖。
- 没有 pgvector 扩展或 psycopg 时，适配器会明确失败；只有调用方明确传入 fallback 才会降级。
- 向量相似度只是候选排序，不等于事实正确性。答案必须继续经过证据、状态、租户和
  no-answer 门禁。
