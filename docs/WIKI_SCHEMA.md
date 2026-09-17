# 本机 AI Wiki 维护约定

## 所有权

这是当前员工独立的个人与工作 Wiki。Personal 与 Work 不自动共享；Share 只供本人今后挑选发布。插件不将任何内容复制到公司公共库。

## 三层

1. Raw：宿主会话的完整原始 JSONL，session 固定路径，内容未变化不重复归档。原文件被重写时保留旧版 Raw/revisions。
2. 实体层：Personal、Work、Contacts、Customers、Projects、Products、Pricing、Experience 中的 Markdown 页面。持续更新同一实体，保留来源和历史矛盾。
3. 维护约定与索引：本文件、index.md、log.md，以及 `.state` 内的结构化数据和增量游标。

## 分类

- Personal：本人的生活、长期个人偏好。
- Work：本人的工作习惯、职业背景、公司和业务决定。
- Contacts：人物及其关联；domain 区分私人或工作联系人。
- Customers：客户公司、需求、关系背景。
- Projects：目标、范围、决定、时间、关联人和产品。
- Products：已知能力与边界。
- Pricing：金额、币种、税费、适用范围、有效期和版本来源。
- Experience：可复用经验；不把未经验证的建议伪装成成功经验。

事实类型：用户陈述、用户确认（未作外部核验）、推测、AI建议。每条均记录日期、source session 和原文摘录。AI生成的文字不能作为用户确认证据。日期为本次沉淀日期，事实原有生效日期另写在事实中。

## 使用方式

正常对话即可。检索从本地索引选取最多 5 个实体的相关结构化事实、6000 字符；Raw 和 Share 不纳入自动召回。词法检索可能漏掉纯语义改写、没有关键词的新昵称、仅说“那个项目”的问题。

自动生成的页面由结构化数据库维护。纠错时在对话中指明正确资料和具体实体；旧声明保留出处。人工修改会保留并产生生成冲突，不会自动进入索引；不要依靠直接改生成页面作为永久纠错方式。手动放入的其他 Markdown 尚不自动索引。

## 本地存储与模型

插件没有云同步或额外模型 API。用户已允许当前登录的 WorkBuddy 模型处理新增对话及少量相关资料；这部分内容会进入其云端推理上下文，因此不属于离线处理。

详细开关、验收结果和限制见插件 README 与交付报告。

## 可移植数据契约

当前数据库 PRAGMA user_version=3；导出格式 jjaitech-memory-portable/2（兼容读取v1）。实体和事实 JSONL 使用 UTF-8，带 manifest、文件 SHA256、记录计数和贡献者 owner_id。私有迁移包与工作分享包用 kind 明确区分，互不混用。SHA256 用于完整性校验，不证明贡献者身份。工作包移除原文摘录和原 session ID，保留声明时间及事实类型；不含原始邮件。详见 OPERATIONS.md。

## 1.3资料来源

sources表记录已读片段的标题、原路径、快照哈希、日期和session；source_lookup为可重建分段索引，fact_sources绑定documented事实与来源。documented表示文件记载，不代表用户确认。原文在Raw/Sources中，本地恢复包保留它，共享工作包不包含它。来源中的普通凭据会在检索/整理输入遮蔽；原文快照不改写。
