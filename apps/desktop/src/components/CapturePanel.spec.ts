import { mount, flushPromises } from "@vue/test-utils";
import { describe, it, expect, vi, beforeEach } from "vitest";
import CapturePanel from "./CapturePanel.vue";
import { listCapture, createCapture, captureToInbox } from "../api";

// 第八阶段 M1：CapturePanel 组件测试（加载 / 保存 / 转化）。
// 用 vi.mock factory + vi.mocked 访问桩，避免顶层变量 hoisting 问题。
vi.mock("../api", () => ({
  listCapture: vi.fn(),
  createCapture: vi.fn(),
  captureToInbox: vi.fn(),
  captureToReminder: vi.fn(),
  captureToMemory: vi.fn(),
}));
vi.mock("../stores/notifications", () => ({
  useNotifications: () => ({
    success: vi.fn(),
    error: vi.fn(),
    info: vi.fn(),
    warning: vi.fn(),
  }),
}));

const sampleItem = {
  id: 1,
  title: "T1",
  content_md: "内容一",
  source: "manual",
  candidate_type: "inbox",
  status: "pending",
  target_type: null,
  target_id: null,
  created_at: "",
  handled_at: null,
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe("CapturePanel", () => {
  it("挂载时加载 pending 捕获列表", async () => {
    vi.mocked(listCapture).mockResolvedValue([sampleItem]);
    const w = mount(CapturePanel);
    await flushPromises();
    expect(listCapture).toHaveBeenCalledWith({ status: "pending" });
    expect(w.text()).toContain("T1");
    w.unmount();
  });

  it("保存草稿调用 createCapture", async () => {
    vi.mocked(listCapture).mockResolvedValue([]);
    vi.mocked(createCapture).mockResolvedValue({} as never);
    const w = mount(CapturePanel);
    await flushPromises();
    await w.find(".cap-text").setValue("新捕获内容");
    await w.find(".cap-title").setValue("标题");
    await w.find("button.pa-btn--primary").trigger("click");
    await flushPromises();
    expect(createCapture).toHaveBeenCalledWith(
      expect.objectContaining({
        content_md: "新捕获内容",
        title: "标题",
        source: "manual",
        candidate_type: "inbox",
      })
    );
    w.unmount();
  });

  it("空内容不保存", async () => {
    vi.mocked(listCapture).mockResolvedValue([]);
    const w = mount(CapturePanel);
    await flushPromises();
    await w.find("button.pa-btn--primary").trigger("click");
    await flushPromises();
    expect(createCapture).not.toHaveBeenCalled();
    w.unmount();
  });

  it("转收件箱调用 captureToInbox", async () => {
    vi.mocked(listCapture).mockResolvedValue([{ ...sampleItem, id: 7, title: "X" }]);
    vi.mocked(captureToInbox).mockResolvedValue(undefined as never);
    const w = mount(CapturePanel);
    await flushPromises();
    const convertBtn = w.find('button[title="转收件箱"]');
    await convertBtn.trigger("click");
    await flushPromises();
    expect(captureToInbox).toHaveBeenCalledWith(7);
    w.unmount();
  });
});
