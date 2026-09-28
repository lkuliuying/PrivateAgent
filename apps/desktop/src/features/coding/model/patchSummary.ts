import type { PatchSummary } from "../api/patches";

export interface EditedFileSummary {
  path: string;
  additions: number | null;
  deletions: number | null;
}

function appliedPaths(patch: PatchSummary): Set<string> {
  const latest = new Map(patch.journal.map(entry => [entry.change_id, entry]));
  return new Set(patch.changes.filter(change => latest.get(change.change_id)?.status === "applied")
    .map(change => change.rel_path));
}

export function summarizeEditedFiles(patches: PatchSummary[]): EditedFileSummary[] {
  const restored = new Map<string, Set<string>>();
  for (const patch of patches) {
    if (patch.kind !== "rollback" || !patch.rollback_of) continue;
    const paths = restored.get(patch.rollback_of) ?? new Set<string>();
    for (const path of appliedPaths(patch)) paths.add(path);
    restored.set(patch.rollback_of, paths);
  }
  const files = new Map<string, EditedFileSummary>();
  const count = (value: number | undefined) => Number.isSafeInteger(value) && value! >= 0 ? value! : null;
  for (const patch of patches) {
    if (patch.kind !== "patch") continue;
    const applied = appliedPaths(patch);
    for (const change of patch.changes) {
      if (!applied.has(change.rel_path) || restored.get(patch.patch_set_id ?? "")?.has(change.rel_path)
        || (change.before_kind !== "file" && change.after_kind !== "file")) continue;
      const previous = files.get(change.rel_path);
      const additions = count(change.additions);
      const deletions = count(change.deletions);
      // 统计已落盘操作的累计增删；旧记录缺少统计时保留未知，不显示为零。
      files.set(change.rel_path, {
        path: change.rel_path,
        additions: previous ? previous.additions === null || additions === null ? null : previous.additions + additions : additions,
        deletions: previous ? previous.deletions === null || deletions === null ? null : previous.deletions + deletions : deletions,
      });
    }
  }
  return [...files.values()];
}
