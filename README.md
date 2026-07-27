# NotaRitmo

NotaRitmo 是运行在 Linux 上的会议分析与长期记忆后端。输入可以是音频 URL、上传的
MP3/MP4/M4A 等文件，或已完成的通义听悟结果；输出是可检索、可对话、可回到原音频
时间点核验的单会议与跨会议知识。

它不是“直接和听悟聊天”的客户端。Android/Web 只调用 NotaRitmo；听悟是当前默认但
可替换的单会议识别供应商。

## 已实现

- URL 和文件上传、MinIO 保存、带 HMAC 过期签名的听悟下载桥接。
- Temporal 持久化处理、重试和可观察状态。
- Meeting、Speaker、Sentence Segment、Word 及词/句起止时间的规范化。
- 摘要、详细摘要、章节、待办、决策、风险、未决问题、热词、词云、树状图、
  说话人统计、重点内容，共 12 类会议产物。
- 每个摘要项、章节、决策和长期记忆关联稳定的 `segment_id`、说话人和时间点。
- FastEmbed 本地多语 384 维向量；PostgreSQL 文本召回 + pgvector HNSW 向量召回
  + RRF 混合排序。
- 单会议、选定多会议、项目全部会议和全部历史会议的检索与综合分析。
- 决策变更、行动跟进、相关主题等跨会议时间关系。
- PostgreSQL 权威记忆库 + 默认启动的 Neo4j Community 可重建关系图。
- 持久化多轮对话、复合问题规划、证据引用和回答落地验证。
- 可选 Graphiti LLM 时态抽取增强；它不替代权威事实库。

没有通用 LLM 时，查询仍会由确定性证据引擎完整工作；配置 LiteLLM 后可增加自然语言
组织能力，但模型不能越过授权范围或无证据补造内容。

## 分支

- `main`：Linux 会议分析、记忆、检索和 API 产品主线。
- `android-legency`：原 Android 本地语音识别实验，保留原貌。

## 快速启动

```bash
git clone https://github.com/tianrking/NotaRitmo.git
cd NotaRitmo
cp .env.example .env
docker compose up -d --build
docker compose ps
make smoke
```

入口：

- API / OpenAPI：`http://localhost:4200/docs`
- Temporal UI：`http://localhost:8233`
- MinIO Console：`http://localhost:9001`
- Neo4j Browser：`http://localhost:7474`

`make smoke` 会顺序导入 4 场会议并验收全部产物、单/跨会检索、时态记忆、图谱、
证据和两轮对话，成功标志是 `ACCEPTANCE_OK`。

## 真实音频接入听悟

在 `.env` 中填写：

```dotenv
PUBLIC_API_BASE_URL=https://de.w0x7ce.eu
PROVIDER_AUDIO_SECRET=替换为长随机值
TINGWU_ENABLED=true
TINGWU_APP_KEY=...
ALIBABA_CLOUD_ACCESS_KEY_ID=...
ALIBABA_CLOUD_ACCESS_KEY_SECRET=...
```

反向代理必须把 `PUBLIC_API_BASE_URL` 指向 API 的 4200 端口。App 只需上传：

```bash
curl -X POST http://localhost:4200/v1/meetings/upload \
  -F 'file=@meeting.m4a' \
  -F 'title=项目周会' \
  -F 'project_id=k6'
```

NotaRitmo 保存音频、生成临时公网读取签名、提交听悟、拉取完整结果、规范化、生成向量
并写入图记忆。也可用 `POST /v1/meetings` 提交已有公网 URL，或
`POST /v1/meetings/import/tingwu` 导入听悟原始 JSON。

## 查询与交互

完整单会报告：

```http
GET /v1/meetings/{meeting_id}/report
```

跨会议问答：

```http
POST /v1/agent/query
Content-Type: application/json

{
  "query": "K6最终采用什么发布方案，有哪些风险和谁负责后续任务？",
  "scope": {
    "mode": "all_meetings",
    "project_id": "k6"
  },
  "limit": 30
}
```

持久化对话：

```http
POST /v1/conversations
POST /v1/conversations/{conversation_id}/messages
GET  /v1/conversations/{conversation_id}
```

主要 API 还包括：

| 能力 | API |
|---|---|
| 逐字稿与词级时间 | `GET /v1/meetings/{id}/transcript`、`/words` |
| 全部派生产物 | `GET /v1/meetings/{id}/artifacts` |
| 混合原文检索 | `POST /v1/search` |
| 长期记忆检索/时间线 | `POST /v1/memory/search`、`GET /v1/memory/timeline` |
| 单会/多会/全局分析 | `POST /v1/analysis` |
| 关系图与图搜索 | `GET /v1/meetings/{id}/graph`、`GET /v1/graph/search` |
| 音频回放入口 | `GET /v1/meetings/{id}/audio-url` |

## 权威边界

- PostgreSQL：事实、权限、证据、结构化记忆和会话的权威存储。
- MinIO：音频与对象。
- pgvector：可重建语义索引。
- Neo4j/Graphiti：可重建关系与时态索引。
- Temporal：后台任务编排，不保存会议事实。
- LiteLLM：可选模型路由，不保存会议事实。

当前本地部署使用一个默认租户/用户。表结构已携带 `tenant_id` 和会议访问关系，但真正
多用户上线仍须接入身份认证、把默认用户替换为请求身份并启用 PostgreSQL RLS；不能把
“字段已预留”描述成“生产权限已经完成”。

详见 [架构](docs/ARCHITECTURE.md) 和 [部署](docs/DEPLOYMENT.md)。
