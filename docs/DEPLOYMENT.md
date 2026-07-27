# 部署、开发与迁移

## 当前 WSL 开发

```text
/home/user/meeting-agent-platform
```

```bash
cd /home/user/meeting-agent-platform
cp .env.example .env
docker compose up -d --build
docker compose ps -a
make lint
make test
make smoke
```

开发热加载：

```bash
docker compose -f compose.yaml -f compose.dev.yaml up -d
```

Compose 默认启动：

- PostgreSQL + pgvector
- MinIO
- Temporal + Temporal UI
- Neo4j Community
- 一次性数据库迁移和模型卷初始化
- NotaRitmo API + Worker

项目使用独立 `meeting-agent` Compose 名称、网络和数据卷，不会停止本机既有 ASR、
LiteLLM、Grafana、Prometheus 或 Loki 服务。

## 配置

必须在服务器修改：

```dotenv
POSTGRES_PASSWORD=长随机值
MINIO_SECRET_KEY=长随机值
NEO4J_PASSWORD=长随机值
PROVIDER_AUDIO_SECRET=长随机值
PUBLIC_API_BASE_URL=https://de.w0x7ce.eu
```

听悟：

```dotenv
TINGWU_ENABLED=true
TINGWU_APP_KEY=...
ALIBABA_CLOUD_ACCESS_KEY_ID=...
ALIBABA_CLOUD_ACCESS_KEY_SECRET=...
```

可选文本模型：

```dotenv
LLM_ENABLED=true
LLM_BASE_URL=http://host.docker.internal:4000/v1
LLM_API_KEY=...
LLM_MODEL=...
```

本地 embedding 默认开启并缓存到 `meeting-models` 卷。首次处理会下载
`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`，以后复用缓存。

Graphiti LLM 增强默认关闭；Neo4j 确定性图默认开启：

```dotenv
GRAPH_MEMORY_ENABLED=true
GRAPHITI_ENABLED=false
```

## 反向代理

只把 API 4200 端口经 TLS 暴露到公网。听悟会通过
`/v1/providers/audio/{meeting_id}?expires=...&token=...` 临时读取上传音频；因此代理
不能屏蔽该路径，且 `PUBLIC_API_BASE_URL` 必须与公网地址一致。

Temporal UI、MinIO Console、Neo4j Browser 和数据库端口保持本机或内网访问。

## 数据、备份与服务器迁移

数据卷：

- `meeting-postgres`：权威事实、证据、记忆、对话和审计。
- `meeting-minio`：音频对象。
- `meeting-models`：可重新下载的 embedding 模型。
- `meeting-neo4j`：可从 PostgreSQL 重建的关系索引。

迁移顺序：

1. 推送/拉取 Git 提交。
2. `pg_dump` / `pg_restore` 迁移 PostgreSQL。
3. `mc mirror` 迁移 MinIO。
4. 复制 `.env` 的安全值，不提交密钥。
5. `docker compose up -d --build`，由 Alembic 自动升级。
6. Neo4j 可 dump/restore，也可逐会议重新处理投影。
7. 执行 `make smoke` 和一份真实听悟录音验收。

不要复制运行中的 PostgreSQL 数据目录。正式环境应把 PostgreSQL、对象存储、Temporal
改为有备份和监控的托管或独立服务，并补 TLS、OIDC、RLS、限流、删除传播和告警。

## 运维检查

```bash
curl -fsS http://127.0.0.1:4200/health
curl -fsS http://127.0.0.1:4200/ready
curl -fsS http://127.0.0.1:4200/v1/graph/health
docker compose logs --tail=200 api worker migrate neo4j
docker compose ps -a
```

成功的四会议验收输出：

```text
ACCEPTANCE_OK {...}
```
