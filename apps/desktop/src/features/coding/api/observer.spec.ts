import { beforeEach, describe, expect, it, vi } from "vitest";
import { fetchProjectObserverConfig, fetchRunObserver, observerReportJson, parseObserverConfig, parseObserverReport, saveProjectObserverConfig } from "./observer";
import { codingFetchJson } from "./codingHttp";

vi.mock("./codingHttp", () => ({ codingFetchJson: vi.fn(), codingJsonInit: (method: string, body: unknown) => ({ method, body: JSON.stringify(body) }) }));

function report() {
  return {
    schema_version: "1.0", run_id: "run/1", status: "completed", goal_outcome: "verified", last_event_sequence: 4,
    config_version: 2, counts: { events: 4, steps: 1, executions: 1 }, truncated: false,
    progress: { repeated_observations: 0, failure_repeats: 0, verification_retries: 1 }, error: null,
    steps: [{ id: "step-1", ordinal: 1, kind: "tool", status: "completed", name: "read_project_file", plan_item_key: null }],
    checks: [{ id: "artifact-check", kind: "artifact", status: "passed", reason_code: "artifact_exists", evidence_ids: ["evidence-1"] }],
    events: [{ sequence: 4, type: "tool.completed", step_id: "step-1", execution_id: "execution-1", category: "tool" }],
  };
}

beforeEach(() => vi.clearAllMocks());

describe("观察器 API", () => {
  it("运行标识编码并传递取消信号，错误归属的报告被拒绝", async () => {
    const signal = new AbortController().signal;
    vi.mocked(codingFetchJson).mockResolvedValue(report());
    expect((await fetchRunObserver("run/1", signal)).run_id).toBe("run/1");
    expect(codingFetchJson).toHaveBeenCalledWith("/agent-runs/run%2F1/observer", { signal });
    await expect(fetchRunObserver("other")).rejects.toThrow("当前任务不一致");
  });

  it("诊断读取和导出只保留白名单，不复制正文或嵌套内部数据", () => {
    const raw = { ...report(), output: "private text", arguments: { secret: "private args" } };
    Object.assign(raw.steps[0], { prompt: "private prompt" });
    Object.assign(raw.events[0], { payload: { stdout: "private log" } });
    Object.assign(raw.checks[0], { scope: "C:\\private\\file" });
    const clean = parseObserverReport(raw);
    const copied = observerReportJson(clean);
    expect(copied).not.toContain("private");
    expect(copied).not.toContain("payload");
    expect(clean.events[0]).toEqual({ sequence: 4, type: "tool.completed", step_id: "step-1", execution_id: "execution-1", category: "tool" });
    expect(observerReportJson({ ...clean, output: "private text" } as typeof clean)).not.toContain("private");
  });

  it("无效报告与超限事件不能被当成可用诊断", () => {
    expect(() => parseObserverReport({ ...report(), counts: { events: -1, steps: 1, executions: 1 } })).toThrow();
    expect(() => parseObserverReport({ ...report(), events: Array(101).fill(report().events[0]) })).toThrow();
    expect(() => parseObserverReport({ ...report(), checks: [{ ...report().checks[0], status: "success" }] })).toThrow();
    expect(() => parseObserverReport({ ...report(), schema_version: "2.0" })).toThrow();
  });

  it("历史步骤未保留安全标识时按未关联记录，不丢弃整份报告", () => {
    const value = { ...report(), steps: [{ ...report().steps[0], id: null }] };
    expect(parseObserverReport(value).steps[0].id).toBeNull();
  });

  it("检查配置读写保留版本并通过独立接口保存", async () => {
    const signal = new AbortController().signal;
    const initial = { version: 0, enabled: false, checks: [] };
    vi.mocked(codingFetchJson).mockResolvedValue(initial);
    expect(await fetchProjectObserverConfig(7, signal)).toEqual(initial);
    expect(codingFetchJson).toHaveBeenLastCalledWith("/projects/7/observer-config", { signal });
    const input = { expected_version: 0, enabled: true, checks: [{ id: "tests", kind: "test" as const, scope: "npm test" }] };
    const updated = { version: 1, enabled: true, checks: input.checks };
    vi.mocked(codingFetchJson).mockResolvedValue(updated);
    expect(await saveProjectObserverConfig(7, input, signal)).toEqual(updated);
    expect(codingFetchJson).toHaveBeenLastCalledWith("/projects/7/observer-config", { method: "PUT", body: JSON.stringify(input), signal });
    expect(() => parseObserverConfig({ ...initial, checks: Array(9).fill(input.checks[0]) })).toThrow();
  });
});
