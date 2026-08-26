/**
 * v1.0 验收阻断 1 收口：?coding-run-preview 静态预览夹具守护。
 *
 * 预览夹具（dev/codingRunPreview.ts）必须与当前 runProjector/runContracts
 * 保持同步：全部键可构建投影、关键键产出对应事实条目（工具卡/命令卡/
 * 审批/执行输出）。任何投影器契约变更破坏夹具时，本套件先行失败，
 * 避免完整 E2E 才发现夹具漂移。
 */
import { describe, expect, it } from "vitest";

import {
  CODING_RUN_PREVIEW_KEYS,
  createStaticProjection,
} from "./codingRunPreview";

describe("codingRunPreview fixture guard", () => {
  it("全部预览键可构建投影且状态收敛", () => {
    for (const key of CODING_RUN_PREVIEW_KEYS) {
      const result = createStaticProjection(key);
      expect(result.projection, key).toBeTruthy();
      expect(result.projection.runId, key).toBe("run-preview");
      expect(result.projection.entries.length, key).toBeGreaterThan(0);
    }
  });

  it("command-output 夹具产出工具卡与命令执行事实", () => {
    const result = createStaticProjection("command-output");
    const toolEntries = result.projection.entries.filter(
      (entry) => entry.kind === "tool"
    );
    expect(toolEntries.length).toBeGreaterThan(0);
    expect(result.executions?.length ?? 0).toBeGreaterThan(0);
    expect(Object.keys(result.outputPages ?? {})).toContain("exec-cmd-1");
  });

  it("waiting-approval 夹具产出审批条目；patch-preview 携带审批预览", () => {
    const waiting = createStaticProjection("waiting-approval");
    expect(
      waiting.projection.entries.some((entry) => entry.kind === "approval")
    ).toBe(true);
    const patch = createStaticProjection("patch-preview");
    expect(Object.keys(patch.approvalPreviews ?? {}).length).toBeGreaterThan(0);
  });

  it("终态键投影到对应终态", () => {
    expect(createStaticProjection("completed").projection.status).toBe("completed");
    expect(createStaticProjection("failed").projection.status).toBe("failed");
    expect(createStaticProjection("cancelled").projection.status).toBe("cancelled");
  });
});
