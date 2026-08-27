import { Divider, Grid, H1, H2, Stack, Stat, Table, Text } from 'qoder/canvas';

export default function V100CodexToolEngineCompletionReport() {
  return (
    <Stack gap={20}>
      <H1>v1.0.0 Codex 工具体系融合 · 开发完成报告</H1>
      <Text tone="secondary">
        依据：docs/releases/v1.0.0/v1.0.0-codex-tool-engine-integration-plan-20260825.md ·
        目标状态：已完成（全量门禁绿）· 日期：2026-08-26
      </Text>

      <Grid columns={4} gap={16}>
        <Stat value="1283" label="全量 pytest 通过" tone="success" />
        <Stat value="0" label="失败用例" tone="success" />
        <Stat value="13/13" label="§7.7 稳定错误码接线" />
        <Stat value="9/9" label="§20 Feature Flag 注册" />
      </Grid>

      <Divider />

      <H2>成果摘要</H2>
      <Table
        headers={['工作包', '交付', '状态']}
        rows={[
          ['CT-0 治理/ADR', 'codex-adoption-manifest.md + ADR-006/007/008（Exec Host 边界 / 完成证据 / 工具暴露）', '完成'],
          ['CT-1 假成功门禁', 'hello.py 端到端磁盘证据链；ExecutionIntent/CompletionContract/Effect/Evidence 契约；preflight + completion gate', '完成'],
          ['CT-2 ToolSpec v2', 'ToolSpec v2 字段 / Catalog 唯一性与碰撞拒绝 / ToolPlan + ToolSnapshot 诊断视图', '完成'],
          ['CT-4 Router/Lifecycle', '六端口生命周期引擎 + 金标等价套件；策略拒绝统一 tool_hidden_by_policy', '完成'],
          ['CT-5 Patch 统一化', 'PatchOperation 冻结 schema + Windows 危险路径矩阵；Codex parser 评估 Defer 已登记', '完成'],
          ['CT-6 Rust Exec Host', 'argv/stdin(nonce)/output-read/PTY+就绪探针；Job 级联 + Low MIC + AppContainer 失败关闭', '完成'],
          ['CT-7 Search/MCP', '本地 BM25 search_tools + 失效语义；MCP 逐工具审批 / discovery 缓存 / namespace 投影', '完成'],
          ['CT-8 App Server Spike', 'Defer 结论归档（计划允许的三选一结局，触发条件明确）', '完成'],
          ['CT-9 诊断', '工具诊断 API + Vue 面板（11/11）；MCP 策略编辑器 UI 记为前端里程碑延后项', '基本完成'],
        ]}
      />

      <H2>关键步骤（本轮）</H2>
      <Table
        headers={['步骤', '内容']}
        rows={[
          ['基线修复', 'ExecHostClient 透传 host 稳定错误码（§7.7 信封），修复 AC 失败关闭断言'],
          ['CT-6 补齐', 'execution/stdin/write（四路径 + nonce 绑定）、execution/output/read（1 MiB 窗口续读）、ConPTY 受控 PTY + 环境就绪探针（不交付伪会话）'],
          ['CT-7 补齐', 'MCP 审批策略迁移 0034、连接身份哈希 + TTL 新鲜度门禁、mcp.<server> 投影接入诊断'],
          ['§7.7 收口', 'error_codes.py 冻结注册表；tool_hidden_by_policy / tool_health_failed / tool_plan_invalidated 接线'],
          ['§20 收口', '9 个 flag 注册（enforce 阶段接线回落非 fail-open）+ .env.example'],
          ['终态回归', '全量 1283 过 / 6 跳过 / 0 红；ruff、依赖方向、cargo 无警告'],
        ]}
      />

      <H2>主要变更文件</H2>
      <Table
        headers={['区域', '文件']}
        rows={[
          ['Rust Exec Host', 'apps/exec-host/src/{main.rs, sandbox.rs}'],
          ['执行协议', 'agent_v2/execution/{contracts.py, exec_host_client.py}'],
          ['领域契约', 'agent_v2/domain/{error_codes.py, tool_search.py, completion.py, effects.py, intents.py}'],
          ['应用层', 'agent_v2/application/{mcp_catalog.py, deferred_search.py, tool_engine.py, preflight.py, planner.py}'],
          ['MCP', 'mcp/{contracts.py, repository.py, manager.py} · api/routes_mcp.py'],
          ['API/配置', 'api/routes_agent_runs.py · config.py · .env.example · alembic/versions/0034_*'],
          ['测试', 'tests/test_v100_ct6_stdin_pty.py · test_v100_ct7_mcp_policy.py · test_v100_s20_flags_error_codes.py 等'],
          ['文档/证据', 'adr/evidence/s4-network-enforcement-plan.md §3.9 · v1.0.0-ct0-ct2-iteration-report §7-§8'],
        ]}
      />

      <H2>验证证据（终态门禁）</H2>
      <Table
        headers={['门禁', '结果']}
        rows={[
          ['全量 pytest', '1283 passed + 6 skipped（0 failed），6 个跳过均为环境守护（PTY/AC 附着需健康会话）'],
          ['CT-6 五套件', '21 过 4 环境守护跳过（含 stdin/PTY 新用例）'],
          ['§7.7/§20 合规套件', '9 用例全绿（注册表完整性 / flag 默认值 / 失效语义 / 健康失败码）'],
          ['ruff src tests scripts', 'All checks passed'],
          ['agent_v2 依赖方向', 'OK（domain 不依赖实现层/传输/Provider SDK）'],
          ['cargo 构建', '无警告；迁移 0034 幂等应用至专用测试库'],
          ['桌面目标 vitest', 'McpServersPanel + ToolDiagnosticsPanel 11/11'],
        ]}
      />

      <H2>终态结论</H2>
      <Text>
        计划所列工作包（第一迭代 → Router/Lifecycle → Patch 统一化 → Rust Exec Host →
        Deferred Tool Search/MCP → 隔离 Spike）全部交付并有测试锚定。架构红线保持：
        Python Agent Core 唯一控制面；Codex App Server 未接入主链；Rust 仅受控执行
        （不发现工具、不调模型、不写库）；模型工具协议以探测为准；副作用完成只认
        Effect/Evidence——缺失工具、模型不支持、策略拒绝、健康失败、执行未知或证据
        不足一律返回稳定错误码，模型文字声明无法伪装为已完成。
      </Text>
      <Text tone="secondary" size="small">
        遗留（环境依赖，断言已固化、解除即自动验证）：AC kernel_deny 强形态与 PTY 回显
        实证需健康会话/参考机；MCP 策略编辑器 UI 属 CT-9 前端里程碑；soak/RC 观察属
        上位计划发布流程（S8/S9）。
      </Text>
    </Stack>
  );
}
