/**
 * v0.9.0 H1-B（计划 §5.6）· useRunStream 创建失败关闭测试
 *
 * 创建失败 = 失败关闭状态：结构化 error_code 暴露给阻塞项诊断，
 * 消息取后端 detail（不出现 [object Object]），无 run 投影（不产生
 * 假完成记录）。
 */
import { describe, expect, it, vi } from "vitest";
import { effectScope } from "vue";
import { useRunStream, type RunStreamDeps } from "./useRunStream";
import type { RunSnapshot, RunStreamFrame } from "../model/runContracts";

function makeDeps(createRun: RunStreamDeps["createRun"]) {
  const deps: RunStreamDeps = {
    createRun,
    fetchSnapshot: vi.fn(async () => ({} as RunSnapshot)),
    fetchEvents: vi.fn(async () => ({ items: [] as RunStreamFrame[] })),
    openStream: vi.fn(() => new AbortController()),
    cancelRun: vi.fn(async () => undefined),
    schedule: vi.fn(() => 1),
    cancelSchedule: vi.fn(),
  };
  return deps;
}

const INPUT = {
  session_id: 1,
  message: "看一下本机是否装了 MySQL",
  project_id: 1,
  workspace_id: 101,
};

describe("useRunStream · 创建失败关闭（H1-B §5.6）", () => {
  it("CodingApiError → phase=error + 结构化错误码 + detail 消息", async () => {
    const deps = makeDeps(
      vi.fn(async () => {
        throw { status: 409, code: "full_access_revoked", message: "授予已撤销" };
      })
    );
    const scope = effectScope();
    const controller = scope.run(() => useRunStream(deps))!;
    await controller.startRun(INPUT);
    expect(controller.phase.value).toBe("error");
    expect(controller.createErrorCode.value).toBe("full_access_revoked");
    expect(controller.connectionError.value).toBe("授予已撤销");
    // 失败关闭：无 run 投影、不打开事件流（不产生假完成记录）
    expect(controller.projection.value).toBeNull();
    expect(deps.openStream).not.toHaveBeenCalled();
    scope.stop();
  });

  it("普通 Error → 保留消息，错误码为 null（阻塞诊断收敛为通用项）", async () => {
    const deps = makeDeps(
      vi.fn(async () => {
        throw new Error("network down");
      })
    );
    const scope = effectScope();
    const controller = scope.run(() => useRunStream(deps))!;
    await controller.startRun(INPUT);
    expect(controller.phase.value).toBe("error");
    expect(controller.createErrorCode.value).toBeNull();
    expect(controller.connectionError.value).toBe("network down");
    scope.stop();
  });

  it("detach 清空阻塞状态（切换对话不串线）", async () => {
    const deps = makeDeps(
      vi.fn(async () => {
        throw { status: 409, code: "workspace_unavailable", message: "x" };
      })
    );
    const scope = effectScope();
    const controller = scope.run(() => useRunStream(deps))!;
    await controller.startRun(INPUT);
    expect(controller.createErrorCode.value).toBe("workspace_unavailable");
    controller.detach();
    expect(controller.createErrorCode.value).toBeNull();
    expect(controller.phase.value).toBe("idle");
    scope.stop();
  });
});
