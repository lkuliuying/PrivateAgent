import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, expect, it, vi } from "vitest";
import PatchReviewPanel from "./PatchReviewPanel.vue";
import { applyRollback, fetchPatches, previewRollback, type PatchSummary } from "../api/patches";

const confirm = vi.hoisted(() => vi.fn());
vi.mock("../../../stores/notifications", () => ({ useNotifications: () => ({ confirm }) }));
vi.mock("../api/patches", async importOriginal => ({ ...await importOriginal<typeof import("../api/patches")>(),
  fetchPatches: vi.fn(), previewRollback: vi.fn(), applyRollback: vi.fn() }));
const patch: PatchSummary = { patch_set_id: "patch", run_id: "run", preview_sha256: "sha", status: "applied", kind: "patch",
  changes: [{ change_id: "x", operation: "create", rel_path: "x", before_kind: "missing", after_kind: "file", diff_chars: 2 }], conflicts: [], journal: [] };
const undo: PatchSummary = { ...patch, patch_set_id: "undo", kind: "rollback", status: "validated" };
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(fetchPatches).mockResolvedValue({ patches: [patch], baseline: { is_git: true, head_sha: "abcdef", current_branch: "dev", dirty: true, dirty_entries: [{ rel_path: "user.txt", status: " M" }] },
    current_git: { is_git: true, head_sha: "abcdef", current_branch: "dev", dirty: true }, ownership_note: "当前 Git 状态可能包含外部修改" });
  vi.mocked(previewRollback).mockResolvedValue(undo);
  vi.mocked(applyRollback).mockResolvedValue({ ...undo, status: "applied" });
});
const button = (wrapper: ReturnType<typeof mount>, label: string) => wrapper.findAll("button").find(item => item.text() === label)!;

it("展示起始用户改动，回滚预览不会直接写入，确认后绑定预览应用", async () => {
  confirm.mockResolvedValue(true);
  const wrapper = mount(PatchReviewPanel, { props: { runId: "run", active: false } });
  await flushPromises();
  expect(wrapper.text()).toContain("user.txt");
  await button(wrapper, "预览回滚").trigger("click");
  await flushPromises();
  expect(applyRollback).not.toHaveBeenCalled();
  await button(wrapper, "应用此回滚预览").trigger("click");
  await flushPromises();
  expect(confirm).toHaveBeenCalledOnce();
  expect(applyRollback).toHaveBeenCalledWith("run", "undo", "sha");
  wrapper.unmount();
});
it("任务切换期间的确认不得向新任务发送回滚", async () => {
  let resolve!: (value: boolean) => void;
  confirm.mockReturnValue(new Promise(done => { resolve = done; }));
  const wrapper = mount(PatchReviewPanel, { props: { runId: "run", active: false } });
  await flushPromises();
  await button(wrapper, "预览回滚").trigger("click");
  await flushPromises();
  await button(wrapper, "应用此回滚预览").trigger("click");
  await wrapper.setProps({ runId: "new" });
  resolve(true);
  await flushPromises();
  expect(applyRollback).not.toHaveBeenCalled();
  wrapper.unmount();
});
it("活动任务禁用回滚，冲突仅展示保留原因", async () => {
  const wrapper = mount(PatchReviewPanel, { props: { runId: "run", active: true } });
  await flushPromises();
  expect(button(wrapper, "预览回滚").attributes("disabled")).toBeDefined();
  await wrapper.setProps({ active: false });
  vi.mocked(previewRollback).mockResolvedValue({ ...undo, patch_set_id: null, status: "conflicted", conflicts: [{ rel_path: "user.txt", reason: "用户已编辑" }] });
  await button(wrapper, "预览回滚").trigger("click");
  await flushPromises();
  expect(wrapper.text()).toContain("已保留 user.txt");
  expect(wrapper.text()).not.toContain("应用此回滚预览");
  wrapper.unmount();
});
