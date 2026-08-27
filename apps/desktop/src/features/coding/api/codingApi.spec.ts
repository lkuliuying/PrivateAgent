import { describe, expect, it } from "vitest";
import { toProjectSummary, toWorkspaceSummary } from "./projects";
import { toThreadSummary } from "./threads";
import { toCodingApiError } from "./codingHttp";
import { toModelProfileDetail } from "./modelProfiles";
import type { Project, ProjectWorkspace, Session } from "../../../types";

describe("coding api 映射层", () => {
  it("项目映射剔除 root_path（敏感字段红线）", () => {
    const dto: Project = {
      id: 1,
      name: "PrivateAgent",
      root_path: "C:\\Users\\secret\\agent",
      language: "python",
      framework: null,
      status: "active",
      last_scanned_at: null,
      created_at: "2026-08-01T00:00:00Z",
      updated_at: "2026-08-22T00:00:00Z",
    };
    const summary = toProjectSummary(dto);
    expect(summary).toEqual({
      id: 1,
      name: "PrivateAgent",
      status: "active",
      updatedAt: "2026-08-22T00:00:00Z",
    });
    expect(JSON.stringify(summary)).not.toContain("root_path");
  });

  it("工作区映射保留分支与状态，剔除路径与 hash 指纹以外的敏感字段", () => {
    const dto: ProjectWorkspace = {
      id: 101,
      project_id: 1,
      kind: "git_worktree",
      root_path: "F:\\worktrees\\feature",
      branch_name: "feature/x",
      head_sha: "ab" + "0".repeat(38),
      status: "dirty",
      last_used_at: "2026-08-22T01:00:00Z",
      created_at: "2026-08-01T00:00:00Z",
      updated_at: "2026-08-22T01:00:00Z",
    };
    const summary = toWorkspaceSummary(dto, 1);
    expect(summary).toEqual({
      id: 101,
      projectId: 1,
      kind: "git_worktree",
      branchName: "feature/x",
      headSha: "ab" + "0".repeat(38),
      status: "dirty",
      lastUsedAt: "2026-08-22T01:00:00Z",
    });
    expect(JSON.stringify(summary)).not.toContain("root_path");
    expect(JSON.stringify(summary)).not.toContain("F:");
  });

  it("线程映射保留 workspace 归属与最近 run", () => {
    const dto: Session = {
      id: 11,
      title: "修复窄屏遮挡",
      created_at: "2026-08-20T00:00:00Z",
      updated_at: "2026-08-22T02:00:00Z",
      project_id: 1,
      workspace_id: 101,
      kind: "coding",
      last_run_id: "run-abc",
      pinned_at: null,
      archived_at: null,
    };
    expect(toThreadSummary(dto, 1)).toEqual({
      id: 11,
      title: "修复窄屏遮挡",
      projectId: 1,
      workspaceId: 101,
      updatedAt: "2026-08-22T02:00:00Z",
      lastRunId: "run-abc",
      // v0.9.0 H4：置顶/归档/类型事实（additive）
      pinnedAt: null,
      archivedAt: null,
      kind: "coding",
    });
  });

  it("错误响应解析为 {error_code, detail} 契约；非 JSON 体按 unknown 收敛", async () => {
    const jsonError = new Response(
      JSON.stringify({ error_code: "workspace_outside_trust", detail: "工作区不在授权路径内" }),
      { status: 403 }
    );
    const parsed = await toCodingApiError(jsonError);
    expect(parsed).toEqual({
      status: 403,
      code: "workspace_outside_trust",
      message: "工作区不在授权路径内",
    });

    const htmlError = new Response("<html>bad gateway</html>", { status: 502 });
    const fallback = await toCodingApiError(htmlError);
    expect(fallback.code).toBe("unknown");
    expect(fallback.status).toBe(502);
  });

  // v0.9.0 H1-D（§5.8）：profile 详情映射（含具体模型路由字段与默认标记）
  it("模型 profile 映射携带 model_name/is_default；旧字段缺失不猜默认能力", () => {
    const detail = toModelProfileDetail({
      id: "ollama-default",
      provider: "ollama",
      display_name: "本地编码模型",
      model_name: "qwen3-coder",
      is_default: true,
      is_local: true,
      reasoning_efforts: ["low", "high"],
      enabled: true,
    });
    expect(detail).toMatchObject({
      id: "ollama-default",
      modelName: "qwen3-coder",
      isDefault: true,
      displayName: "本地编码模型",
      contextTokens: 8192,
      enabled: true,
    });
    // 历史 profile（无 model_name）如实为 null（运行期失败关闭，不回填全局值）
    const legacy = toModelProfileDetail({
      id: "legacy",
      provider: "ollama",
      display_name: "历史",
      is_local: true,
      reasoning_efforts: null,
      enabled: true,
    });
    expect(legacy.modelName).toBeNull();
    expect(legacy.isDefault).toBe(false);
  });
});
