# 公开访谈模拟 ASR 语料验收

评测时间：2026-07-27  
语料版本：`public-interviews-v1`  
运行环境：本地 Docker Compose NotaRitmo，`LLM_ENABLED=false`

## 目的

验证多篇真实来源访谈在被改写为“听悟式 ASR 结果”后，NotaRitmo 是否能够完成：

1. Speaker、句级时间、置信度的 Canonical 标准化；
2. 13 类会议产物和带证据记忆生成；
3. 单篇精确检索和语义检索；
4. 同领域跨篇召回；
5. 不同领域干扰项区分；
6. Agent 跨篇问答和原文时间点引用；
7. 无答案问题的拒答。

语料只使用公开访谈中的事实制作简短中文改写，不复制整篇原文。

## 来源

| Key | 访谈 | 主题 | 来源 |
| --- | --- | --- | --- |
| `nasa_shirley` | Donna Shirley 谈火星车与机器人 AI | AI / 机器人 | NASA Oral History |
| `nasa_erb` | Bryan Erb 谈遥感、自动化与空间站 | AI / 自动化 | NASA JSC Oral History |
| `nih_horigan` | John Horigan 谈 All of Us | 精准医疗 / 数据 | NIH Oral History |
| `nih_grady` | Christine Grady 谈临床生物伦理 | 生物伦理 | NIH Oral History |
| `npc_solar` | 黄鸣谈新能源与太阳能产业 | 新能源 | 中国人大网在线访谈 |
| `ajph_kasich` | John Kasich 谈公共卫生 | 公共卫生 | AJPH / PMC |

测试脚本中的每篇语料包含 9–10 个问答片段、两名 Speaker、单调递增时间戳和模拟
置信度。来源 URL 保存在 Meeting 的 `audio_uri` 和模拟原始结果的 `_Source` 中。

## 结构验收

六篇访谈全部通过：

| 指标 | 结果 |
| --- | --- |
| Meeting READY | 6 / 6 |
| Graph READY | 6 / 6 |
| Temporal 七阶段完成 | 6 / 6 |
| 13 类 Artifact 完整 | 6 / 6 |
| Segment / Word | 58 / 58 |
| Memory | 231 |
| 无证据 Memory | 0 |

各会议 Memory 数量为 37、39、39、38、39、39。

## 检索评测

### 汇总

| 指标 | 结果 |
| --- | --- |
| 正向 Top-1 Accuracy | 8 / 9 = 88.89% |
| Mean Recall@K | 88.89% |
| 跨 AI 访谈召回 | 2 / 2 |
| 跨健康访谈召回 | 3 / 3 |
| 无答案拒答 | 失败 |

### 逐项

| 用例 | 期望 | 实际 Top-1 | 结果 |
| --- | --- | --- | --- |
| 像昆虫一样分层避障 | Shirley | Shirley | 通过 |
| Tooth 控制逻辑 + Rocky 车体 | Shirley | Shirley | 通过 |
| 空间站推动自动化和机器人 | Erb | Shirley | **失败** |
| 七十万参与者、目标一百万 | Horigan | Horigan | 通过 |
| 资源分配、临终照护、公共卫生平衡 | Grady | Grady | 通过 |
| 太阳能热水器占比 76% | 黄鸣 | 黄鸣 | 通过 |
| 公共卫生像持续缴费的保险 | Kasich | Kasich | 通过 |
| AI / 机器人 / 自动化跨篇召回 | Shirley + Erb | 两篇均命中 | 通过 |
| 健康 / 伦理 / 公共卫生跨篇召回 | 三篇健康访谈 | 三篇均命中 | 通过 |
| K6 OTA 灰度分包（语料中不存在） | 空结果 | 返回六篇最近邻 | **失败** |

## Agent 验收

三组 Agent 查询都满足：

- 预期访谈出现在引用集合；
- `grounded=true`；
- `unresolved_memory_evidence=[]`；
- 每条引用包含 Meeting、Speaker、Segment、起止时间和原文。

但 `LLM_ENABLED=false` 时，Agent 主要输出排序后的证据或结构化列表：

- NASA 跨篇问题能同时找到 Shirley 和 Erb；
- 健康跨篇问题能覆盖 Horigan、Grady 和 Kasich；
- 太阳能占比问题第一条精确命中 `17250–21100ms`；
- 不能把多篇证据凝练成自然的比较结论。

## 暴露的问题

### P0：没有“无答案”拒答能力

`/v1/search` 只要启用向量检索，就会返回固定数量的最近邻。即使问题是语料中完全不存在的
“K6 OTA 灰度分包”，仍会返回六篇访谈。

需要：

1. 记录真实 cosine distance / similarity，而不是用语义排名倒数充当分数；
2. 设置经过标注集校准的绝对阈值；
3. lexical 和 semantic 都弱时返回空集合；
4. Agent 在证据不足时明确拒答。

### P0：同领域相似访谈存在 Top-1 竞争

“空间站为什么被当作推动自动化和机器人技术的载体”应命中 Erb，但 Shirley 的机器人
访谈排在第一。系统虽然在第二名找到了 Erb，但 Meeting 定位不够精确。

需要：

1. 精确实体和短语加权，如“空间站”；
2. 标题、主题、项目字段参与排序；
3. 增加 cross-encoder reranker；
4. 对 Segment 分数做 Meeting 级聚合，而不是只取每个会议第一次出现的位置。

### P1：热词质量偏低

当前 Top Topics 包含“采访者、什么、怎样、工作、早期”等泛词。说明只靠 Jieba 频次不能
形成产品级热词。

需要：

1. 去除角色前缀；
2. 扩充访谈停用词；
3. 使用跨语料 TF-IDF 或 KeyBERT 类关键词；
4. 合并同义主题和命名实体。

### P1：规则提取把问题当成大量 open question

六篇语料产生 16 条未决问题，主要来自采访者问句，并不代表会议真正的待解决事项。

需要区分：

- 采访问题；
- 会议未决事项；
- 修辞疑问；
- 已经被后续回答的问题。

### P1：无 LLM 时只有证据列表

当前路径适合验证检索和证据链，但不代表最终用户体验。真实产品需要在授权、截断后的证据
上调用可替换 LLM，生成跨篇比较，并继续返回同样的 Segment 引用。

## 结论

本轮证明：

- 多篇访谈能够完整进入 NotaRitmo；
- 单篇事实定位、跨篇主题召回、证据时间点均已成立；
- 当前正向检索达到了可用原型水平；
- 无答案拒答、同领域精排、访谈问题识别和自然语言归纳仍未达到生产水平。

重复运行：

```bash
docker compose run --rm --no-deps \
  -e MEETING_API_BASE=http://api:4200 \
  api python scripts/interview_corpus_acceptance.py
```

脚本默认复用同版本、同标题且已经 READY 的语料，避免重复导入；传 `--force` 才会新建。
