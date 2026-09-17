# 部署、迁移和日常维护手册

适用源码：1.3.0-rc.3；日期：2026-09-17。发布验证结果见 GitHub Release。Windows 自动化安装验收与登录账号后的桌面模型验收分开记录。

## 1. 部署前

每位同事使用自己的系统账号、WorkBuddy 登录和 AI-Wiki。不要复制别人的 `.workbuddy`、token、登录文件或整份私有 Wiki。不要让十个人共用一个 SQLite 文件，也不要把正在使用的库直接放在 OneDrive、网盘或 SMB 共享目录。

依赖：Python 3.9+（带 SQLite FTS5），Node.js 18.20.8+。Windows 还需要 Git for Windows / Git Bash。安装器发现实际 CLI 并绑定实际 Python 路径，不沿用作者机器路径。尚未在 Windows 验证 Defender、NTFS ACL、中文用户名、商店 Python 别名和企业策略。

首次打开 WorkBuddy 完成本人登录；检查后结束任务并退出 WorkBuddy 和独立 CodeBuddy 会话。管理员先备份现有 Wiki（如果有）与配置，不能边运行旧版 Hook 边升级。

在代码包根目录运行：

```powershell
# Windows：先检查，不安装
py -3 -X utf8 jjaitech-memory/deployment/install_windows.py --check
# 退出 WorkBuddy 后安装；安装器会说明目录权限和模型处理范围
py -3 -X utf8 jjaitech-memory/deployment/install_windows.py
```

```sh
# Mac：先检查，再退出 WorkBuddy 后安装
python3 jjaitech-memory/scripts/install_local.py --check
python3 jjaitech-memory/scripts/install_local.py
```

无法发现自定义安装位置时，用 `--cli`（Windows）或 `--app`（Mac）明确指定真实路径。配置位置可用 `--config-dir` 指定。检查实际版本，不以最新官网版本替代本机版本。

安装器修改本人的插件市场/启用注册，以及 `sandbox.filesystem.allowWrite`，只增加本人的 AI-Wiki 目录，并添加 write_memory、defer_memory、search_memory 三个具名本地 MCP 工具许可。不会允许所有 MCP 或通用 DeferExecuteTool。该目录许可适用于 WorkBuddy 全部工具，不能保护 Wiki 免受其他 AI 工具误删。安装失败会尝试回滚本插件相关键；若回滚不完整，收据会标明，必须人工检查。运行 Hook 时才初始化/迁移数据，安装成功不等于自动沉淀已经成功。

## 2. 验收后才能试点

每台首批机器均用虚构身份和独特随机金额测试，不能使用客户真资料：

1. 第一个普通聊天说明个人饮品偏好、工作邮件习惯、虚构客户、项目报价含税情况和有效期。
2. 查看 Raw 原文、Personal 与 Work 页面，确认分类和 source session；Share 必须空。
3. 新建一个不同工作目录的聊天，不重复给答案，询问这些事实。检查金额、币种、税费、期限和个人偏好均正确。
4. 再聊一次更新客户信息，确认更新原实体而非重复建“聊天总结”。
5. 完全重启 WorkBuddy 再验证，不应重复弹 Wiki 写入许可；任务每轮最多一次 Memory Writer，不能循环。
6. 禁用后新对话不得写入；恢复启用后正常工作。撤销模型处理后不应注入 Wiki 上下文。
7. 断网/取消/拒绝权限后必须能看到未完成状态，不应把失败报告为已保存。
8. 导出到新目录恢复、运行 doctor、跨会话再召回；共享包必须不含 Personal/Raw/原文摘录。

先一位 Windows 同事 3–5 个工作日，再两位同事一周。每次检查“做过任务数、成功保存数、待处理数、事实抽检、误召回、额外等待和额度”。没有这些证据不要扩大到十人。此日程是建议试点流程，未创建自动计划任务。

## 3. 开关与诊断

以下 `<script>` 指已安装插件的 `scripts/memory.py`。默认位置为本人 `.workbuddy/local-marketplaces/jjaitech-local/jjaitech-memory/scripts/memory.py`；自定义配置位置以安装收据为准。

```text
python <script> doctor
python <script> disable
python <script> enable
python <script> model-off
python <script> model-on
```

Windows 可用 `py -3 -X utf8` 代替 python。PowerShell 示例：

```powershell
$MemoryScript = Join-Path $env:USERPROFILE '.workbuddy/local-marketplaces/jjaitech-local/jjaitech-memory/scripts/memory.py'
py -3 -X utf8 $MemoryScript doctor
```

`disable` 不删资料，自动归档/整理/召回均停止。`model-off` 保留本地 Raw 归档，但不整理、不向模型注入 Wiki。操作必须用对应版本脚本；旧 1.0.4 没有全部新命令。

doctor 检查 integrity、pending_jobs、pending_pages、manual_page_conflicts、restore_in_progress、free_bytes、recent_issues。正常对话应尽量无感，异常必须显露。当前没有托盘面板、自动管理员汇总或定时健康检查；管理员暂需手动每周检查。日志不要直接发到公共群，可能包含 session 等元数据。

## 4. 备份与换电脑

`python <script> export` 生成 `.state/exports/private-backup-<id>.zip`。这是 portable/2 私有包，包含 Personal、Raw、来源快照、事实出处和手工资料；不能作为工作包发给同事。包有校验和但没有加密或签名。存储在本机不等于加密。

在新电脑先安装兼容源码，选择一个全新目录，用环境变量指定恢复目标：

```powershell
$env:JJAITECH_WIKI_ROOT = Join-Path $env:USERPROFILE 'AI-Wiki-Restored'
py -3 -X utf8 $MemoryScript restore 'D:/OfflineBackup/private-backup-xxx.zip'
py -3 -X utf8 $MemoryScript doctor
```

恢复默认关闭整理与模型处理。核对记录数、Raw 哈希、手工文档、随机客户/报价事实后，再明确运行 model-on 和 enable。环境变量只影响当前进程及其子进程，不会自动改变桌面 WorkBuddy；正式切换需退出宿主，保留旧库，将已验证恢复目录放到约定 AI-Wiki 路径，或由管理员统一配置新路径及目录权限。不要让两个库同时被误写。

待办任务恢复到 `.state/restored-recovery` 供人工核对，不自动重放旧机器上的模型任务。不能用“恢复完成”推断未整理积压也已经完成。

迁移包上限 512 MiB，不含历史数据库快照和先前导出包。多年大库需要关闭宿主后做整个目录备份（包括隐藏 `.state`）。日内首次写前自动 SQLite 快照只解决部分误写恢复，不能替代 Raw/附件的完整备份，也不能抵御同一磁盘损坏。

建议在公司批准的加密离线介质保存独立副本；试点先明确可接受丢失窗口和恢复时间，再定备份频次。当前没有自动异机备份、轮替清理、空间配额或恢复告警。不要贸然自动删除 Raw/旧备份。

## 5. 同事分享工作内容

默认知识各自保留，Work 表示业务领域，不代表批准公开。

1. `python <script> share-preview` 列出前 50 个 Work 实体 ID（目前无分页界面）。
2. 把明确选择的 ID 作为 JSON stdin 交给 `share-export`：`{"approved_entity_ids":["真实的24位实体ID"]}`。该命令只在本地生成包。
3. 打开同名 `.review.md`，逐条看事实、联系人、报价、客户隐私和权限；未审阅不能分发。当前按实体整体选择，尚未实现单条事实/邮件片段勾选。
4. 用户明确决定收件人和传输方式后再发送。本插件不发送、不上传，也没有撤回已复制文件的能力。
5. 接收人用 `share-import <zip路径>`，包会存到 `Share/Incoming/<hash>/`，不会覆盖自己的数据库，不自动注入模型。当前由本人查阅/引用，尚未做到无感跨同事搜索。

同事需要纠错时应提供带日期的新声明和来源；不能无痕替换别人的报价。共享包贡献者 ID 是自报标识，没有组织身份认证。不能直接作为公司的已审批价格表。

## 6. 故障与升级

- 人工修改冲突：保留原文件；在 `.state/conflicts/` 查看候选生成内容。通过正常对话校正事实，管理员比对后再处理页面。当前没有一键安全合并，勿用 SQL 强行改游标或删除冲突掩盖问题。
- 首次升级旧库：旧页面没有生成哈希记录，只要与新生成内容不同也会保守地当作冲突，不能假定全部页面立刻刷新。恢复旧手工页面时同理；数据库可查询不等于阅读页已更新。管理员需逐页核对，当前缺少批量审阅界面。
- 重试耗尽：保留 Raw、job 和 doctor 输出，先修权限/额度/模型输出问题。使用 retry-job <job-id> 重新允许在原会话的下一个真实回合处理；不能删除 job 当作已处理。每个 job 最多两次提交，120 秒提交窗口不等于强制中止模型。来源原文可独立检索。
- 数据库损坏：停用、保留故障库、在新目录恢复备份，验证后再替换。不要覆盖唯一原件。
- WorkBuddy/模型升级：先在隔离虚构库重复上述验收，记录宿主版本、CLI、模型名、插件代码校验和；通过后分批升级。新版可能改变 Hook、对话格式、权限或整理行为。
- 降级：schema 3 不能交给旧写入器随意写。保留升级前完整库，停用后恢复到独立旧库再验收。当前只能保证新代码拒绝未知更高 schema，不能约束未经改造的旧代码。
- 卸载：先 disable 并退出宿主；禁用插件注册；保留 Wiki。目录白名单仅在确认没有其他依赖时由管理员移除，不能重置整份 settings.json。

删除事实不等于彻底遗忘：Raw、job、快照、导出包和已分发副本仍可能留存。目前没有跨所有副本的自动删除/撤回机制。
