import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, expect, it, vi } from "vitest";
import { open } from "@tauri-apps/plugin-dialog";
import ApplicationBackup from "./ApplicationBackup.vue";
import AttachmentStoragePanel from "./AttachmentStoragePanel.vue";
import { previewBackup, importBackup, exportBackup } from "../api/backups";
import { getAttachmentStorage, previewAttachmentCleanup, applyAttachmentCleanup } from "../api/attachmentStorage";
const confirm = vi.hoisted(() => vi.fn());
vi.mock("../stores/notifications", () => ({ useNotifications: () => ({ confirm }) }));
vi.mock("@tauri-apps/plugin-dialog", () => ({ open: vi.fn() }));
vi.mock("../api/backups", () => ({ previewBackup: vi.fn(), importBackup: vi.fn(), exportBackup: vi.fn() }));
vi.mock("../api/attachmentStorage", () => ({ getAttachmentStorage: vi.fn(), previewAttachmentCleanup: vi.fn(), applyAttachmentCleanup: vi.fn() }));
beforeEach(() => { vi.clearAllMocks(); confirm.mockResolvedValue(true); });
it("预览冲突与目录映射，未选完整目录时不能恢复数据", async () => {
  vi.mocked(open).mockResolvedValue("F:/fixture/backup.json");
  vi.mocked(previewBackup).mockResolvedValue({ sha256: "a".repeat(64), kind: "application", home_layout: "compact", counts: { drafts: 1 }, warnings: [], providers: [{ id: "one", name: "模型服务", base_url: "https://fixture.test", conflict: true }], projects: [{ id: 1, name: "项目", root_path: "F:/old" }], workspaces: [{ id: 2, project_id: 1, root_path: "F:/old", kind: "root" }] });
  const wrapper = mount(ApplicationBackup);
  await wrapper.findAll("button").find(button => button.text() === "选择备份并预览")!.trigger("click"); await flushPromises();
  expect(wrapper.text()).toContain("供应商 ID 冲突：保留本机配置");
  const restore = wrapper.findAll("button").find(button => button.text() === "确认恢复历史、草稿和附件")!;
  expect(restore.attributes("disabled")).toBeDefined();
  vi.mocked(open).mockResolvedValue("F:/new-project");
  await wrapper.findAll("button").find(button => button.text() === "选择项目目录")!.trigger("click"); await flushPromises();
  expect(restore.attributes("disabled")).toBeUndefined();
  expect(importBackup).not.toHaveBeenCalled();
  vi.mocked(importBackup).mockResolvedValue({}); await restore.trigger("click"); await flushPromises();
  expect(importBackup).toHaveBeenCalledWith("F:/fixture/backup.json", "a".repeat(64), "data", { "1": "F:/new-project" }, { "2": "F:/new-project" });
  expect(wrapper.emitted("imported")).toEqual([["data", {}]]);
  wrapper.unmount();
});

it("导出直接下载 API Blob，卸载释放下载地址", async () => {
  const blob = new Blob(['{"temperature":1.0}'], { type: "application/json" });
  vi.mocked(exportBackup).mockResolvedValue(blob);
  const create = vi.fn(() => "blob:backup-test"), revoke = vi.fn();
  vi.stubGlobal("URL", class extends URL { static createObjectURL = create; static revokeObjectURL = revoke; });
  const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  const wrapper = mount(ApplicationBackup);
  try {
    await wrapper.findAll("button").find(button => button.text() === "导出应用数据备份")!.trigger("click"); await flushPromises();
    expect(create).toHaveBeenCalledWith(blob);
    expect(click).toHaveBeenCalledOnce();
    expect(wrapper.text()).toContain("请确认文件已保存");
  } finally { wrapper.unmount(); click.mockRestore(); vi.unstubAllGlobals(); }
  expect(revoke).toHaveBeenCalledWith("blob:backup-test");
});

it("预览显示来源信息与模型风险，重复导入结果展示真实计数", async () => {
  vi.mocked(open).mockResolvedValue("F:/fixture/backup.json");
  vi.mocked(previewBackup).mockResolvedValue({ sha256: "a".repeat(64), kind: "application", home_layout: "compact", format: "privateagent.backup.v2", created_at: "2026-10-02T10:00:00Z", size_bytes: 1024, coverage: ["历史", "草稿"], counts: { sessions: 2, messages: 3, attachments: 1, drafts: 1, draft_attachments: 2 }, providers: [], projects: [], workspaces: [], warnings: [], model_selections: [{ scope: "project", id: 1, profile_id: "same", source_scope: "global", source_identity: null, target_identity: null, requires_confirmation: true, reason: "旧备份未记录模型身份" }] });
  vi.mocked(importBackup).mockResolvedValue({ id: "import-one", already_imported: true, source_kind: "application", backup_format: "privateagent.backup.v2", imported_counts: { sessions: 2, attachments: 3, sent_attachments: 1, drafts: 1, draft_attachments: 2, model_selections: 1, models_pending_confirmation: 1 }, skipped_counts: { sessions: 1 } });
  const wrapper = mount(ApplicationBackup);
  await wrapper.findAll("button").find(button => button.text() === "选择备份并预览")!.trigger("click"); await flushPromises();
  expect(wrapper.text()).toContain("2026-10-02T10:00:00Z"); expect(wrapper.text()).toContain("1.0 KiB");
  expect(wrapper.text()).toContain("消息 3 条"); expect(wrapper.text()).toContain("需重新确认模型");
  await wrapper.findAll("button").find(button => button.text() === "确认恢复历史、草稿和附件")!.trigger("click"); await flushPromises();
  const result = wrapper.get('[aria-label="应用数据恢复结果"]');
  expect(result.text()).toContain("此备份已导入，沿用原结果"); expect(result.text()).toContain("import-one");
  expect(result.text()).toContain("待确认模型选择1");
  expect(result.text()).toContain("附件总数3"); expect(result.text()).toContain("已发送附件1");
  expect(result.text()).toContain("本次未导入数量会话1");
  expect(wrapper.emitted("imported")?.[0][0]).toBe("data");
  wrapper.unmount();
});

it("配置已成功但数据恢复失败时保留配置结果并明确失败原因", async () => {
  vi.mocked(open).mockResolvedValue("F:/fixture/backup.json");
  vi.mocked(previewBackup).mockResolvedValue({ sha256: "a".repeat(64), kind: "application", home_layout: "standard", counts: {}, providers: [], projects: [], workspaces: [], warnings: [] });
  vi.mocked(importBackup).mockResolvedValueOnce({ imported: ["source"], skipped: ["retained-provider"] }).mockRejectedValueOnce(new Error("磁盘空间不足，应用数据未导入"));
  const wrapper = mount(ApplicationBackup);
  await wrapper.findAll("button").find(button => button.text() === "选择备份并预览")!.trigger("click"); await flushPromises();
  await wrapper.findAll("button").find(button => button.text() === "确认导入普通配置")!.trigger("click"); await flushPromises();
  await wrapper.findAll("button").find(button => button.text() === "确认恢复历史、草稿和附件")!.trigger("click"); await flushPromises();
  expect(wrapper.get('[aria-label="普通配置导入结果"]').text()).toContain("新增供应商 1 个");
  expect(wrapper.get('[aria-label="普通配置导入结果"]').text()).toContain("新增供应商 ID：source");
  expect(wrapper.get('[aria-label="普通配置导入结果"]').text()).toContain("保留本机配置的供应商 ID：retained-provider");
  expect(wrapper.get('[role="alert"]').text()).toContain("磁盘空间不足，应用数据未导入");
  expect(wrapper.find('[aria-label="应用数据恢复结果"]').exists()).toBe(false);
  expect(wrapper.emitted("imported")?.map(event => event[0])).toEqual(["configuration"]);
  wrapper.unmount();
});

it("确认取消或组件卸载后不得开始导入", async () => {
  vi.mocked(open).mockResolvedValue("F:/fixture/backup.json");
  vi.mocked(previewBackup).mockResolvedValue({ sha256: "a".repeat(64), kind: "configuration", home_layout: "standard", counts: {}, providers: [], projects: [], workspaces: [], warnings: [] });
  let accept!: (value: boolean) => void;
  confirm.mockImplementationOnce(() => new Promise(resolve => { accept = resolve; }));
  const wrapper = mount(ApplicationBackup);
  await wrapper.findAll("button").find(button => button.text() === "选择备份并预览")!.trigger("click"); await flushPromises();
  await wrapper.findAll("button").find(button => button.text() === "确认导入普通配置")!.trigger("click");
  wrapper.unmount(); accept(true); await flushPromises();
  expect(importBackup).not.toHaveBeenCalled();
});
it("清理先显示引用和空间影响，取消后不执行删除", async () => {
  const item = { id: "a".repeat(32), name: "材料.txt", size_bytes: 20, sha256: "b".repeat(64), project_id: 1, workspace_id: 2, language: "txt", project_name: "项目", read_status: "可预览", drafts: [{ id: "c".repeat(32), title: "当前草稿", session_id: null, scope_key: "scope", revision: 1 }], sessions: [] };
  vi.mocked(getAttachmentStorage).mockResolvedValue({ total: 1, size_bytes: 20, offset: 0, items: [item], cache_bytes: 0, cache_policy: "按需解码", retention: "保留原件" });
  vi.mocked(previewAttachmentCleanup).mockResolvedValue({ version: "version", attachment_id: item.id, draft_id: item.drafts[0].id, name: item.name, draft: item.drafts[0], remaining_drafts: 0, sessions: [], reclaim_bytes: 20 });
  confirm.mockResolvedValue(false);
  const wrapper = mount(AttachmentStoragePanel, { global: { stubs: { TaskAttachmentList: true } } });
  await flushPromises();
  await wrapper.findAll("button").find(button => button.text() === "预览移除影响")!.trigger("click"); await flushPromises();
  expect(confirm.mock.calls[0][0].impact).toContain("预计释放 20 B");
  expect(applyAttachmentCleanup).not.toHaveBeenCalled();
  wrapper.unmount();
});
