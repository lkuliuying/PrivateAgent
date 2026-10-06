import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, expect, it, vi } from "vitest";
import HistoryMigration from "./HistoryMigration.vue";
import { apiFetch, ensureApiBase } from "../api/http";
import { exportHistoryArchive } from "../api/backups";

const confirm = vi.hoisted(() => vi.fn());
vi.mock("../api/http", () => ({ apiFetch: vi.fn(), ensureApiBase: vi.fn() }));
vi.mock("../api/backups", () => ({ exportHistoryArchive: vi.fn() }));
vi.mock("../stores/notifications", () => ({ useNotifications: () => ({ confirm, success: vi.fn() }) }));
const imported = { id: "application-import", created_at: "2026-10-02T10:00:00Z", source_kind: "application", backup_format: "privateagent.backup.v2", counts: { sessions: 2, agent_tasks: 0 }, imported_counts: { sessions: 2, drafts: 3, draft_attachments: 4, model_selections: 2, models_pending_confirmation: 1 } };
beforeEach(() => {
  vi.clearAllMocks(); confirm.mockResolvedValue(true);
  vi.mocked(ensureApiBase).mockResolvedValue("http://privateagent.localhost");
  vi.mocked(apiFetch).mockResolvedValue(Response.json([imported]));
});

it("应用导入记录包含草稿和模型待确认计数，并明确归档仅为历史子集", async () => {
  const wrapper = mount(HistoryMigration); await flushPromises();
  expect(wrapper.text()).toContain("应用数据备份"); expect(wrapper.text()).toContain("草稿 3 个");
  expect(wrapper.text()).toContain("未发送附件 4 个"); expect(wrapper.text()).toContain("待确认模型 1 个");
  expect(wrapper.text()).toContain("导出历史归档（不含配置和草稿）");
  expect(wrapper.text()).not.toContain("导出原始归档");
  wrapper.unmount();
});

it("数据回滚成功立即刷新记录并通知父组件，确认包含配置边界", async () => {
  vi.mocked(apiFetch).mockImplementation(async (_input, init) => init?.method === "POST" ? Response.json({ rolled_back: true }) : Response.json([imported]));
  const wrapper = mount(HistoryMigration); await flushPromises();
  await wrapper.findAll("button").find(button => button.text() === "核对并回滚数据")!.trigger("click"); await flushPromises();
  expect(confirm.mock.calls[0][0].impact).toContain("不撤销单独导入的模型配置");
  expect(wrapper.emitted("changed")).toEqual([[]]);
  expect(apiFetch).toHaveBeenCalledTimes(3);
  wrapper.unmount();
});

it("历史再导出使用原始 Blob 并告知未发送材料不在归档内", async () => {
  const blob = new Blob(['{"cost_usd":1.0}']);
  vi.mocked(exportHistoryArchive).mockResolvedValue(blob);
  const create = vi.fn(() => "blob:history-test"), revoke = vi.fn();
  vi.stubGlobal("URL", class extends URL { static createObjectURL = create; static revokeObjectURL = revoke; });
  const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  const wrapper = mount(HistoryMigration);
  try {
    await flushPromises();
    await wrapper.findAll("button").find(button => button.text() === "导出历史归档（不含配置和草稿）")!.trigger("click"); await flushPromises();
    expect(exportHistoryArchive).toHaveBeenCalledWith(imported.id);
    expect(create).toHaveBeenCalledWith(blob);
    expect(confirm.mock.calls[0][0].impact).toContain("不含配置、草稿、未发送附件和模型选择");
  } finally { wrapper.unmount(); click.mockRestore(); vi.unstubAllGlobals(); }
  expect(revoke).toHaveBeenCalledWith("blob:history-test");
});
