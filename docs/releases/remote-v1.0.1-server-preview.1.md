# PrivateAgent 1.0.1 账号登录修复预览版

发行标签：`remote-v1.0.1-server-preview.1`。这是 Windows x64 未签名手动安装预览包，不替换稳定版或任何既有自动更新通道。

[GitHub Release](https://github.com/lkuliuying/PrivateAgent/releases/tag/remote-v1.0.1-server-preview.1) · [下载安装包](https://github.com/lkuliuying/PrivateAgent/releases/download/remote-v1.0.1-server-preview.1/PrivateAgent_1.0.1_x64-setup.exe)

## 修复范围

初版统一包默认生成本机账号，退出后又将用户名密码登录发往本机不存在的接口，导致 Not Found。本版只保留服务器账号，账号入口由 Tauri 后端固定为用户确认的 `https://www.liuyingapi.top`，不提供地址设置，也不回退本机账号或完整业务后端。

本机 Ollama 和 OpenAI 兼容模型设置保留，与账号身份分离。项目、任务、SQLite、审批、文件 SHA-256 及命令执行仍在本机。切换模型不另建账号记录库；旧连接配置迁移时保留有效模型参数，清除旧账号模式、地址覆盖和会话，不删除数据库。

## 安装与更新

1. 正常退出旧客户端，包括托盘中的后台实例。
2. 备份当前用户的 `%LOCALAPPDATA%\com.personal-assistant.desktop\local-projects` 整个目录；不要只复制可能仍有 WAL 的 SQLite 主文件。
3. 安装 `PrivateAgent_1.0.1_x64-setup.exe`，进入后使用服务器用户名和密码登录。
4. 如需本机模型，在设置中的“模型执行设置”选择本机模型，并核对协议、回环地址、模型名和上下文容量。

不需要用户填写账号服务器地址或修改 hosts 文件。不要删除 AppData / SQLite 来清除旧本机账号。旧 `local://device` 记录保留，但不会自动归入服务器账号；旧 PrivateAgentRemote 的独立应用目录也不会自动合并。具体历史迁移规则见[统一运行时说明](../unified-desktop-runtime.md)。

**服务器 git pull 不能更新已安装的桌面客户端。** 本次修改不新增业务表迁移，不替用户操作或重启服务器；若服务器模型、管理或历史接口仍不可用，按实际服务器回执另行核对。不能把本次客户端发行当作服务器部署验收。

## 安装包与构建依据

- 本机产物：`.run/unified-client-6IIl0v/PrivateAgent_1.0.1_x64-setup.exe`
- 大小：30048579 字节
- SHA-256：`236bb5b7cc97a39788a9d237cbce56989e23a3e68c4874e31e3df067d795db2c`
- 发布附件：安装包、原始 `build-info.json`、只包含这两个附件的 `SHA256SUMS.txt`。
- 原始构建记录：基线提交 `71057fe43a83f3c764751b7d7ad846ca9f38576c` 加本次修复，`dirty=true`。确认服务器入口没有改变已验证的程序，因此保留原安装包和原始构建记录，没有把记录改写成干净构建。发行标签关联本次分批提交后的源码。
- 应用标识仍为 `com.personal-assistant.desktop`；预览包关闭自动更新入口，不生成 latest.json。没有读取、替换签名密钥或关闭 updater 验签。

## 已验证与限制

完整前端回归 82 文件、482 项通过；Python 相关回归 134 项通过；构建选项 9 项通过。Vue 类型检查、Ruff、Vite、Rust 原生编译、NSIS 打包和产物 SHA-256 清单通过。

使用最终包中的冻结执行器，分别通过服务器模型、本机 Ollama、本机 OpenAI 兼容接口的隔离回环验证：服务器登录与退出、取消本机账号入口、文件写入、人工命令审批、完全访问脚本、上下文 usage、历史导出、撤权，以及篡改宿主摘要后拒绝执行。没有向本机模型发送账号令牌。

这些是模拟账号和模型服务的本地验证，不代表真实账号、真实供应商或原生安装升级已经验收。安装包没有 Authenticode 签名；项目脚本仍以当前系统用户权限执行，工具审批和校验不构成操作系统沙箱。

具体测试命令、失败与修正记录、完整变更文件清单见[修复说明](../solutions/2026-08-31-server-account-login.md)。已读取 AGENTS.md 和 docs/project-state.md；后者按仓库约定保留历史快照，当前实现和发行边界以本说明与源码为准。README.md 原有用户改动未纳入本次提交。
