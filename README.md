# jjaitech-memory 1.3.0-rc.3

WorkBuddy 的本地个人/工作记忆插件。每人独立使用 AI-Wiki，明确选择后才分享。当前版本重点修复“读过文件但下次找不到”和长时间反复整理。

## Windows 一条命令安装/升级

先安装并登录 WorkBuddy，完成当前任务后退出。打开 **Windows PowerShell** 粘贴：

```powershell
irm https://raw.githubusercontent.com/JachinLan/jjaitech-memory/v1.3.0-rc.3-online.1/install.ps1 | iex
```

阅读本地目录权限和当前云端模型处理说明，输入 `YES`。安装器检查 Python、Node、Git Bash 和实际 WorkBuddy CLI；缺少依赖时停止并说明，不修改企业执行策略。ZIP 使用固定 SHA256 验证。成功后重新打开 WorkBuddy；普通聊天即可使用，无需说“记住”。重复运行可升级/修复，已有 Wiki 保留。自定义路径、关闭、回滚和迁移见 [运维手册](docs/OPERATIONS.md)。

## 本版验收

- Mac：89 项回归测试通过；Windows 最新结果见下方 Actions。
- WorkBuddy 5.5.6 / CLI 2.137.1，当前登录账号真实模型，隔离文件读入、自动结构化写入、原文件移走后跨会话召回通过；本次46.17秒/10.94秒。
- Mac 桌面 Hy4 preview：同一历史问题由原7分43秒降至本次35秒；这是单次测量，不是每次速度保证。
- Windows CI 检查使用官方安装包内真实CLI；不含用户账号、模型调用或真实资料。每位同事仍应完成一次本人账号的虚构资料验收。
- [Windows 回归结果](https://github.com/JachinLan/jjaitech-memory/actions/runs/35206137677)；公开安装命令专项结果见 [Actions](https://github.com/JachinLan/jjaitech-memory/actions/workflows/one-command-smoke.yml)。

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
