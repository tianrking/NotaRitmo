# 离线 Meeting Memory 基线

这是 Fixture-10 的最小可运行基线，不依赖外部 LLM、PostgreSQL、Graphiti、Mem0 或 RAGFlow。

## 运行

在本目录执行：

    python run_fixture.py

运行测试：

    python -m unittest discover -s . -p 'test_*.py'

输出包括：

- 每场会议的 MeetingArtifact。
- Candidate Claim 和 active/superseded 状态。
- 关键词和 Token 相似度检索。
- 会议、片段、Speaker、时间点引用。
- 当前状态和历史状态查询。
- no-answer。
- tenant_id 过滤。

## 明确边界

这里的 FixtureRuleExtractor 只是可重复的离线基线，用规则模拟单会议理解，目的是先验证数据协议、证据、Claim 状态和查询流程。它不是生产抽取器。

下一步替换位置：

- FixtureRuleExtractor → Python LLM/结构化抽取 Worker。
- MemoryStore → PostgreSQL Claim Ledger。
- lexical_score → PostgreSQL FTS + pgvector + reranker。
- answer → 检索证据通过校验后再调用 LLM 生成自然语言。

规则、数据库和权限不会交给 LLM。

## 可插拔核心

当前基线已经提供一个组合式入口 MeetingMemoryService。它将核心职责拆成五个协议：

- Extractor：把 TranscriptBundle 转成带证据的 MeetingArtifact。
- Repository：保存会议、片段、Artifact、Claim 和 active/superseded 状态。
- Retriever：按租户返回片段和 Claim 候选。
- Answerer：执行 no-answer 门槛、引用拼装和答案生成。
- LLMProvider：可选的模型接口，可指向 SaaS 或用户自己的 OpenAI-compatible API。

默认组合仍然完全离线：

    FixtureRuleExtractor
        -> MemoryStore (in-memory)
        -> LexicalRetriever
        -> TemplateAnswerer

OfflineLLMProvider 不会发起网络请求；未显式配置模型时调用它会抛出明确错误。GroundedLLMAnswerer 只把已通过租户过滤和 no-answer 门槛的证据片段交给 LLM，权限、状态、证据和拒答仍由确定性代码控制。

示例：

    from service import MeetingMemoryService

    service = MeetingMemoryService.from_fixture_root(FIXTURE_ROOT)
    result = service.answer("当前生产检索的主链路是什么？", "tenant_alpha", "current_state")

以后替换实现时只需注入同一协议：

    service = MeetingMemoryService(
        extractor=MyLLMExtractor(),
        repository=PostgresRepository(...),
        retriever=HybridRetriever(...),
        answerer=GroundedLLMAnswerer(MyLLMProvider()),
    )

这组接口是第一轮编排边界；PostgreSQL、pgvector 和真实 SaaS Provider 尚未在离线基线中实现。
Windows 与 WSL 开发入口、路径和边界见 [DEVELOPMENT_WINDOWS.md](DEVELOPMENT_WINDOWS.md)。
