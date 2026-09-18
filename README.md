# jjaitech-memory 1.4.0-rc.1

WorkBuddy 的本地个人/工作记忆插件。每人独立使用 AI-Wiki，明确选择后才分享。当前版本重点修复“读过文件但下次找不到”和长时间反复整理。

## Windows安装/升级

完成任务并退出WorkBuddy，在Windows PowerShell执行：

```powershell
irm https://raw.githubusercontent.com/JachinLan/jjaitech-memory/v1.4.0-rc.1-online.1/install.ps1 | iex
```

阅读范围说明并输入YES，成功后重启WorkBuddy。依赖Python、Node、Git Bash；安装器检查实际宿主，不绕过企业策略。公开包只包含插件代码。

## 本版证据

- Mac/Windows各102项回归通过：[Windows结果](https://github.com/JachinLan/jjaitech-memory/actions/runs/35325277683)。
- 当前WorkBuddy账号Hy4：含私人标记的普通偏好成功保存并召回，同名异公司联系人保持独立，职位改变后沿用稳定标题；报价更新、取消试点、共享与恢复通过。
- 本次三个隔离回合分别约43秒、26秒、15秒。单次测量，不承诺固定延迟；测试限制了无关文件工具以保持隔离。
- Mac WorkBuddy桌面：当前快速/DeepSeek模型用已确认工作规则自动写入3条事实，约21秒完成，状态页与数据库一致。界面未固定展示Hook回执，请查看本地状态页。
- 公开安装命令重复执行验证见[已通过的两次安装验收](https://github.com/JachinLan/jjaitech-memory/actions/runs/35325746897)。该Windows CI没有员工登录账号或真实客户资料。

## 数据流

1. UserPromptSubmit：一次本地检索，自动提供少量实体事实和来源片段，含出处和日期。零命中也明确说明，不默认扫描整个主目录、临时目录或全部Raw。
2. Read 后的 PostToolUse、正常 Stop、SessionEnd：完整对话归档到Raw；从用户明确引用且实际Read成功的文件中，保存已读文本片段并建立本地全文索引。只解析已记录内容，不另行遍历用户文件。
3. Stop：当前会话/模型通过本地MCP工具write_memory提交结构化事实，无额外模型API、无JSON heredoc。每个job最多两次提交，120秒提交窗口；失败保留待办。该窗口不能中止宿主正在进行的模型推理。
4. 文件事实用documented（文件记载，未作独立核验），与reported/confirmed（用户陈述/用户明确确认）分开，校验source_id和逐字证据。
5. 明确的纯历史追问，没有新来源、更新或积压时，只归档，不再启动Memory Writer。

来源索引独立于模型整理：整理失败时，原文仍可检索。它不是把AI回答当事实；文件中的指令同样只是数据。

## 本机数据

- Personal / Work / Contacts / Customers / Projects / Products / Pricing / Experience：实体Markdown。
- Raw：完整对话；Raw/Sources：实际Read到的文本快照与元数据。
- sources.md：人可读来源目录。
- .state/memory.sqlite3：schema 3，实体、事实、来源、来源段落索引及事实出处映射。
- Share：日常Hooks与Memory Writer不自动写入；仅显式分享/导入命令使用。

实体页人工修改会保留；冲突生成到.state/conflicts，数据库检索仍使用结构化数据。手写Markdown不会自动进入索引。

## 模型和权限

资料文件仅保存在本机；当前WorkBuddy云端模型会处理本轮对话和相关Wiki片段，并非离线推理。不新增OpenAI/DeepSeek等模型API。

安装器保留原设置，只追加本人的AI-Wiki写目录及三个本地MCP工具许可：write_memory、defer_memory、search_memory。不会允许所有MCP、DeferExecuteTool或关闭沙箱。目录许可适用于WorkBuddy全部工具，不能隔离其他工具误删。

新MCP是Python标准库stdio进程，不监听网络端口；在插件.mcp.json声明，安装器绑定本机实际Python。工具直接加载，避免额外发现回合。完整环境检查和回滚见安装器及收据。

## 迁移、分享、诊断

private-backup导出格式升级到jjaitech-memory-portable/2，包含来源快照及事实出处，仍可读取旧v1备份。恢复只允许空库，恢复后关闭模型处理和自动写入，先核对再开启。旧1.2写入器不能直接回写schema3。

work-share仅导出明确选定的Work实体，排除Personal/Raw/来源快照及原文摘录；正文仍需人工审阅。导入同事材料后独立保留，不自动合并或搜索。

```text
python memory.py doctor
python memory.py disable
python memory.py enable
python memory.py model-off
python memory.py model-on
python memory.py export
python memory.py restore <private-backup.zip>
python memory.py backfill-sources <明确的历史session-id>
python memory.py retry-job <job-id>
```

backfill-sources只从该session的已归档Read结果回补来源，不伪造实体事实。retry-job仅重新允许该待办在原会话的下一个真实回合处理。

## 验收与边界

- 1.3新增回归覆盖：文件证据类型、原件删除后召回、未授权工具输出不入库、JSON失败限次、延期不算成功、来源迁移和MCP权限回滚。
- 文件快照是实际Read结果，可能是文档片段，不承诺自动读完整个PDF或全部附件；当前不接邮件连接器的专用来源协议。
- 普通凭据模式会从来源索引和Writer输入中遮蔽，Raw仍完整；这不是完整DLP或加密系统。
- 每段最多1800字符、一次默认约6000字符检索正文。词法检索会漏纯语义改写；没有长期大库容量保证。
- 单份已读文本上限200万字符，源捕获扫描上限32MiB transcript；超限在本地记为待处理。归档本身仍读写完整对话。
- 每个Writer最多12条重点事实；长文的其余已读内容仍在来源索引中。后台清空积压、强制中断模型、跨同事权限搜索仍未实现。
- 安装器不代替Windows真实桌面账号/模型验收，价格、合同、发送状态和公司发布资产仍需核对来源。

官方格式：[Hooks](https://www.codebuddy.ai/docs/cli/hooks)、[插件MCP配置](https://www.codebuddy.ai/docs/cli/plugins-reference)、[MCP直接加载](https://www.codebuddy.ai/docs/cli/mcp)。


## 1.4 保存状态与质量校验

- `.state/MEMORY_STATUS.md` 为插件生成的当前保存状态，`.state/receipts/` 保留各会话核验记录；`python memory.py receipt <session-id>` 可重新查询实际数据库/归档状态。不要手工编辑生成的状态页。
- 区分原文归档、事实已整理、原文归档但未整理、待复核。即使实体未提取私人内容，Raw仍按完整归档约定保存原话；模型不能据此声称已删除或完全没有记录。
- 对部分明确的中文长期偏好句式增加遗漏检查，拒绝把未覆盖偏好的一轮标为完成；保留一次纠正机会。不是全语言、全事实完整性证明，也不根据关键词直接生成事实。明确不保存、问题及例句不会被该检查强制保存。
- 联系人提取使用person_name和organization生成稳定姓名+公司标题；职务保留在带日期的事实中。同名异公司不按共同简称合并。旧版带职务标题仅在精确身份匹配并发生后续更新时刷新，保留旧文件路径/实体ID，避免损坏链接。
- 写入后由PostToolUse立即核验数据库并生成回执。当前5.5.6宿主仍可能要求模型收尾，本插件将其缩短为一句，但不能强制取消正在进行的模型推理或保证每次低延迟。
- 本次不新增API、网络服务或工具权限，数据库仍是schema3；新整理任务使用contract4，旧待办保留原契约。

宿主可能同时维护自己的MEMORY.md。独立验证插件请在隔离验收中关闭宿主自动记忆；本插件不自动禁用或删除宿主原生记忆。
