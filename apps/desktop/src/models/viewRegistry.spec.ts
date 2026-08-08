import { describe, expect, it } from "vitest";
import {
  NAV_GROUPS,
  SYSTEM_GROUP,
  VIEW_REGISTRY,
  groupViews,
  viewLabel,
} from "./viewRegistry";

describe("viewRegistry", () => {
  it("覆盖全部 View 联合类型成员", () => {
    const keys = Object.keys(VIEW_REGISTRY).sort();
    expect(keys).toEqual(
      [
        "chat",
        "today",
        "kb",
        "projects",
        "learning",
        "tasks",
        "memory",
        "settings",
        "diagnostics",
        "extensions",
        "integrations",
        "backup",
      ].sort()
    );
  });

  it("一级导航分组与系统分组互不重叠且覆盖全部视图", () => {
    const nav = NAV_GROUPS.flatMap((group) => groupViews(group).map((m) => m.key));
    const system = groupViews(SYSTEM_GROUP).map((m) => m.key);
    expect([...nav, ...system].sort()).toEqual(Object.keys(VIEW_REGISTRY).sort());
    expect([...system].sort()).toEqual(["backup", "diagnostics", "settings"]);
  });

  it("每组至少一个入口，且分组不超过 D0 冻结的 6 组", () => {
    const groups = new Set(Object.values(VIEW_REGISTRY).map((m) => m.group));
    expect(groups.size).toBe(6);
    for (const group of groups) {
      expect(groupViews(group).length).toBeGreaterThan(0);
    }
  });

  it("chat 视图标记任务状态展示", () => {
    expect(VIEW_REGISTRY.chat.showsTaskState).toBe(true);
  });

  it("viewLabel 返回中文短名", () => {
    expect(viewLabel("today")).toBe("今日");
    expect(viewLabel("backup")).toBe("备份");
  });
});
