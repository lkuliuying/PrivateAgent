import { expect, it } from "vitest";
import type { PatchChange, PatchSummary } from "../api/patches";
import { summarizeEditedFiles } from "./patchSummary";

const change: PatchChange = { change_id: "one", rel_path: "src/app.ts", operation: "update", before_kind: "file", after_kind: "file", diff_chars: 30, additions: 3, deletions: 1 };
const patch: PatchSummary = { patch_set_id: "patch", run_id: "run", preview_sha256: "sha", status: "applied", kind: "patch", conflicts: [],
  changes: [change], journal: [{ change_id: "one", rel_path: change.rel_path, status: "applied" }] };

it("只统计日志已确认落盘的文件，不把预览、目录或未知结果计入", () => {
  expect(summarizeEditedFiles([{ ...patch, status: "validated", journal: [] }])).toEqual([]);
  expect(summarizeEditedFiles([{ ...patch, status: "interrupted", journal: [{ ...patch.journal[0], status: "applying" }] }])).toEqual([]);
  expect(summarizeEditedFiles([{ ...patch, changes: [{ ...change, before_kind: "missing", after_kind: "directory" }] }])).toEqual([]);
  expect(summarizeEditedFiles([{ ...patch, status: "partially_applied", changes: [change, { ...change, change_id: "two", rel_path: "not-written.ts" }] }]))
    .toEqual([{ path: change.rel_path, additions: 3, deletions: 1 }]);
});

it("同一文件多次写入合并计数，已实际回滚的部分从摘要中排除", () => {
  const second = { ...patch, patch_set_id: "second", changes: [{ ...change, additions: 2, deletions: 4 }] };
  expect(summarizeEditedFiles([patch, second])).toEqual([{ path: change.rel_path, additions: 5, deletions: 5 }]);
  const undo: PatchSummary = { ...patch, kind: "rollback", patch_set_id: "undo", rollback_of: "patch" };
  expect(summarizeEditedFiles([patch, second, undo])).toEqual([{ path: change.rel_path, additions: 2, deletions: 4 }]);
  expect(summarizeEditedFiles([patch, { ...undo, journal: [] }])).toEqual([{ path: change.rel_path, additions: 3, deletions: 1 }]);
});

it("旧记录缺少统计或数值无效时保留未知，不伪造零行变更", () => {
  for (const additions of [undefined, -1, Infinity, 1.5]) {
    expect(summarizeEditedFiles([patch, { ...patch, changes: [{ ...change, additions }] }]))
      .toEqual([{ path: change.rel_path, additions: null, deletions: 2 }]);
  }
});
