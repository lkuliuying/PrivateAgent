import { flushPromises, mount } from "@vue/test-utils";
import { ref, shallowRef } from "vue";
import { beforeEach, describe, expect, it, vi } from "vitest";
import samples from "../../../../../../tests/coding_acceptance/s1-wire-examples.json";
import type { RunStreamController } from "../composables/useRunStream";
import { createCodingWorkspacePreviewStore } from "../dev/codingHomePreview";
import { applyRunFrame, createRunProjection } from "../model/runProjector";
import type { RunExecutionRecord } from "../model/runContracts";
import CodingThreadWorkspace from "./CodingThreadWorkspace.vue";
import RunTranscript from "./RunTranscript.vue";

const state = vi.hoisted(() => ({ stream: null as unknown as RunStreamController, fetch: vi.fn() }));
vi.mock("../composables/useRunStream", () => ({ useRunStream: () => state.stream }));
vi.mock("../api/runs", async (original) => ({ ...await original<object>(), fetchRunExecutions: state.fetch }));
vi.mock("../api/threads", async (original) => ({ ...await original<object>(),
  fetchCodingThreadMessages: vi.fn(async () => []), fetchLatestCodingThreadRunId: vi.fn(async () => null) }));

function projected(runId = samples.test_failed.snapshot.id) {
  const projection = createRunProjection(runId);
  for (const event of samples.test_failed.events) applyRunFrame(projection, event);
  return projection;
}

async function mounted() {
  const store = createCodingWorkspacePreviewStore("ready");
  await flushPromises();
  store.selectThread(11);
  const wrapper = mount(CodingThreadWorkspace, { props: { store } });
  await flushPromises();
  return wrapper;
}

beforeEach(() => {
  state.fetch.mockReset();
  state.stream = { projection: shallowRef(projected()), phase: ref("idle"), connectionError: ref(null), createErrorCode: ref(null),
    startRun: vi.fn(), attachRun: vi.fn(), cancelActive: vi.fn(), retryConnection: vi.fn(), detach: vi.fn() };
});

describe("S1 执行事实刷新与运行隔离", () => {
  it("纠偏后重新加载同一运行的命令事实", async () => {
    state.fetch.mockResolvedValueOnce(samples.test_failed.executions).mockResolvedValueOnce([]);
    const wrapper = await mounted();
    try {
      expect(Object.keys(wrapper.findComponent(RunTranscript).props("executionByTool") ?? {})).toHaveLength(1);
      const next = projected();
      next.status = "running";
      state.stream.projection.value = next;
      await flushPromises();
      expect(state.fetch).toHaveBeenCalledTimes(2);
      expect(wrapper.findComponent(RunTranscript).props("executionByTool")).toEqual({});
    } finally { wrapper.unmount(); }
  });

  it("切换运行后，即使调用 ID 重用或旧请求迟到，也不显示上轮执行结果", async () => {
    let resolveOld!: (records: RunExecutionRecord[]) => void;
    state.fetch.mockResolvedValueOnce(samples.test_failed.executions)
      .mockImplementationOnce(() => new Promise<RunExecutionRecord[]>(resolve => { resolveOld = resolve; }))
      .mockRejectedValueOnce(new Error("新运行的执行记录暂不可用"));
    const wrapper = await mounted();
    try {
      expect(Object.keys(wrapper.findComponent(RunTranscript).props("executionByTool") ?? {})).toHaveLength(1);
      const refreshing = projected();
      refreshing.status = "running";
      state.stream.projection.value = refreshing;
      await flushPromises();
      state.stream.projection.value = projected("new-run");
      await flushPromises();
      resolveOld(samples.test_failed.executions as unknown as RunExecutionRecord[]);
      await flushPromises();
      expect(wrapper.findComponent(RunTranscript).props("executionByTool")).toEqual({});
    } finally { wrapper.unmount(); }
  });
});
