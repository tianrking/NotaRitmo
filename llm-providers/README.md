# 横向 LLM Providers

`llm-providers` 是 NotaRitmo 的横向基础设施，不是第七个业务模块。它只解决“如何以统一合同调用不同 LLM”，不拥有会议事实、Claim、权限、Memory 或答案裁决。

## 边界

```text
03 单会议理解 / 04 会议记忆 / 05 检索研究
        │ 构造 LLMRequest，携带证据和版本
        ▼
llm-providers
        │ 选择协议、调用、重试、解析、计量
        ▼
LLMResponse（候选数据 + input_hash + prompt/model + usage/cost/latency）
        │
03/04/05 自己做 Schema、Evidence、权限、状态和 no-answer 校验
```

Provider 禁止：

- 直接查询或修改 PostgreSQL、Memory、Claim Ledger。
- 自己决定 `active/superseded`、租户范围、负责人或截止日期是否可信。
- 绕过模块的证据校验把模型输出发布为正式 Artifact/Claim。
- 把 API Key、完整 Authorization、完整提示词或会议全文写进普通日志。

## 已实现

- 统一 `LLMRequest` / `LLMResponse` / `Usage` 合同。
- `input_hash`、`prompt_version`、`schema_version`、模型标识。
- `OfflineFixtureProvider`：默认不联网，适用于 CI 和编排回归。
- `OpenAICompatibleProvider`：`/v1/chat/completions`。
- `AnthropicCompatibleProvider`：`/v1/messages`，包含 BigModel Anthropic-compatible 路由。
- 超时、有限指数退避重试（408/409/425/429/5xx 和网络错误）。
- API 返回 usage 时记录真实 token；没有 usage 时明确标记为 estimated。
- 可选每百万 token 成本估算、延迟、重试次数、脱敏 endpoint/request id。
- 单进程可选缓存；生产共享缓存由 Go 控制面实现。
- 环境变量配置和无密钥 `.env.example`。
- 本地 loopback HTTP mock 契约测试，不依赖互联网或真实 SaaS Key。

## 默认配置

默认值是离线模式：

```bash
LLM_PROVIDER=offline
LLM_API_STYLE=offline
LLM_MODEL=fixture
```

用户当前 BigModel 路由可按 Anthropic-compatible 协议配置：

```bash
LLM_PROVIDER=anthropic-compatible
LLM_API_STYLE=anthropic
ANTHROPIC_BASE_URL=https://open.bigmodel.cn/api/anthropic
ANTHROPIC_AUTH_TOKEN=<仅注入当前 shell，不写入 Git>
ANTHROPIC_MODEL=glm-5.2
```

这里的 token 只作为环境变量名称示例；仓库、README、测试输出中不保存真实凭证。也可以改用 OpenAI-compatible：

```bash
LLM_PROVIDER=openai-compatible
LLM_API_STYLE=openai
LLM_BASE_URL=https://api.example.com
LLM_API_KEY=<仅注入当前 shell>
LLM_MODEL=your-model
```

## 运行

本目录只使用 Python 标准库：

```bash
cd /home/user/meeting-agent-platform/llm-providers
python3 -m unittest discover -s tests -p 'test_*.py' -q
```

测试会启动本地临时 HTTP mock，覆盖两个协议、重试、usage/cost/latency、缓存、环境别名和密钥脱敏；不会访问公网。

## 接入 03 / 04 / 05

业务模块只把自己的 DTO 转换为 `LLMRequest`：

```python
from llm_providers import LLMRequest, ProviderRouter

request = LLMRequest(
    operation="meeting.extract",
    system_prompt="只根据证据抽取结构化会议产物。",
    user_payload={"meeting_id": meeting_id, "segments": segments},
    prompt_version="meeting-extract-v1",
    response_schema={"type": "object"},
    model_hint="glm-5.2",
)
response = ProviderRouter.from_env().complete_json(request)
# response.data 是候选；模块必须继续做证据、权限、状态和 Schema 校验。
```

推荐职责：

- 03 负责会议 Artifact 的 Prompt、EvidenceRef 校验和质量门禁。
- 04 负责 Claim 规范化、实体归并、双时态和 PostgreSQL 事务；Provider 只产生候选。
- 05 负责检索后证据约束回答和 no-answer；Provider 不能自行补事实。
- Go 控制面负责 Provider 路由、密钥加载、缓存、配额、审计、Temporal 重试和成本汇总；本目录 Python 实现用于本地模型/研究/合同回归。

## 明确的未完成项

此目录不是完整 LLM 质量系统，仍需由业务模块实现：真实模型抽取评估、Prompt A/B、事实一致性、引用可播放验证、PostgreSQL/pgvector、权限和生产可观测性。`OfflineFixtureProvider` 只能证明编排合同，不代表模型质量。
