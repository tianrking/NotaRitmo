# NotaRitmo

NotaRitmo 是运行在 Linux 上、供 Hera/Android 调用的会议智能内核。输入是音频或
Tingwu 原始转写，输出是可核验的单会议分析、跨会议记忆、Hybrid RAG、图谱和对话。
App 不直接与 Tingwu 对话；Tingwu 只负责转写、说话人分离、词级时间戳与置信度。

## 当前已实现

- App 通过预签名 PUT 直传 MinIO，API 不转发大文件；保留旧上传接口用于兼容。
- ffprobe 解码/格式/时长校验，ffmpeg 规范化为 16 kHz 单声道 PCM；可选降噪。
- 能量 VAD、语音/静音占比、RMS、削波、SNR、DC Offset 和 0–100 质量分。
- 唯一已注册 ASR Provider 是 Tingwu；接口已抽象，但没有假装实现多 ASR 路由。
- Tingwu 请求显式关闭摘要、章节、辅助、润色、翻译，只消费 ASR Canonical。
- 可替换 OpenAI-compatible LLM，一次提交紧凑转写并统一提取七类组件：
  `summary / facts / decisions / action_items / risks / open_questions / topics`。
- 每项绑定真实 Segment evidence；无有效 ordinal 的 LLM 项会被丢弃。
- 由统一语义层派生章节、热词、词云、思维导图、说话人统计和重点内容，共 13 类
  Artifact；不再逐组件重复发送全文。
- Canonical SHA-256、Prompt/Schema/模型版本、结果缓存、Token 和估算成本账本。
- Temporal 将音频预检、转写、Canonical、统一提取、声纹匹配、图谱、Hera Outbox
  拆为独立 Activity，分别重试和恢复。
- sherpa-onnx + 3D-Speaker CAM++ 192 维声纹：注册、跨会候选、用户确认/拒绝、
  删除与 Speaker 解绑。
- PostgreSQL + pgvector 文本/向量 RRF Hybrid RAG、Neo4j 图、跨会时态 Memory、
  单会/多会/全局分析和持久化对话。
- Hera HMAC 签名身份与权限上下文；租户、用户、对象路径、PostgreSQL 和 Neo4j
  查询使用同一 tenant 边界。
- NotaRitmo 只发布证据卡片和 Todo 候选到事务 Outbox；权限、卡片呈现、Todo
  物化和 App 交互仍归 Hera。

无外部 LLM 时使用确定性提取器，完整链路仍可工作。配置第三方 LLM 后才会调用它；
`Graphiti` 仍是可选图增强，不是权威事实库。

## 启动与验收

```bash
git clone https://github.com/tianrking/NotaRitmo.git
cd NotaRitmo
cp .env.example .env
docker compose up -d --build
docker compose ps
make lint
make test
make smoke
```

入口：

- API / OpenAPI：`http://localhost:4200/docs`
- Temporal UI：`http://localhost:8233`
- MinIO Console：`http://localhost:9001`
- Neo4j Browser：`http://localhost:7474`

`make smoke` 导入四场会议并验收词级证据、13 类产物、阶段化 Pipeline、统一提取账本、
Hybrid RAG、跨会记忆、Neo4j、Outbox 和多轮问答。成功标志是 `ACCEPTANCE_OK`。

## 音频直传

先申请上传地址：

```http
POST /v1/uploads
Content-Type: application/json

{
  "filename": "meeting.m4a",
  "content_type": "audio/mp4",
  "size_bytes": 12345678,
  "sha256": "64位十六进制，可选但推荐",
  "title": "项目周会",
  "project_id": "k6",
  "source_language": "cn",
  "denoise_enabled": false
}
```

客户端按响应的 `method/url/headers` 直接 PUT 对象，然后：

```http
POST /v1/uploads/{upload_id}/complete
{"sha256": "与申请时相同"}
```

完成后 Temporal 自动执行全链路。真实 Tingwu 需要：

```dotenv
PUBLIC_API_BASE_URL=https://de.w0x7ce.eu
PROVIDER_AUDIO_SECRET=长随机值
TINGWU_ENABLED=true
TINGWU_APP_KEY=...
ALIBABA_CLOUD_ACCESS_KEY_ID=...
ALIBABA_CLOUD_ACCESS_KEY_SECRET=...
```

## 第三方 LLM

```dotenv
LLM_ENABLED=true
LLM_PROVIDER=openai-compatible
LLM_BASE_URL=http://host.docker.internal:4000/v1
LLM_API_KEY=...
LLM_MODEL=...
LLM_PROMPT_VERSION=meeting-unified-v1
LLM_SCHEMA_VERSION=meeting-components-v1
LLM_INPUT_COST_PER_MILLION=0
LLM_OUTPUT_COST_PER_MILLION=0
```

`GET /v1/meetings/{id}/extractions` 和 `GET /v1/analytics/extractions` 返回哈希、版本、
cache hit、Token 和成本。相同 Canonical + 模型 + Prompt + Schema 会直接命中缓存。

## 主要 API

| 能力 | API |
|---|---|
| 完整报告/逐字稿/词级时间 | `GET /v1/meetings/{id}/report`、`/transcript`、`/words` |
| Pipeline / 提取账本 | `GET /v1/meetings/{id}/pipeline-runs`、`/extractions` |
| 13 类产物 | `GET /v1/meetings/{id}/artifacts` |
| 混合检索/会议问答 | `POST /v1/search`、`POST /v1/agent/query` |
| 跨会分析/记忆 | `POST /v1/analysis`、`POST /v1/memory/search`、`GET /v1/memory/timeline` |
| 持久对话 | `POST /v1/conversations`、`POST /v1/conversations/{id}/messages` |
| 图谱 | `GET /v1/meetings/{id}/graph`、`GET /v1/graph/search` |
| 声纹 | `POST /v1/voiceprints/enroll`、`GET /v1/voiceprints/candidates`、review/delete |
| Hera 交付 | `GET /v1/hera/outbox`、`POST /v1/hera/outbox/{id}/ack` |

## 分支和权威边界

- `main`：当前 Linux 会议智能内核。
- `android-legency`：原 Android 本地语音识别实验，原样保留。
- PostgreSQL：事实、证据、权限上下文、记忆、版本、成本和 Outbox 权威源。
- MinIO：原始音频和可重建规范化音频。
- pgvector / Neo4j：可重建索引。
- Temporal：流程状态与恢复，不是会议事实库。
- Hera：身份、产品权限、卡片、Todo 和 App 工作流。

详见 [架构](docs/ARCHITECTURE.md) 和 [部署](docs/DEPLOYMENT.md)。
