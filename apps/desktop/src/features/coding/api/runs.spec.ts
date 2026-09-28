import { beforeEach, describe, expect, it, vi } from "vitest";
import samples from "../../../../../../tests/coding_acceptance/s1-wire-examples.json";
const mocks = vi.hoisted(() => ({ list: vi.fn(), fetch: vi.fn(), local: vi.fn() }));
vi.mock("../../../api/agentRuns", () => ({ listAgentRunExecutions: mocks.list }));
vi.mock("./codingHttp", () => ({ codingFetchJson: mocks.fetch, codingJsonInit: (method: string, body: unknown) => ({ method, body }) }));
vi.mock("../../../services/localExecutor", () => ({ usesLocalExecutor: mocks.local }));
import { createCodingRun, fetchRunExecutions } from "./runs";

describe("S1 API 适配", () => {
  beforeEach(() => vi.clearAllMocks());
  it("执行结果与调用关联经过适配后仍保留", async () => {
    mocks.list.mockResolvedValue(samples.test_failed.executions);
    const records = await fetchRunExecutions(samples.test_failed.snapshot.id);
    expect(records[0].execution_result).toEqual(samples.test_failed.executions[0].execution_result);
    expect(records[0].tool_call_id).toBe(samples.test_failed.executions[0].tool_call_id);
    expect(records[0].operation_id).toBe(samples.test_failed.executions[0].operation_id);
  });
  it("本机创建声明 S1 版本，旧服务端入口不被扩展", async () => {
    const input = { session_id: 1, project_id: 2, workspace_id: 3, message: "创建 hello.py" };
    mocks.local.mockReturnValue(true);
    await createCodingRun(input);
    expect(mocks.fetch).toHaveBeenLastCalledWith("/agent-runs", { method: "POST", body: { ...input, completion_contract_version: "1.0" } });
    mocks.local.mockReturnValue(false);
    await createCodingRun(input);
    expect(mocks.fetch).toHaveBeenLastCalledWith("/agent-runs", { method: "POST", body: input });
  });
});
