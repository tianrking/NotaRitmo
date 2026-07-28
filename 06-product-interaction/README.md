# ⑥ 产品与交互 Product Interaction

## 一句话定位

面向Linux客户端、Android App、Web和外部系统，提供稳定的会议产品能力。

这一块组织前五块的结果和用户操作，但不实现它们的算法。

## 输入

- 用户身份、租户、项目和权限上下文。
- 上传文件、URL、录音或已经存在的媒体引用。
- 会议列表、详情、搜索和导出请求。
- 单会议或跨会议自然语言问题。
- Transcript、Speaker、Artifact和Claim人工修订。
- 声纹、决策、行动项和冲突关系确认。
- Android、Linux、Web或外部系统的回调与幂等键。

统一请求示例：

```json
{
  "request_id": "request_xxx",
  "tenant_id": "tenant_xxx",
  "user_id": "user_xxx",
  "operation": "query",
  "scope": {
    "project_ids": ["android"],
    "meeting_ids": null
  },
  "payload": {
    "query": "Android方案后来发生了什么变化？"
  },
  "idempotency_key": "optional"
}
```

## 输出：ProductResponse

```json
{
  "request_id": "request_xxx",
  "schema_version": "product-response-v1",
  "status": "SUCCEEDED",
  "resource_type": "query_result",
  "resource_id": "query_xxx",
  "data": {},
  "error": null,
  "links": {
    "self": "/queries/query_xxx",
    "meeting": null
  }
}
```

长任务首先返回`Job`，客户端通过查询、事件流或回调获得后续状态；产品响应只暴露稳定
资源和错误合同，不暴露内部Provider、工作流、数据库或模型结构。

## 用户角色

- 个人用户。
- 团队成员。
- 项目管理员。
- 租户管理员。
- 会议所有者。
- 会议参与者。
- 只读查看者。
- 外部API调用方。

## 完整功能点

### 用户、租户和权限

- 注册和登录适配。
- tenant。
- 用户。
- 团队。
- 项目。
- 会议成员。
- 角色和权限。
- 会议可见范围。
- 分享和撤销分享。
- 操作审计。
- 数据导出。
- 删除账户和数据。

### 输入和上传

- 选择本地文件。
- 拖拽上传。
- URL导入。
- YouTube导入。
- Android录音上传。
- 将来的实时录音。
- 批量上传。
- 断点续传。
- 重复文件提示。
- 上传进度。
- 取消上传。
- 失败重试。

### 处理任务

- 创建会议处理任务。
- 查看当前阶段。
- 查看整体进度。
- 媒体错误提示。
- 转写错误提示。
- 模型错误提示。
- 自动重试状态。
- 用户主动重试。
- 取消任务。
- 重新处理指定模块。
- 使用新模型重新分析。
- 保留历史处理版本。

### 会议管理

- 会议列表。
- 项目分组。
- 时间排序。
- 搜索会议。
- 标签。
- 收藏。
- 归档。
- 重命名。
- 删除。
- 批量操作。
- 会议封面和基础信息。
- 参与人。
- 音频时长。
- 处理状态和质量提示。

### Transcript体验

- 逐字稿。
- Speaker分色。
- 点击文字播放原音频。
- 音频播放位置同步高亮。
- 按Speaker筛选。
- 按时间跳转。
- 搜索原文。
- 修改文字。
- 合并或拆分Segment。
- 修改Speaker名称。
- 确认真人身份。
- 查看低置信内容。
- 保留修改历史。

### 单会议结果

- 一句话摘要。
- 完整摘要。
- 章节导航。
- 议题。
- 事实。
- 决策。
- 行动项。
- 风险。
- 未解决问题。
- 人员观点。
- 重点内容。
- 热词。
- 词云。
- 思维导图。
- 树状图。
- 时间线。
- Speaker统计。
- 会议质量。

### 人工修正

- 修正Transcript。
- 修正Speaker。
- 确认或拒绝声纹候选。
- 修正摘要。
- 确认或拒绝决策。
- 修正行动项负责人。
- 修正截止时间。
- 解决冲突Claim。
- 确认旧决策被替代。
- 提交错误反馈。
- 修改记录和回滚。

### 搜索和问答

- 搜索会议标题。
- 搜索原文。
- 搜索决策。
- 搜索行动项。
- 单会议问答。
- 多会议问答。
- 项目范围问答。
- 全部会议问答。
- 查询某人说过什么。
- 查询历史决策变化。
- 查询当前有效方案。
- 多轮对话。
- 明确no-answer。
- 查看召回会议。
- 查看每条引用。
- 播放引用音频。

### 对话历史

- 创建会话。
- 会话标题。
- 多轮上下文。
- 会话与项目或会议范围绑定。
- 引用快照。
- 模型和检索版本记录。
- 删除会话。
- 导出会话。
- 反馈答案是否正确。
- 重新生成。

### 卡片和行动项

- 决策卡片。
- 行动项卡片。
- 风险卡片。
- 未解决问题卡片。
- 证据卡片。
- 用户确认。
- 状态变化。
- 负责人和截止时间。
- 外部任务系统适配器。
- 不强制绑定某一个任务产品。

### 导出和分享

- JSON。
- Markdown。
- PDF。
- 纯文本Transcript。
- SRT / VTT字幕。
- 会议数据包。
- 选定章节导出。
- 带引用摘要。
- 分享链接。
- 链接过期和撤销。
- 导出权限检查。

### 通知和回调

- 处理完成通知。
- 处理失败通知。
- 行动项提醒。
- 后续会议提醒。
- Webhook。
- 外部系统回调。
- 通知幂等。
- 用户通知偏好。

### API

建议资源：

```text
/uploads
/jobs
/meetings
/transcripts
/artifacts
/claims
/search
/queries
/conversations
/citations
/exports
/feedback
```

API只返回稳定产品合同，不返回ASR、LLM、向量库和图数据库的内部结构。

## 数据所有权

本模块权威拥有：

- tenant、用户、团队、项目、会议成员、角色、授权和分享策略。
- 会议产品元数据、上传入口、处理 Job 聚合视图和客户端幂等记录。
- 会话历史、卡片、Todo、通知、Webhook、导出、反馈和人工审核任务。
- 人员主档、声纹授权、Speaker 身份确认动作和操作审计。
- 客户端可见的资源状态、错误映射、能力开关和 API 兼容版本。

本模块不拥有媒体技术元数据、逐字稿内容、单会语义产物、跨会议 Claim 真相或检索索引。
它保存这些资源的稳定 ID 和展示快照，并通过拥有者接口读取或提交修订命令。

## 命令、查询与事件

产品命令：

```text
CreateMeeting
UploadMeetingMedia
StartMeetingProcessing
RetryMeetingStage
SubmitCorrection
ConfirmSpeaker
ApproveClaim
CreateTodo
ExportMeeting
DeleteMeeting
```

产品查询：

```text
ListMeetings
GetMeeting
GetJob
GetTranscript
GetArtifacts
Search
Query
GetConversation
GetCitationPlayback
```

产品事件：

```text
MeetingCreated
MeetingProcessingStarted
MeetingReady
MeetingPartiallyReady
CorrectionSubmitted
ReviewCompleted
ExportReady
MeetingDeletionCompleted
```

产品事件是用户体验层的聚合事件，不替代前五块的领域事件。`MeetingReady` 必须指向各模块
具体版本，不能只用一个布尔值隐藏部分失败或数据过期。

## 编排职责

本模块负责：

- 建立请求身份、租户、项目、会议和权限上下文。
- 接受用户意图，向正确模块发送命令或查询。
- 聚合各模块 Job 状态，对客户端提供稳定进度和错误。
- 组织人工修订工作流，并等待拥有数据的模块确认新版本。
- 把查询结果、卡片和播放链接转换为客户端稳定资源。

本模块不负责：

- 实现媒体、ASR、Diarization、LLM 提取、Claim 判定或 RAG 算法。
- 直接重试未知错误；重试策略来自目标模块和执行面。
- 通过写数据库绕过模块命令。
- 把聊天内容、用户编辑或 Todo 静默升级为会议事实。

## 依赖规则

- Product 可以调用前五块的稳定命令和查询，但不能访问其私有表或 Provider。
- 每个请求建立 `TenantScope`；下游仍需独立执行权限约束。
- 领域事件通过 Outbox、消息系统或本地事件总线消费，传输技术不进入 API 合同。
- 客户端只依赖产品资源和错误码，内部模块拆分或 Provider 替换不要求升级 App。
- 删除先冻结外部访问，再编排各模块删除并汇总结果；任何残留都必须可审计。

## 错误分类

- 参数、格式和状态不允许：返回稳定 4xx 业务错误，不创建无效后台任务。
- 身份或权限失败：拒绝并审计，不泄露资源是否存在。
- 某处理模块失败：会议进入 `PARTIAL` 或 `FAILED`，列出可用能力和可重试阶段。
- 查询生成失败：退化到 Search 证据列表；引用验证失败则隐藏对应结论。
- 通知、导出或外部 Todo 失败：不回滚会议知识，只重试对应集成。
- 客户端断网：上传、命令和修订依赖幂等键恢复，不能重复创建会议。

## 实时与离线边界

- 产品层可统一展示会中 partial 与会后 final，但视觉和 API 状态必须明确区分。
- 会中字幕、滚动摘要和待办候选可以被后续 Delta 修订。
- 会后 Finalize 后锁定正式输入版本，运行全量理解、Memory 和索引更新。
- Android 或 Linux 客户端不处理 Provider 临时 ID，统一消费产品层稳定 ID 与映射事件。

## 状态机

```text
CREATED -> UPLOADING -> QUEUED -> PROCESSING -> READY
                                      ├──> PARTIAL
                                      ├──> FAILED
                                      └──> CANCELLED
DELETION_PENDING -> DELETED
```

- `READY`必须对应具体处理版本。
- `PARTIAL`表示部分能力可用，并列出失败模块。
- `FAILED`给出稳定错误码、错误阶段和是否可以重试。

## 可插拔点

```text
IdentityProvider
  - 自建账号
  - OIDC
  - 企业身份系统

Client
  - Linux
  - Android
  - Web
  - External API

TaskIntegration
  - Disabled
  - 通用Webhook
  - 第三方任务系统

ExportProvider
  - JSON
  - Markdown
  - PDF

NotificationProvider
  - Push
  - Email
  - Webhook
```

## 重要边界

- 不直接调用特定ASR Provider。
- 不直接调用特定LLM。
- 不直接查询向量库。
- 不直接读取图数据库。
- 不向客户端返回Provider原始JSON。
- 不自己判断跨会议事实是否有效。
- 只调用前五块的稳定接口。
- 更换任何内部模型不要求发布新客户端。

## 非功能需求

- API版本兼容。
- 请求幂等。
- 稳定错误码。
- 分页。
- 限流。
- 移动网络重试。
- 上传恢复。
- tenant隔离。
- 最小权限。
- 审计日志。
- 删除传播。
- 隐私导出。
- 指标和链路追踪。
- 服务降级。
- 多语言界面准备。

## 研究重点

- Linux先行时最小产品闭环。
- Android上传、查看、播放和问答所需最小API。
- 复杂内部流程如何呈现为简单用户状态。
- 人工修订如何回流到Transcript、Artifact和Memory。
- 引用播放的最佳交互。
- 单会议和跨会议问答如何共用一个入口。
- 产品反馈如何转化为各模块黄金数据。

## 评测指标

- 上传成功率。
- 任务完成率。
- 首个可用结果时间。
- 查询端到端延迟。
- 引用播放成功率。
- 用户修订完成率。
- 错误可理解率。
- 移动网络恢复成功率。
- 权限泄漏数量，目标为零。
- 删除传播完整率。
- 用户从上传到获得结果的完成率。

## 完成标准

- 固定面向客户端的资源和错误合同。
- Linux客户端能够完成上传、等待、查看、修正和问答。
- Android只依赖稳定产品API。
- 更换ASR、LLM、Memory和向量库不改变客户端合同。
- 单会与跨会查询均可显示证据并播放原音频。
- 双tenant和越权访问测试完整通过。
- 删除、导出、分享和撤销均有端到端验收。
- 产品反馈能够进入对应模块的评测数据集。
