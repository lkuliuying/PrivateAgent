import { describe, expect, it } from "vitest";
import {
  deriveAgentWorkspaceFacts,
  gitStateLabel,
  shortSha,
  truncatePath,
} from "./workspaceFacts";

describe("deriveAgentWorkspaceFacts（W6-R3 工作目录/Git 事实）", () => {
  const base = {
    id: 1,
    project_id: 1,
    kind: "root",
    root_path: "F:/workspace/demo",
    status: "active",
  };

  it("无项目绑定 → no-project（不沿用旧值）", () => {
    const facts = deriveAgentWorkspaceFacts({ hasProject: false, workspace: null });
    expect(facts.git.kind).toBe("no-project");
    expect(facts.rootPath).toBeNull();
  });

  it("正常分支 + HEAD → branch 与短 sha", () => {
    const facts = deriveAgentWorkspaceFacts({
      hasProject: true,
      workspace: { ...base, branch_name: "main", head_sha: "a".repeat(40) },
    });
    expect(facts.git.kind).toBe("branch");
    expect(gitStateLabel(facts.git)).toBe("main");
    expect(facts.rootPath).toBe("F:/workspace/demo");
  });

  it("有 HEAD 无分支名 → detached", () => {
    const facts = deriveAgentWorkspaceFacts({
      hasProject: true,
      workspace: { ...base, branch_name: null, head_sha: "b".repeat(40) },
    });
    expect(facts.git.kind).toBe("detached");
    expect(gitStateLabel(facts.git)).toContain("detached");
    expect(gitStateLabel(facts.git)).toContain(shortSha("b".repeat(40)));
  });

  it("无分支无 HEAD → 非 Git 目录", () => {
    const facts = deriveAgentWorkspaceFacts({
      hasProject: true,
      workspace: { ...base, branch_name: null, head_sha: null },
    });
    expect(facts.git.kind).toBe("non-git");
    expect(gitStateLabel(facts.git)).toBe("非 Git 目录");
  });

  it("路径缺失/归档 → path-invalid 并附真实原因", () => {
    const missing = deriveAgentWorkspaceFacts({
      hasProject: true,
      workspace: { ...base, branch_name: "main", head_sha: null, status: "missing" },
    });
    expect(missing.git.kind).toBe("path-invalid");
    expect(gitStateLabel(missing.git)).toBe("路径缺失");

    const archived = deriveAgentWorkspaceFacts({
      hasProject: true,
      workspace: { ...base, branch_name: null, head_sha: null, status: "archived" },
    });
    expect(gitStateLabel(archived.git)).toBe("工作区已归档");
  });

  it("工作区未找到 → 目录不可用（不用上一任务旧值冒充）", () => {
    const facts = deriveAgentWorkspaceFacts({ hasProject: true, workspace: null });
    expect(facts.git.kind).toBe("path-invalid");
    expect(facts.rootPath).toBeNull();
  });

  it("长路径截断保留首末段，完整值由调用方经 tooltip/复制提供", () => {
    const long = "F:/very/deep/nested/project/path/with/many/segments/demo-project";
    const truncated = truncatePath(long);
    expect(truncated.length).toBeLessThan(long.length);
    expect(truncated).toContain("…");
    expect(truncated.endsWith("demo-project")).toBe(true);
    expect(truncatePath("F:/a")).toBe("F:/a");
  });
});
