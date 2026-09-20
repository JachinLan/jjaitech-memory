# Windows / MacBook 安装与升级

适用插件1.4.1-rc.1。安装包只有代码，不包含员工Wiki或账号。

## 安装前仅需做什么

1. 从WorkBuddy官网下载与电脑匹配的客户端，安装后用自己的账号登录，等待运行环境准备完成。
2. 完成当前任务，退出WorkBuddy（Windows也退出托盘）和独立CodeBuddy会话。
3. 使用发布页对应系统的命令，阅读本地写入/当前云端模型处理范围，输入YES。
4. 成功后重开WorkBuddy，用虚构客户做一次普通聊天，再新建聊天询问，核对Raw和保存回执。

支持基线：Windows10/11 x64，macOS12+（Apple Silicon/Intel分开验收）。Windows ARM64、企业特殊策略和员工真实桌面账号需要另外验证，不能由CI替代。

## 安装器现在会做什么

- 优先查找WorkBuddy已下载的Python/Node，并真实执行版本与SQLite FTS5探测；不能只凭文件存在就判定可用。
- Windows跳过Microsoft Store的Python占位入口；依赖确实缺失时通过WinGet提示安装，保留原厂许可/管理员确认，不自动接受协议。
- Mac优先使用WorkBuddy运行环境，支持已有官方Python/Homebrew Python；不自动安装Homebrew、开发者工具或Rosetta。缺失时明确停止并指向官方Python安装。
- Windows持久保存实际Git Bash路径到settings.env，以便从桌面重启仍可用；只改这一项环境键，失败恢复原值。
- Hook和本地MCP共用本地运行环境选择器。原Python路径不存在时尝试其他本地运行环境，不联网偷偷下载、不修改用户PATH。
- 防止两个安装器同时改配置；保留原配置、数据库及原插件运行缓存。同版本重装失败也恢复实际缓存，避免只恢复注册信息。
- 安装后核对启用/注册版本，再在临时隔离Wiki真实运行本地MCP与Raw归档/去重；失败按事务回滚。
- 下载ZIP后检查固定SHA256，网络暂时失败可有限重试。不会取消沙箱或改PowerShell执行策略。

## 下载不通：代码离线包

GitHub访问受网络影响，不能保证所有国内电脑都能直接下载。管理员可下载发布页同一份ZIP与SHA256SUMS，核验后通过公司批准的渠道传递代码包。不要把自己的AI-Wiki或.workbuddy打包给同事。

Windows：完整解压后，运行jjaitech-memory/deployment/install-windows.cmd。该入口使用同一依赖检查、权限说明、回滚和校验流程。企业显式Restricted/AllSigned策略仍会停止，需IT批准/签名部署；不要用Bypass或永久放宽策略。

Mac：终端运行`bash /解压目录/jjaitech-memory/distribution/bootstrap-macos.sh /解压目录`；可追加`--check`仅检查。路径有空格时用引号。在线安装器也可追加--check做只读预检。

离线包不包含Python/Node/Git。真正断网的电脑需要IT先准备运行环境；已有WorkBuddy运行环境一般可以复用。当前没有额外镜像站、签名pkg/msi/exe或静默全自动部署。

## 安装成功的三层含义

1. **注册成功**：插件版本、缓存路径、启用状态正确。
2. **本地启动通过**：运行环境、stdio MCP、Raw保存和去重实测通过。安装器现在自动做这一步，不消费模型额度。
3. **员工使用通过**：重开WorkBuddy后，用本人的账号和模型完成自动沉淀及跨会话召回。这一步不能由无账号CI冒充。

## 常见失败

- 未登录/未准备环境：先打开WorkBuddy完成登录和环境初始化。
- WorkBuddy仍运行：保存当前任务并退出托盘；安装器不会强行结束你的任务。
- GitHub下载失败：确认网络或使用经校验的代码离线包；不会因下载失败删除Wiki。
- Python/Node损坏：重新运行安装命令，或由IT修复运行环境；不要删Wiki。
- 企业阻止安装：保留错误和安装收据交IT处理，不能直接关闭Defender/Gatekeeper或放开全盘权限。
- 安装后仍不保存：先重开新会话，检查AI-Wiki/.state/MEMORY_STATUS.md与doctor，再检查宿主/模型版本。

日常开关、备份迁移和手工分享见OPERATIONS.md。运行环境选择器能处理路径变化，但不代替宿主大版本兼容测试或完整异机备份。
