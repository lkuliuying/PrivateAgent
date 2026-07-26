import { flushPromises, shallowMount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import LearningWorkspace from "./LearningWorkspace.vue";

const api = vi.hoisted(() => ({
  listLearningTopics: vi.fn(),
  createLearningTopic: vi.fn(),
  updateLearningTopic: vi.fn(),
  generateLearningPlan: vi.fn(),
  listLearningNodes: vi.fn(),
  saveLearningNote: vi.fn(),
  listLearningNotes: vi.fn(),
  generateQuiz: vi.fn(),
  listQuizzes: vi.fn(),
  gradeQuizAnswer: vi.fn(),
  generateCards: vi.fn(),
  listCards: vi.fn(),
  listReviewsToday: vi.fn(),
  reviewCard: vi.fn(),
  topicDashboard: vi.fn(),
  weakPoints: vi.fn(),
  wrongAnswers: vi.fn(),
  weeklyReport: vi.fn(),
}));

vi.mock("../api", () => api);

vi.mock("../stores/notifications", () => ({
  useNotifications: () => ({
    success: vi.fn(),
    error: vi.fn(),
  }),
}));

const topics = [
  {
    id: 1,
    title: "系统设计",
    goal: "建立架构判断力",
    level: "进阶",
    status: "active",
    tags_json: [],
  },
  {
    id: 2,
    title: "性能工程",
    goal: "掌握性能诊断",
    level: "中级",
    status: "active",
    tags_json: [],
  },
];

const node = (id: number, title: string) => ({
  id,
  topic_id: 1,
  title,
  summary: "",
  order_index: 0,
  mastery_level: "unknown",
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

async function mountLearning() {
  const wrapper = shallowMount(LearningWorkspace);
  await flushPromises();
  return wrapper;
}

beforeEach(() => {
  Object.values(api).forEach((mock) => mock.mockReset());
  api.listLearningTopics.mockResolvedValue(topics);
  api.listLearningNodes.mockResolvedValue([node(1, "初始节点")]);
  api.listLearningNotes.mockResolvedValue([]);
  api.listQuizzes.mockResolvedValue([]);
  api.listCards.mockResolvedValue([]);
  api.listReviewsToday.mockResolvedValue([]);
  api.topicDashboard.mockResolvedValue(null);
  api.weakPoints.mockResolvedValue([]);
  api.wrongAnswers.mockResolvedValue([]);
});

describe("LearningWorkspace async state", () => {
  it("卸载后忽略初始主题响应且不继续请求详情", async () => {
    const pendingTopics = deferred<typeof topics>();
    api.listLearningTopics.mockImplementationOnce(() => pendingTopics.promise);
    const wrapper = shallowMount(LearningWorkspace);

    wrapper.unmount();
    pendingTopics.resolve(topics);
    await flushPromises();

    expect(api.listReviewsToday).not.toHaveBeenCalled();
    expect(api.listLearningNodes).not.toHaveBeenCalled();
  });

  it("快速切换主题时忽略旧主题的迟到响应", async () => {
    const wrapper = await mountLearning();
    const slow = deferred<ReturnType<typeof node>[]>();
    const fast = deferred<ReturnType<typeof node>[]>();
    api.listLearningNodes
      .mockImplementationOnce(() => slow.promise)
      .mockImplementationOnce(() => fast.promise);

    const topicButtons = wrapper.findAll(".topic-item");
    await topicButtons[1].trigger("click");
    await topicButtons[0].trigger("click");

    fast.resolve([node(3, "最后选择的节点")]);
    await flushPromises();
    slow.resolve([node(2, "过期节点")]);
    await flushPromises();
    await wrapper.findAll(".tabs button")[1].trigger("click");

    expect(wrapper.text()).toContain("最后选择的节点");
    expect(wrapper.text()).not.toContain("过期节点");
    wrapper.unmount();
  });

  it("当前主题加载失败时给出可见反馈", async () => {
    const wrapper = await mountLearning();
    api.listLearningNodes.mockRejectedValueOnce(new Error("后端暂不可用"));

    await wrapper.findAll(".topic-item")[1].trigger("click");
    await flushPromises();

    expect(wrapper.get('[role="alert"]').text()).toContain("后端暂不可用");
    wrapper.unmount();
  });
});
