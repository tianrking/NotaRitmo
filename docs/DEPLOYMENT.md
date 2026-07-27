# 部署、开发与迁移

## WSL 开发

```bash
cd /home/user/meeting-agent-platform
cp .env.example .env
docker compose up -d --build
docker compose ps -a
make lint
make test
make smoke
```

Compose 使用统一 `meeting-agent-app:latest` 镜像运行 migrate、API 和 Worker，避免三个
服务版本不一致。默认服务：

- PostgreSQL 16 + pgvector
- MinIO
- Temporal + UI
- Neo4j Community
- model-init（FastEmbed 目录和 27 MB CAM++ ONNX）
- Alembic migrate
- API + Worker

数据卷和网络使用独立 `meeting-agent` 前缀，不停止本机其他 ASR、LiteLLM 或监控服务。

## 必改生产配置

```dotenv
POSTGRES_PASSWORD=长随机值
MINIO_SECRET_KEY=长随机值
NEO4J_PASSWORD=长随机值
PROVIDER_AUDIO_SECRET=长随机值
HERA_SIGNING_SECRET=另一个长随机值
HERA_AUTH_REQUIRED=true

PUBLIC_API_BASE_URL=https://de.w0x7ce.eu
MINIO_PUBLIC_ENDPOINT=上传域名或内网可达地址
MINIO_PUBLIC_SECURE=true
```

`MINIO_PUBLIC_ENDPOINT` 是 App PUT 使用的地址，不是容器内的 `minio:9000`。公网部署可
把对象存储换成 S3/OSS 适配器，或给 MinIO 单独配置 TLS 域名。API 只需暴露 4200；
Temporal UI、MinIO Console、Neo4j 和 PostgreSQL 保持内网。

## Tingwu

```dotenv
TINGWU_ENABLED=true
TINGWU_APP_KEY=...
TINGWU_REGION=cn-beijing
TINGWU_DOMAIN=tingwu.cn-beijing.aliyuncs.com
ALIBABA_CLOUD_ACCESS_KEY_ID=...
ALIBABA_CLOUD_ACCESS_KEY_SECRET=...
```

听悟通过 `/v1/providers/audio/{meeting_id}?expires=...&token=...` 读取规范化音频。
`PUBLIC_API_BASE_URL` 必须能从听悟公网访问。当前没有第二个 ASR Provider。

## 统一 LLM 与成本

```dotenv
LLM_ENABLED=true
LLM_PROVIDER=openai-compatible
LLM_BASE_URL=http://host.docker.internal:4000/v1
LLM_API_KEY=...
LLM_MODEL=qwen-plus
LLM_PROMPT_VERSION=meeting-unified-v1
LLM_SCHEMA_VERSION=meeting-components-v1
LLM_INPUT_COST_PER_MILLION=...
LLM_OUTPUT_COST_PER_MILLION=...
LLM_MAX_TRANSCRIPT_CHARACTERS=240000
```

选择支持长上下文和 JSON object 输出的模型。超过字符上限会明确失败，不会静默截断或
分多组件重复计费。升级 Prompt/Schema 时改版本即可自动生成新缓存键。

## 音频与声纹

```dotenv
AUDIO_MAX_BYTES=6442450944
AUDIO_MAX_DURATION_SECONDS=21600
AUDIO_PREPROCESS_VERSION=ffmpeg-v1
AUDIO_DENOISE_DEFAULT=false

SPEAKER_EMBEDDING_ENABLED=true
SPEAKER_EMBEDDING_MODEL=/models/speaker/3dspeaker_speech_campplus_sv_zh-cn_16k-common.onnx
SPEAKER_EMBEDDING_MODEL_VERSION=3dspeaker-campplus-16k-v1
SPEAKER_EMBEDDING_DIMENSIONS=192
SPEAKER_MATCH_THRESHOLD=0.62
SPEAKER_MIN_ENROLLMENT_MS=3000
```

上线前必须用真实会议建立同人/异人验证集，确定 FAR/FRR 后再调整阈值。删除 Person 或
Profile 会删除样本/候选并解绑由声纹确认的 Speaker。

## Hera 签名

Hera 计算：

```text
hex(HMAC_SHA256(HERA_SIGNING_SECRET,
  METHOD + "\n" + PATH + "\n" + TENANT + "\n" + USER + "\n" +
  TIMESTAMP + "\n" + REQUEST_ID + "\n" + PERMISSIONS))
```

权限至少按调用包含：

- `meeting:read`
- `meeting:write`
- `meeting:query`
- `voiceprint:manage`
- `integration:read`
- `integration:ack`

Hera 拉取 `GET /v1/hera/outbox`，成功处理卡片/Todo 候选后调用
`POST /v1/hera/outbox/{event_id}/ack`。

## 迁移与备份

权威卷：

- `meeting-postgres`：事实、证据、版本、成本、声纹元数据、Outbox。
- `meeting-minio`：原始/规范化音频。
- `meeting-models`：可重新下载的模型。
- `meeting-neo4j`：可从 PostgreSQL 重建。

服务器迁移：

1. `pg_dump` / `pg_restore`。
2. `mc mirror` 迁移 MinIO。
3. 安全传输 `.env`，不提交密钥。
4. `docker compose up -d --build`，Alembic 自动升级。
5. Neo4j 可 restore，也可逐会议 reprocess。
6. 执行 `make lint && make test && make smoke`。
7. 用真实音频验证 Tingwu、音频回放、质量分和至少一组同人/异人声纹。

不要复制运行中的 PostgreSQL 数据目录。

## 运维

```bash
curl -fsS http://127.0.0.1:4200/health
curl -fsS http://127.0.0.1:4200/ready
curl -fsS http://127.0.0.1:4200/v1/graph/health
docker compose exec -T postgres psql -U meeting -d meeting \
  -Atc 'select version_num from alembic_version'
docker compose logs --tail=200 api worker migrate model-init neo4j
docker compose ps -a
```

关键可观测 API：

- `/v1/meetings/{id}/pipeline-runs`
- `/v1/meetings/{id}/extractions`
- `/v1/analytics/extractions`
- `/v1/voiceprints/candidates`
- `/v1/hera/outbox`
