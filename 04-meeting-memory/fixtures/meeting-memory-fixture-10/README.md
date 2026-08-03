# Meeting Memory Fixture-10

这是一套完全自制的中文会议测试数据，用于在没有真实音频和 ASR 的情况下验证 NotaRitmo 的会议理解、会议记忆和检索架构。

## 数据范围

- 10 场会议，时间跨度为 2026-07-01 至 2026-07-10。
- 会议 001 至 009 属于 tenant_alpha，围绕同一个星河会议平台项目连续演化。
- 会议 010 属于 tenant_beta，是无关的蓝海客户项目，用于验证租户隔离和 no-answer。
- 每场会议约 5 分钟，6 个带逻辑时间戳的发言片段，3 个 Speaker。
- 时间戳是合成的逻辑时间，不用于验证 ASR、VAD 或真实说话人分离。
- 所有摘要、决策、行动项和查询答案都以 gold 文件提供预期引用。

## 文件

- meetings.jsonl：会议元数据。
- segments.jsonl：标准 TranscriptBundle 片段。
- gold_artifacts.jsonl：单会议理解结果应覆盖的主题、决策、待办和风险。
- gold_claims.jsonl：跨会议 Claim、当前状态和 supersedes 关系。
- queries.jsonl：单会议、跨会议、当前状态、历史状态、拒答和租户隔离查询。
- validate_fixture.py：只使用 Python 标准库的完整性检查器。

## 运行校验

在本目录执行：

    python validate_fixture.py

预期输出：

    fixture valid: 10 meetings, 60 segments, 18 claims, 18 queries

## 使用边界

这套 Fixture 先只验证：

1. 输入标准化。
2. 单会议摘要、章节、事实、决策、行动项和风险抽取。
3. 证据 segment_id、speaker_id 和时间点绑定。
4. Claim 的 active、superseded 和历史关系。
5. PostgreSQL FTS、pgvector 和混合检索。
6. 跨会议查询、引用和 no-answer。
7. tenant_id 过滤和跨租户不可见。

它不验证音频解码、ASR 字准率、说话人分离、声纹识别或真实音频播放。
