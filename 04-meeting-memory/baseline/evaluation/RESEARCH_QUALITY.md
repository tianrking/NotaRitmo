# 研究质量评估

固定 Fixture 是唯一回归输入。每个 LLM、Embedding、Reranker、Repository 或 Retriever
组合都必须在同一组会议和查询上比较，不把回放 Gold 当作模型质量。

运行：

```bash
python3 evaluation/run_research_quality.py \\
  --fixture-dir ../fixtures/meeting-memory-fixture-10
```

报告包含：

- Recall@1/3/5
- MRR
- nDCG@1/3/5
- 会议定位和证据定位
- 引用可播放结构
- no-answer accuracy
- 当前/历史状态命中
- 跨会议命中
- 租户泄漏数量

当前离线词法基线用于发现回归，不代表生产质量。真实第三方 LLM 评估使用
`evaluation/run_fixture_evaluation.py --provider openai-compatible`，并记录 Provider、
模型、Prompt 版本、输入哈希、Token、延迟和成本。
