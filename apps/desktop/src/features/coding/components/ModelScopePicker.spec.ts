import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, expect, it, vi } from "vitest";
import ModelScopePicker from "./ModelScopePicker.vue";
import { getModelPreference, setModelPreference, type ModelPreference } from "../api/modelPreferences";
import type { CodingModelProfileSummary } from "../model/contracts";
vi.mock("../api/modelPreferences", () => ({ getModelPreference: vi.fn(), setModelPreference: vi.fn() }));
const preference: ModelPreference = { profile_id: "one", source: "project", overrides: { global: "one", project: "one", session: null }, available: true };
beforeEach(() => { vi.clearAllMocks(); vi.mocked(getModelPreference).mockResolvedValue(preference); });
it("显示实际来源，保存作用域通过显式按钮完成", async () => {
  const wrapper = mount(ModelScopePicker, { props: { projectId: 1, sessionId: 2, profiles: [] }, attachTo: document.body });
  await flushPromises();
  expect(wrapper.text()).toContain("项目设置");
  expect(setModelPreference).not.toHaveBeenCalled();
  await wrapper.get("button").trigger("click");
  await flushPromises();
  expect(document.querySelector('[role="dialog"]')?.textContent).toContain("继承上级设置");
  vi.mocked(setModelPreference).mockResolvedValue(preference);
  document.querySelector<HTMLButtonElement>('[role="dialog"] .pa-btn--primary')!.click();
  await flushPromises();
  expect(setModelPreference).toHaveBeenCalledWith("session", null, 1, 2);
  expect(wrapper.emitted("resolved")?.slice(-1)[0]).toEqual(["one", true]);
  wrapper.unmount();
});
it("迟到的旧项目响应不能替换新项目模型，失败时阻止发送", async () => {
  let finish!: (value: ModelPreference) => void;
  vi.mocked(getModelPreference).mockImplementationOnce(() => new Promise(resolve => { finish = resolve; })).mockResolvedValueOnce({ ...preference, profile_id: "missing", available: false });
  const wrapper = mount(ModelScopePicker, { props: { projectId: 1, sessionId: null, profiles: [] } });
  await wrapper.setProps({ projectId: 2 });
  await flushPromises();
  finish(preference); await flushPromises();
  expect(wrapper.emitted("resolved")?.slice(-1)[0]).toEqual(["missing", false]);
  expect(wrapper.text()).toContain("所选模型不可用");
  wrapper.unmount();
});

const restoredIdentity = { provider_id: "provider", protocol: "openai", api_format: "responses", base_url: "https://source.example.test/v1", model_id: "source-model" };
const pendingPreference: ModelPreference = { ...preference, profile_id: null, available: false, requires_confirmation: true, confirmation_reason: "同 ID 模型地址与原备份不同", restore_source: { profile_id: "one", source_scope: "global", source_identity: restoredIdentity } };
const profiles: CodingModelProfileSummary[] = [{ id: "one", provider: "openai", providerName: "当前服务", displayName: "目标模型", modelName: "target-model", isDefault: true, isLocal: false, contextTokens: 8192, reasoningEfforts: [] }];

it("恢复模型待确认时不预选同 ID，必须主动选择模型", async () => {
  vi.mocked(getModelPreference).mockResolvedValue(pendingPreference);
  const wrapper = mount(ModelScopePicker, { props: { projectId: 1, sessionId: null, profiles }, attachTo: document.body });
  await flushPromises();
  expect(wrapper.emitted("resolved")?.slice(-1)[0]).toEqual([null, false]);
  expect(wrapper.text()).toContain("恢复的模型待确认");
  await wrapper.get("button").trigger("click"); await flushPromises();
  const dialog = document.querySelector('[role="dialog"]')!;
  const choice = dialog.querySelector<HTMLSelectElement>('[aria-label="作用域模型"]')!;
  const save = dialog.querySelector<HTMLButtonElement>(".pa-btn--primary")!;
  expect(choice.value).not.toBe("one"); expect(save.disabled).toBe(true);
  expect(dialog.textContent).toContain(restoredIdentity.base_url);
  vi.mocked(setModelPreference).mockResolvedValue({ ...preference, requires_confirmation: false, confirmation_reason: null, restore_source: null });
  choice.value = "one"; choice.dispatchEvent(new Event("change", { bubbles: true })); await flushPromises();
  save.click(); await flushPromises();
  expect(setModelPreference).toHaveBeenCalledWith("project", "one", 1, null);
  expect(wrapper.emitted("resolved")?.slice(-1)[0]).toEqual(["one", true]);
  wrapper.unmount();
});

it("明确继承只清当前范围，服务端上级仍待确认时继续阻止发送", async () => {
  vi.mocked(getModelPreference).mockResolvedValue({ ...pendingPreference, source: "session" });
  vi.mocked(setModelPreference).mockResolvedValue(pendingPreference);
  const wrapper = mount(ModelScopePicker, { props: { projectId: 1, sessionId: 2, profiles }, attachTo: document.body });
  await flushPromises(); await wrapper.get("button").trigger("click"); await flushPromises();
  const choice = document.querySelector<HTMLSelectElement>('[aria-label="作用域模型"]')!;
  choice.value = ""; choice.dispatchEvent(new Event("change", { bubbles: true })); await flushPromises();
  document.querySelector<HTMLButtonElement>('[role="dialog"] .pa-btn--primary')!.click(); await flushPromises();
  expect(setModelPreference).toHaveBeenCalledWith("session", null, 1, 2);
  expect(wrapper.emitted("resolved")?.slice(-1)[0]).toEqual([null, false]);
  expect(wrapper.text()).toContain("确认前不能发送");
  wrapper.unmount();
});

it("切换保存范围不会把待确认 ID 自动选中", async () => {
  vi.mocked(getModelPreference).mockResolvedValue(pendingPreference);
  const wrapper = mount(ModelScopePicker, { props: { projectId: 1, sessionId: 2, profiles }, attachTo: document.body });
  await flushPromises(); await wrapper.get("button").trigger("click"); await flushPromises();
  const scope = document.querySelector<HTMLSelectElement>('[aria-label="模型应用范围"]')!;
  scope.value = "project"; scope.dispatchEvent(new Event("change", { bubbles: true })); await flushPromises();
  expect(document.querySelector<HTMLSelectElement>('[aria-label="作用域模型"]')!.value).not.toBe("one");
  expect(document.querySelector<HTMLButtonElement>('[role="dialog"] .pa-btn--primary')!.disabled).toBe(true);
  expect(setModelPreference).not.toHaveBeenCalled();
  wrapper.unmount();
});
