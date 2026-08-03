# 会议记忆研究服务 API

这是当前 04 模块的可运行研究版入口：它接收已经由 ASR 生成的
`TranscriptBundle`，异步完成单会议规则抽取，把会议、证据、Claim 写入
SQLite，并提供带租户过滤的查询接口。默认不调用网络、不下载模型、不调用
外部 LLM；LLM、PostgreSQL、pgvector 和 Temporal 是可替换的后续运行适配器。

## 启动

在 WSL 项目目录执行：

```bash
cd /home/user/meeting-agent-platform/04-meeting-memory
python3 api_server.py --host 127.0.0.1 --port 8090 --db ./data/meeting-memory.sqlite3
```

也可以用环境变量：

```bash
MEETING_MEMORY_DB=./data/meeting-memory.sqlite3 \
  python3 api_server.py --host 0.0.0.0 --port 8090
```

Windows VS Code 可以通过以下路径打开同一个 WSL 项目：
`\\wsl.localhost\Ubuntu-24.04-sglang\home\user\meeting-agent-platform`。

## 数据流

```text
TranscriptBundle
  -> Schema/tenant/ID/时间戳校验
  -> 202 queued
  -> 后台 worker
  -> 单会议 artifact + evidence-backed claims
  -> SQLite meetings/segments/artifacts/claims
  -> /v1/query 检索、no-answer、引用
```

## 输入格式

```json
{
  "meeting_id": "meeting_demo_01",
  "tenant_id": "tenant_demo",
  "title": "方案评审",
  "segments": [
    {
      "segment_id": "seg_001",
      "speaker_id": "speaker_01",
      "start_ms": 0,
      "end_ms": 3200,
      "text": "我们决定先完成 Android 上传。",
      "confidence": 0.94,
      "words": []
    }
  ]
}
```

`meeting_id`、`tenant_id`、`segment_id`、`speaker_id` 和非空 `text` 必须存在；
时间戳是非负整数且 `end_ms > start_ms`；不同说话人的片段允许重叠，不能把
串话误判为非法输入。重复 ID、跨租户 ID 冲突和不同内容复用同一会议 ID 会被拒绝。

## 提交会议

```bash
curl -X POST http://127.0.0.1:8090/v1/meetings \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: demo-01' \
  --data @bundle.json
```

响应为 `202`：

```json
{
  "job_id": "...",
  "meeting_id": "meeting_demo_01",
  "tenant_id": "tenant_demo",
  "status": "queued",
  "duplicate": false
}
```

重复提交相同内容会返回同一个 `job_id`，并将 `duplicate` 置为 `true`；同一
幂等键提交不同内容返回 `409`。

## 查询作业

作业查询也必须带租户，避免把原始请求内容泄露给其他租户：

```bash
curl 'http://127.0.0.1:8090/v1/jobs/JOB_ID?tenant_id=tenant_demo'
```

终态为 `completed` 或 `failed`。成功结果含：

```json
{
  "status": "completed",
  "result": {
    "artifact": {
      "meeting_id": "meeting_demo_01",
      "summary": "...",
      "claims": [],
      "decisions": [],
      "action_items": [],
      "risks": []
    },
    "metadata": {
      "run_id": "...",
      "input_sha256": "...",
      "schema_version": "transcript-bundle-v1",
      "extractor_version": "fixture-rule-v1",
      "counts": {"segments": 1, "claims": 1},
      "latency_ms": 1.2
    }
  }
}
```

## 查询与证据回溯

```bash
curl -X POST http://127.0.0.1:8090/v1/query \
  -H 'Content-Type: application/json' \
  --data '{
    "tenant_id": "tenant_demo",
    "question": "Android 上传什么时候完成？",
    "query_type": "retrieval",
    "top_k": 5
  }'
```

返回 `answer`、`no_answer`、`confidence`、`meetings`、`claims`、`citations`。
每个 citation 含 `meeting_id`、`segment_id`、`speaker_id`、`start_ms`、
`end_ms` 和原文 `text`，客户端可以据此定位音频播放点。无租户证据时返回
`no_answer: true`，不会跨租户兜底。

只查指定会议：

```json
{
  "tenant_id": "tenant_demo",
  "meeting_scope": "meeting_demo_01",
  "question": "刚才的决定是什么？"
}
```

`meeting_scope` 也可以是会议 ID 数组，用于多会议比较；`mode` 是
`query_type` 的兼容别名，可取 `current_state`、`historical_state` 等。

## 替换 Extractor / Repository / Service

HTTP 层不把规则抽取器写死。嵌入 Python 的调用方可以注入已经完成证据校验的
Extractor、PostgreSQL Repository 或完整 Service：

```python
from api_server import create_app
from intelligence.extractor import MeetingArtifactExtractor
from llm_providers import InMemoryResponseCache, ProviderRouter

provider = ProviderRouter.from_env(cache=InMemoryResponseCache())
extractor = MeetingArtifactExtractor(provider, prompt_version="meeting-artifact-v1")
app = create_app(
    "./data/meeting-memory.sqlite3",
    extractor=extractor,
    # repository=PostgreSQLRepository(...),  # 生产适配器
    # service=MeetingMemoryService(...),
)
```

Provider 的选择仍由 `LLM_PROVIDER`、`LLM_API_STYLE` 和对应凭证环境变量决定；
默认不联网。真实 LLM 返回的 Artifact 必须先通过 `intelligence.schema` 的
Schema/证据检查，未通过的结果只能失败或进入审核，不能绕过 HTTP 作业状态写入
当前记忆。`llm-providers/README.md` 列出 Anthropic-compatible（包括 BigModel
兼容路由）和 OpenAI-compatible 配置，仓库不保存任何凭证。

## 读取单场会议

```bash
curl 'http://127.0.0.1:8090/v1/meetings/meeting_demo_01?tenant_id=tenant_demo'
```

返回会议元数据、完整 segments、artifact 和 Claim 生成的证据入口。缺少
租户参数或租户不匹配时不会返回会议内容。

## 固定十场 Fixture 测试

```bash
cd /home/user/meeting-agent-platform/04-meeting-memory
python3 -m unittest -v tests.test_api_server
python3 -m unittest discover -v
```

离线批量评估仍使用：

```bash
cd baseline
python3 run_fixture.py
python3 evaluation/run_llm_loop.py --provider offline
```

## 当前边界

当前服务已经是可长期运行、可增量提交和查询的研究闭环，但默认抽取和
检索仍是确定性的 fixture-rule/lexical baseline。它证明 API、持久化、幂等、
证据、`no_answer`、重启恢复和租户边界，不代表真实 LLM 的理解质量，也不
代表生产级并发能力。

生产替换顺序保持解耦：用真实结构化 LLM Provider 替换 extractor；用
PostgreSQL 作为事实/权限权威；用 pgvector + FTS + reranker 替换 lexical
retriever；用 Temporal 承担可恢复工作流。所有替换都不改变本 HTTP 输入输出
协议。生产部署还必须增加认证、授权、TLS、限流、审计和音频对象存储策略。
