# 私人助手 Agent · 第二阶段开发计划书

> 版本：v0.1 · 日期：2026-07-04
> 对应需求：`docs/archive/phases/phase2-requirements.md`
> 阶段主题：受控工具调用 + 知识库增强 + 活动流 + UI 大改造。
> 阶段原则：先建立安全边界和 UI 工作台骨架，再逐步开放工具能力。第二阶段不做完全自主 Agent。

---

## 1. 阶段目标

第一阶段已经完成“能聊天、能 RAG、能运行”的基础闭环。第二阶段要把产品从“问答应用”升级为“桌面工作台助手”：

1. 助手能使用受控工具，但风险操作必须审批。
2. 助手能读取用户授权的本地文件和目录。
3. 知识库从单文档管理升级为批量、筛选、重建、启用/禁用。
4. 用户能看到助手执行任务的过程、证据和结果。
5. UI 进行一次大改造，形成成熟桌面应用的视觉系统。

---

## 2. 总体架构变化

第二阶段继续沿用第一阶段架构：

```text
Tauri 桌面壳
  -> Vue 3 工作台 UI
    -> FastAPI 本地 API
      -> core: chat / rag / tools / files / activities
        -> Ollama + MySQL + ChromaDB
```

新增核心模块：

```text
src/personal_assistant/
├── core/
│   ├── tools.py          # ToolDefinition / ToolRegistry / ToolExecutor
│   ├── approvals.py      # 审批状态与权限判断
│   ├── files.py          # 授权路径、文件读取、目录扫描
│   ├── activities.py     # 活动流聚合
│   └── permissions.py    # 风险等级与路径校验
├── api/
│   ├── routes_tools.py
│   ├── routes_files.py
│   └── routes_activities.py
└── workers/
    ├── tool_runner.py
    └── batch_importer.py
```

前端新增/重构：

```text
apps/desktop/src/
├── design/
│   ├── tokens.css        # 颜色、间距、字体、动效变量
│   └── components.css    # 通用控件基础样式
├── components/
│   ├── WorkspaceShell.vue
│   ├── InspectorPanel.vue
│   ├── ActivityTimeline.vue
│   ├── ToolApprovalCard.vue
│   ├── SourceInspector.vue
│   └── FilePickerPanel.vue
└── views/
    ├── ChatWorkspace.vue
    ├── KnowledgeWorkspace.vue
    ├── ActivityWorkspace.vue
    └── SettingsWorkspace.vue
```

---

## 3. UI 大改造方案

### 3.1 信息架构

第二阶段主界面采用“四区工作台”：

1. **左侧主导航 rail**
   - 聊天
   - 知识库
   - 任务/活动
   - 设置

2. **列表区**
   - 聊天页显示会话列表。
   - 知识库页显示文档列表。
   - 活动页显示任务/工具调用列表。

3. **主工作区**
   - 聊天消息、知识库管理、任务详情或设置内容。

4. **右侧检查器**
   - 引用片段详情。
   - 工具执行步骤。
   - 当前上下文、状态、错误详情。

底部增加轻量状态栏：
- API 状态。
- Ollama 状态。
- MySQL 状态。
- ChromaDB 状态。
- 当前模型。
- 当前任务状态。

### 3.2 视觉风格

方向：**冷静、专业、桌面工作台、长期使用不疲劳**。

设计规则：
- 默认浅色主题，预留深色主题变量。
- 主色使用青蓝，但只作为强调色，不铺满整个页面。
- 背景使用雾白、石墨、银灰，配合少量琥珀警告和红色危险状态。
- 页面区域不做多层卡片嵌套。
- 卡片只用于消息、文档、活动、审批等独立对象。
- 圆角统一 6-8px。
- 字号和间距偏紧凑，适合桌面高信息密度。
- 图标优先使用统一图标库，不手写零散 SVG。

### 3.3 交互效果

必须实现：
- 流式回答的轻量打字状态。
- 工具调用步骤的展开/收起。
- 引用片段点击后右侧检查器滑入或定位。
- 批量导入队列进度。
- 工具审批卡片的状态变化：等待、批准、拒绝、执行中、完成、失败。
- 页面切换短过渡，控制在 120-180ms。

不做：
- 大面积渐变背景。
- 营销式 hero。
- 复杂装饰动效。
- 影响阅读的强动画。

---

## 4. 数据库变更计划

### 4.1 新增表

`tool_calls`：
- 记录工具调用、审批、执行结果。

`trusted_paths`：
- 记录用户授权过的文件/目录路径。

`activities`：
- 聚合工具调用、导入任务、索引任务，供活动流展示。

建议表结构：

```sql
CREATE TABLE activities (
  id            BIGINT AUTO_INCREMENT PRIMARY KEY,
  session_id    BIGINT NULL,
  kind          ENUM('tool','document_import','reindex','system') NOT NULL,
  title         VARCHAR(255) NOT NULL,
  status        ENUM('pending','waiting_approval','running','succeeded','failed','cancelled') NOT NULL,
  ref_type      VARCHAR(64),
  ref_id        BIGINT,
  detail_json   JSON,
  error_message TEXT,
  started_at    DATETIME(3),
  finished_at   DATETIME(3),
  created_at    DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at    DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  INDEX idx_activity_session (session_id, created_at),
  INDEX idx_activity_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

### 4.2 现有表增强

`documents`：
- 增加 `enabled BOOLEAN NOT NULL DEFAULT TRUE`。
- 增加 `last_error_at DATETIME(3)` 可选。

`messages`：
- 可选增加 `metadata_json JSON`，用于保存引用、工具结果摘要。

---

## 5. API 设计

### 5.1 工具 API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/tools` | 获取可用工具列表 |
| POST | `/tools/plan` | 根据用户意图生成工具计划 |
| POST | `/tool-calls/{id}/approve` | 批准执行 |
| POST | `/tool-calls/{id}/reject` | 拒绝执行 |
| GET | `/tool-calls` | 查询调用记录 |

### 5.2 文件 API

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/files/authorize` | 保存 Tauri 文件选择器授权路径 |
| GET | `/files/scan` | 扫描授权目录下可处理文件 |
| POST | `/files/summarize` | 总结授权文件 |

### 5.3 知识库增强 API

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/documents/batch-import` | 批量导入 |
| POST | `/documents/{id}/reindex` | 重建单个文档索引 |
| POST | `/documents/reindex-all` | 重建全部索引 |
| PATCH | `/documents/{id}` | 更新启用状态 |
| GET | `/chunks/{id}` | 查看片段详情 |

### 5.4 活动流 API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/activities` | 查询活动列表 |
| GET | `/activities/{id}` | 活动详情 |
| POST | `/activities/{id}/retry` | 重试失败活动 |

---

## 6. 开发里程碑

### M0 · 设计系统与 UI 骨架

目标：先把新的工作台框架搭出来。

- [x] 建 `design/tokens.css`：颜色、字号、间距、阴影、动效变量。
- [x] 建 `WorkspaceShell.vue`：四区布局，支持响应式宽度。
- [x] 重构主导航 rail。
- [x] 增加右侧 `InspectorPanel.vue`。
- [x] 增加底部状态栏。
- [x] 保留第一阶段聊天/知识库/设置能力，不破坏现有 API。
- [x] 用截图检查 900px / 1200px / 1600px 三种宽度。

验收：
- 新工作台 UI 可打开。
- 四个主入口存在：聊天、知识库、任务、设置。
- 旧功能仍可使用。

### M1 · 工具调用底座

目标：建立工具注册、调用、审批、记录机制。

- [x] 新增 ORM：`ToolCall`、`TrustedPath`、`Activity`。
- [x] 新增 Alembic 迁移。
- [x] 实现 `ToolDefinition`、`ToolRegistry`、`ToolExecutor`。
- [x] 实现风险等级：safe / confirm / restricted。
- [x] 实现审批状态机。
- [x] 实现 API：`GET /tools`、`POST /tools/plan`、approve/reject。
- [x] 前端实现 `ToolApprovalCard.vue`。

验收：
- 一个 confirm 工具在执行前必须展示审批卡片。
- 拒绝后不执行。
- 批准后执行并记录结果。实现上 approve 接口会原子占用 `pending_approval` 并直接进入 `running` 执行，避免并发重复执行。

### M2 · 文件工具与授权路径

目标：让助手可以读取用户明确授权的本地文件。

- [x] Tauri 前端接入文件/目录选择器。
- [x] 后端保存授权路径到 `trusted_paths`。
- [x] 实现路径校验：只读授权路径。
- [x] 实现 `read_file` 工具。
- [x] 实现 `summarize_file` 工具。
- [x] 实现文件大小和类型限制。
- [x] 前端新增文件摘要交互。

验收：
- 选择文件后可总结。
- 未授权路径读取失败。
- 文件读取工具有审批记录。

### M3 · 知识库增强

目标：让知识库适合日常管理。

- [x] 文档列表增加搜索、筛选、启用/禁用。
- [x] `documents.enabled` 入库并参与 RAG 检索过滤。
- [x] 实现批量导入 API。
- [x] 实现重建索引 API。
- [x] 实现引用片段详情 API。
- [x] 前端新增引用详情检查器。
- [x] 批量导入显示队列进度。

验收：
- 批量导入可运行。
- 禁用文档后不参与检索。
- 点击引用能看到原文片段。

### M4 · 活动流与执行可视化

目标：用户能看到助手在做什么。

- [x] 实现 `ActivityService`。
- [x] 工具调用、文档导入、重建索引写入 activities。
- [x] 新增活动页。
- [x] 聊天页右侧检查器显示当前会话活动。
- [x] 活动支持展开输入/输出摘要。
- [x] 失败活动支持重试。

验收：
- 工具调用和导入任务都出现在活动流。
- 活动状态实时更新或可刷新。
- 失败活动有错误原因和重试入口。

### M5 · 测试、视觉 QA 与收尾

目标：把第二阶段收束到可交付。

- [x] 单元测试：工具注册、审批状态、路径校验。
- [x] API 测试：工具审批、文件摘要、批量导入、启用/禁用、引用详情。
- [x] E2E 测试：从聊天触发工具、审批、执行、结果回到对话。
- [x] 前端构建：`npm run build`。
- [x] 后端测试：`pytest`。
- [x] Tauri 校验：`cargo check`。
- [x] 截图 QA：900px / 1200px / 1600px。
- [x] 更新 README 和 usage-guide。

验收：
- 所有测试通过。
- 主要页面截图无重叠、无溢出、风格统一。
- 第二阶段需求文档中的验收清单全部通过。

---

## 7. 推荐开发顺序

1. 先做 M0 UI 骨架，不改业务。
2. 再做 M1 工具调用底座。
3. 然后 M2 文件工具。
4. 接着 M3 知识库增强。
5. 最后 M4 活动流，把工具和导入过程统一展示。
6. M5 专门做测试、视觉 QA 和文档收尾。

这样做的原因：UI 大改造会影响所有页面，如果放到最后，会导致功能做完后再返工页面结构。先把工作台骨架定下来，后面所有新功能都能自然长进去。

---

## 8. 关键风险与对策

| 风险 | 对策 |
|---|---|
| 工具调用越界访问本地文件 | 只允许访问 Tauri 文件选择器授权路径；后端做路径校验 |
| 用户不清楚助手做了什么 | 工具调用和导入任务全部写入活动流 |
| UI 大改造破坏现有功能 | M0 只重构外壳，保留旧 API，逐页迁移 |
| 批量导入阻塞界面 | 后台任务 + 活动流进度 |
| LangGraph 引入过重 | 第二阶段只在工具计划/审批链路需要时局部引入，不强行重写聊天主链路 |
| 页面信息过密 | 四区布局 + 检查器承载详情，主工作区保持聚焦 |

---

## 9. 第二阶段最终验收

第二阶段完成时必须满足：
1. 新 UI 工作台可用，页面风格明显升级。
2. 聊天、知识库、任务、设置四个主入口稳定。
3. 工具调用底座可用，有审批、有记录、有结果。
4. 文件读取只允许访问授权路径。
5. 知识库支持批量导入、重建索引、启用/禁用、引用详情。
6. 活动流能展示工具调用和导入任务。
7. 后端测试、前端构建、Tauri 校验通过。
8. 视觉 QA 截图通过，不出现布局重叠或文字溢出。

---

## 10. 不变的边界

第二阶段仍然坚持：
- 默认本地优先。
- 默认不上传用户资料。
- 不做完全自主 Agent。
- 有风险操作必须审批。
- 工具调用必须可审计。
- UI 改造服务于工作效率，不做花哨演示页。
