# PrivateAgent 桌面端

Tauri 2、Vue 3、TypeScript 和 Vite 提供本机 Coding 工作区。客户端通过私有 IPC 连接 Python 本机执行器，使用用户配置的 API Key；当前架构与开发前提见[项目 README](../../README.md)。

## 目录

| 位置 | 职责 |
| --- | --- |
| `src/features/coding/` | Coding 页面、领域状态、API、运行流和组件测试 |
| `src/components/`、`src/services/`、`src/api/` | 共享设置、桌面生命周期、本机传输和请求接口 |
| `src/design/`、`src/animations/`、`src/assets/` | 设计系统、动画与应用素材 |
| `src-tauri/` | Rust 壳、凭据、执行器生命周期、更新及安装模板 |
| `e2e/` | 浏览器流程、合成夹具和正式视觉基线 |
| `scripts/` | 分包预算和界面基线辅助 |

## 开发与验证

在仓库根目录执行：

```powershell
npm run dev --prefix apps/desktop
npm test --prefix apps/desktop
npm run e2e --prefix apps/desktop -- --list
npm run build --prefix apps/desktop
```

Vite 提供浏览器界面开发服务；本机命令和凭据能力需要 Tauri 与执行器。E2E 使用接口或 IPC 替身，测试收集不等于断言通过。Rust 开发需要可用的 MSVC 环境，详见[测试指南](../../docs/testing-guide.md)。

## 构建产物

安装器与便携目录使用仓库的 `scripts\build-client.cmd` 生成，前端构建不等于完整桌面打包。当前保留候选包为 `dist/PrivateAgentCandidate-1.0.20/`，未签名且未配置更新端点。

`node_modules/` 是保留的开发依赖；`dist/`、`test-results/`、`playwright-report/` 和 Rust 编译缓存可重建。正式 E2E 截图位于 `e2e/visual-regression.spec.ts-snapshots/`，不能当作缓存删除或为消除失败直接重录。目录清理及历史证据入口见[目录说明](../../docs/repository-layout.md)。
