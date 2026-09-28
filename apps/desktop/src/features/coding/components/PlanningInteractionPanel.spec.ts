import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import PlanningInteractionPanel from "./PlanningInteractionPanel.vue";
import { createRunProjection } from "../model/runProjector";
import { answerPlanQuestion, implementRunPlan } from "../api/planning";
import { fetchRunSnapshot } from "../api/runs";
import type { RunSnapshot } from "../model/runContracts";

vi.mock("../api/planning", () => ({ answerPlanQuestion: vi.fn(), implementRunPlan: vi.fn() }));
vi.mock("../api/runs", () => ({ fetchRunSnapshot: vi.fn() }));

const input = { input_id: "q-1", goal_version: 1, generation: 0, created_at: "",
  questions: [{ id: "scope", question: "检查哪些模块？", options: [{ label: "当前模块", description: "限定范围" }] }] };
function waiting() {
  return { ...createRunProjection("r-1"), status: "waiting_input" as const, collaborationMode: "plan" as const, pendingInput: input };
}
function ready() {
  const value = createRunProjection("r-1");
  return { ...value, status: "completed" as const, collaborationMode: "plan" as const,
    runOutcome: { ...value.runOutcome, goal_outcome: "answered" as const },
    plan: { version: 3, items: [{ item_key: "read", ordinal: 1, title: "检查模块", detail: "先读取代码", status: "pending" as const }] } };
}
const mounted: ReturnType<typeof mount>[] = [];
afterEach(() => mounted.splice(0).forEach(wrapper => wrapper.unmount()));
beforeEach(() => vi.resetAllMocks());

describe("规划协作", () => {
  it("不默认选择答案，允许自定义回答并提交精确的问题版本", async () => {
    vi.mocked(fetchRunSnapshot).mockResolvedValue({ state_version: 8, pending_input: input } as RunSnapshot);
    vi.mocked(answerPlanQuestion).mockResolvedValue({ request_id: "a", kind: "answer", status: "applied", result_run_id: "r-1" });
    const wrapper = mount(PlanningInteractionPanel, { props: { projection: waiting() } }); mounted.push(wrapper);
    expect(wrapper.get('[data-testid="planning-answer"]').attributes("disabled")).toBeDefined();
    await wrapper.get("textarea").setValue("只看入口代码");
    await wrapper.get("form").trigger("submit"); await flushPromises();
    expect(answerPlanQuestion).toHaveBeenCalledWith("r-1", expect.objectContaining({ input_id: "q-1", expected_state_version: 8, answers: { scope: "只看入口代码" } }));
    expect(wrapper.emitted("refresh")).toHaveLength(1);
  });

  it("问题更换后清除旧草稿，迟到响应不影响新问题", async () => {
    let resolve!: (value: RunSnapshot) => void;
    vi.mocked(fetchRunSnapshot).mockImplementation(() => new Promise(done => { resolve = done; }));
    const wrapper = mount(PlanningInteractionPanel, { props: { projection: waiting() } }); mounted.push(wrapper);
    await wrapper.get("textarea").setValue("当前模块");
    await wrapper.get("form").trigger("submit");
    await wrapper.setProps({ projection: { ...waiting(), pendingInput: { ...input, input_id: "q-2" } } });
    resolve({ state_version: 8, pending_input: input } as RunSnapshot); await flushPromises();
    expect(answerPlanQuestion).not.toHaveBeenCalled();
    expect((wrapper.get("textarea").element as HTMLTextAreaElement).value).toBe("");
  });

  it("计划版本冲突时不执行，保持可核对的错误说明", async () => {
    vi.mocked(fetchRunSnapshot).mockResolvedValue({ state_version: 8, status: "completed", plan: { version: 4, items: [] } } as unknown as RunSnapshot);
    const wrapper = mount(PlanningInteractionPanel, { props: { projection: ready() } }); mounted.push(wrapper);
    await wrapper.get('[data-testid="planning-implement"]').trigger("click"); await flushPromises();
    expect(implementRunPlan).not.toHaveBeenCalled();
    expect(wrapper.get('[role="alert"]').text()).toContain("任务已变化");
  });

  it("实施结果不确定时重用请求标识，成功后切换到关联任务", async () => {
    vi.mocked(fetchRunSnapshot).mockResolvedValue({ state_version: 8, status: "completed", checkpoint_id: "cp", plan: { version: 3, items: [] } } as unknown as RunSnapshot);
    vi.mocked(implementRunPlan).mockRejectedValueOnce(new Error("网络中断"))
      .mockResolvedValueOnce({ request_id: "a", kind: "implement", status: "applied", result_run_id: "child" });
    const wrapper = mount(PlanningInteractionPanel, { props: { projection: ready() } }); mounted.push(wrapper);
    await wrapper.get('[data-testid="planning-implement"]').trigger("click"); await flushPromises();
    await wrapper.get('[data-testid="planning-implement"]').trigger("click"); await flushPromises();
    const calls = vi.mocked(implementRunPlan).mock.calls;
    expect(calls[0][1]).toEqual(calls[1][1]);
    expect(calls[1][1]).toMatchObject({ expected_plan_version: 3, expected_state_version: 8, checkpoint_id: "cp" });
    expect(wrapper.emitted("implemented")).toEqual([["child"]]);
  });

  it("卸载后不再提交，普通执行任务不显示实施入口", async () => {
    const wrapper = mount(PlanningInteractionPanel, { props: { projection: { ...ready(), collaborationMode: "default" } } });
    expect(wrapper.find('[data-testid="planning-implement"]').exists()).toBe(false);
    wrapper.unmount();
    let resolve!: (value: RunSnapshot) => void;
    vi.mocked(fetchRunSnapshot).mockImplementation(() => new Promise(done => { resolve = done; }));
    const active = mount(PlanningInteractionPanel, { props: { projection: ready() } });
    await active.get('[data-testid="planning-implement"]').trigger("click"); active.unmount();
    resolve({ state_version: 8, status: "completed", plan: { version: 3, items: [] } } as unknown as RunSnapshot);
    await flushPromises(); expect(implementRunPlan).not.toHaveBeenCalled();
  });
});
