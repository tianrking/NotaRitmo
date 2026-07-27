# NotaRitmo

NotaRitmo 当前主线是一个运行在 Linux 上、以证据为中心且与 ASR 供应商解耦的
会议分析产品后端。第一阶段由通义听悟提供
单场音频的转写、说话人、章节、摘要、待办和关键词；平台把这些结果规范化后，提供
单会议与跨会议的检索、问答、汇总和原文时间点验证。

## 分支

- `main`：Linux 会议分析、记忆、检索和 API 主线。
- `android-legency`：早期 Android 本地语音识别实验原貌。

## 核心边界

- App 只调用本项目的 API，不直接持有听悟 AccessKey。
- PostgreSQL 是事实与证据的权威数据源。
- pgvector/全文检索和 Graphiti 都是可重建索引。
- 原始音频和听悟原始 JSON 永久与派生结果分层保存。
- 没有听悟凭证时，可以导入固定结果样本完成端到端开发。

## 当前可运行能力

- 音频 URL 创建会议并异步提交听悟。
- 导入听悟原始结果 JSON。
- 官方段落、Speaker、词级时间戳规范化。
- 单场会议逐字稿、摘要、章节、待办、关键词、词云数据和树状结构。
- 单场或跨会议搜索与问答，返回会议、Speaker、原文和时间点证据。
- 项目/时间范围内的多会议汇总。
- 多租户字段和会议访问控制数据结构。
- Temporal 持久化后台任务。
- 可选 Graphiti/Neo4j profile。

当前的检索基线使用中文分词和 PostgreSQL 文本匹配，`pgvector` 字段和扩展已经建好，
但向量写入与混合召回要在配置 Embedding 模型后作为下一阶段启用。通用文本模型未配置
时，Agent 会返回可核验的原文证据摘要；不会伪装成已经执行了大模型推理。

当前是可运行的后端 MVP，不是已经生产化的成品：真实听悟请求需要用户自己的凭证和
可公网下载的测试音频；登录鉴权、PostgreSQL RLS、限流、备份和删除传播需要在服务器
上线前补齐。Graphiti 是可选跨会议时态索引，不是事实源。

## 快速启动

```bash
git clone https://github.com/tianrking/NotaRitmo.git
cd NotaRitmo
cp .env.example .env
docker compose up -d --build
docker compose ps
make smoke
```

API 文档：

- `http://localhost:4200/docs`
- `http://localhost:8233`（Temporal UI，仅本机）
- `http://localhost:9001`（MinIO Console，仅本机）

## 真实听悟

在 `.env` 中配置：

```dotenv
TINGWU_ENABLED=true
TINGWU_APP_KEY=...
ALIBABA_CLOUD_ACCESS_KEY_ID=...
ALIBABA_CLOUD_ACCESS_KEY_SECRET=...
```

然后调用：

```http
POST /v1/meetings
Content-Type: application/json

{
  "title": "项目周会",
  "audio_url": "https://可供听悟下载且有效期足够长的地址/audio.m4a",
  "project_id": "android",
  "source_language": "cn"
}
```

听悟离线任务需要能从公网下载音频。本地 MinIO 地址默认不满足这一要求；开发期应传
外部可访问的预签名 URL，正式环境则由平台的对象存储生成。

## 查询

```http
POST /v1/agent/query
Content-Type: application/json

{
  "query": "哪些会议讨论过OTA，当前结论是什么？",
  "scope": {
    "mode": "all_meetings",
    "project_id": "k6"
  }
}
```

更多架构、状态机、数据层次与迁移方法见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
和 [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)。
