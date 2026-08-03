# 可选 LLM Provider 与 Fixture 评估

这个目录是会议核心的模型适配边界。它不拥有会议事实，也不决定权限、Claim
状态或 `no-answer`；它只负责把一组明确的输入交给可选 LLM，并将结构化 JSON
和 `provider/model/prompt/input_hash/token/cost` 元数据返回给上层。

## 当前实现

> Provider 唯一实现位于仓库顶层的
> [`llm-providers/`](../../../llm-providers/README.md)。本目录的
> `provider.py` 是旧评估器的临时兼容模块，仅为既有测试保留，禁止在其中新增
> SaaS、协议或重试实现。新的 03/04/05 编排（包括 `run_llm_loop.py`）必须直接
> 导入顶层 `llm_providers`。

- `LLMProvider`：唯一需要被会议编排依赖的接口，方法是 `complete_json(request)`。
- `OpenAICompatibleProvider`：仅使用 Python 标准库调用兼容
  `POST /chat/completions` 的 SaaS 或自建服务，不依赖 SDK。
- `FixtureReplayProvider`：离线回放 gold fixture 的契约测试 Provider。它不调用
  模型、不会产生真实模型质量，不能将其 F1 当作 LLM 结果。
- `build_meeting_extraction_request()`：固定单会议理解的 JSON schema、Prompt 版本
  和输入哈希。
- `build_answer_request()`：固定受证据约束的问答 JSON schema；最终
  `no-answer` 必须由确定性策略层再次校验。
- `evaluator.py`：可以调用 Provider，也可以对落盘预测重跑评分。指标按字段
  Precision/Recall/F1，证据按 `segment_id` 评分，避免“文字像”被误当成事实正确。

## 默认不联网的 Windows 测试

在此目录的父目录运行：

```powershell
py -3.11 -m unittest discover -s _llm_eval_stage -p "test_*.py" -v
py -3.11 _llm_eval_stage\run_fixture_evaluation.py `
  --fixture-dir 04-meeting-memory\fixtures\meeting-memory-fixture-10 `
  --provider fixture-replay `
  --output $env:TEMP\meeting-llm-fixture-eval.json
```

默认 Provider 是 `fixture-replay`，不会访问网络，也不需要 API Key。它的预期
结果是所有严格字段和证据 F1 为 `1.0`，这只证明评估链路与数据契约正常。

## 调用第三方 SaaS 或用户自己的本地端点

只在明确选择 `openai-compatible` 时联网。可用外部 SaaS：

```powershell
$env:LLM_BASE_URL = "https://api.example.com/v1"
$env:LLM_API_KEY = "<短期密钥>"
$env:LLM_MODEL = "example-model"
$env:LLM_INPUT_USD_PER_1M = "0.15"
$env:LLM_OUTPUT_USD_PER_1M = "0.60"
py -3.11 _llm_eval_stage\run_fixture_evaluation.py `
  --fixture-dir 04-meeting-memory\fixtures\meeting-memory-fixture-10 `
  --provider openai-compatible `
  --output $env:TEMP\meeting-llm-saas-eval.json
```

用户自建 OpenAI-compatible HTTP 服务只需替换地址，核心代码不变：

```powershell
$env:LLM_BASE_URL = "http://127.0.0.1:8000/v1"
$env:LLM_API_KEY = ""              # 局域网服务可以为空
$env:LLM_MODEL = "your-model"
```

请求默认带 `response_format: {"type":"json_object"}`，同时把 schema 写入
用户消息，以兼容不支持 strict schema 的端点。API 返回没有 usage 时，工具会
标记 `usage.estimated=true`，成本只在配置价格时计算，不会伪造真实计费。

## 评估输出

每场会议会记录：

```json
{
  "provider": "openai-compatible",
  "model": "example-model",
  "prompt_version": "meeting-extract-v1",
  "input_hash": "sha256...",
  "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "estimated": false},
  "cost_usd": 0.0001,
  "fields": {
    "topics": {"precision": 1.0, "recall": 0.8, "f1": 0.888889}
  },
  "evidence": {"precision": 1.0, "recall": 1.0, "f1": 1.0}
}
```

`evaluate_predictions()` 可以读取已经落盘的 SaaS 预测，再在不消耗 token 的情况
下重跑评估。这使 Prompt/模型版本对比可重复，也保留当前规则/回放基线作为 CI
门禁。

## 生产边界

LLM Provider 可以负责：摘要、决策/待办/风险候选、Claim 候选、受证据约束的
语言生成。它不能决定：租户隔离、权限、证据是否存在、Claim 的当前/历史状态、
`supersedes` 写入、删除和最终 `no-answer`。这些必须由会议核心的确定性策略和
权威数据库控制。
