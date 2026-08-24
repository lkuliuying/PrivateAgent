/**
 * v0.9.0 H1-B（计划 §5.6）· run 创建阻塞项诊断测试
 *
 * 覆盖：后端创建链全部平铺 error_code 均有阻塞项与恢复入口；未知码
 * 收敛为通用阻塞（不猜测）；恢复动作词汇表冻结。
 */
import { describe, expect, it } from "vitest";
import { describeRunBlocker } from "./runBlocking";

describe("describeRunBlocker", () => {
  it("模型类阻塞 → 配置 PrivateAgent 入口", () => {
    for (const code of ["model_profile_not_found", "model_profile_unsupported"]) {
      const facts = describeRunBlocker(code);
      expect(facts.recovery).toBe("configure-model");
      expect(facts.title).toBeTruthy();
      expect(facts.hint).toBeTruthy();
    }
  });

  it("项目/工作区类阻塞 → 选择项目或重新授权", () => {
    expect(describeRunBlocker("workspace_not_found").recovery).toBe("select-project");
    expect(describeRunBlocker("coding_context_incomplete").recovery).toBe("select-project");
    expect(describeRunBlocker("session_not_coding").recovery).toBe("select-project");
    expect(describeRunBlocker("workspace_outside_trust").recovery).toBe("reauthorize");
    expect(describeRunBlocker("workspace_unavailable").recovery).toBe("reauthorize");
  });

  it("full_access 类阻塞 → 失败关闭且可重新发起（不静默降级提示）", () => {
    for (const code of [
      "full_access_unsupported",
      "full_access_revoked",
      "full_access_grant_expired",
    ]) {
      const facts = describeRunBlocker(code);
      expect(facts.recovery).toBe("retry");
      expect(facts.title).toContain("完全访问");
    }
  });

  it("上下文超限 → 新开会话恢复路径", () => {
    expect(describeRunBlocker("budget_exceeded").recovery).toBe("select-project");
    expect(describeRunBlocker("budget_exceeded").recoveryLabel).toContain("新开会话");
  });

  it("未知/null 错误码收敛为通用阻塞（不猜测、不隐藏）", () => {
    expect(describeRunBlocker(null).title).toBe("执行创建失败");
    expect(describeRunBlocker("never_seen_code").recovery).toBe("retry");
  });
});
