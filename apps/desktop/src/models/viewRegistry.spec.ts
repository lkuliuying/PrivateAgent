import { describe, expect, it } from "vitest";
import {
  NAV_GROUPS,
  SYSTEM_GROUP,
  VIEW_REGISTRY,
  groupViews,
  viewLabel,
} from "./viewRegistry";

describe("viewRegistry", () => {
  it("覆盖全部 View 联合类型成员（v0.8.0 W1 新增 coding）", () => {
    const keys = Object.keys(VIEW_REGISTRY).sort();
    expect(keys).toEqual(
      [
        "chat",
        "coding",
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

  it("一级导航分组与系统分组互不重叠且覆盖全部旧视图；coding 组不进旧 NavRail", () => {
    const nav = NAV_GROUPS.flatMap((group) => groupViews(group).map((m) => m.key));
    const system = groupViews(SYSTEM_GROUP).map((m) => m.key);
    // v0.8.0 W1：coding 视图经内部 flag 启用，不进入旧 NavRail 分组渲染
    expect([...nav, ...system, "coding"].sort()).toEqual(Object.keys(VIEW_REGISTRY).sort());
    expect([...system].sort()).toEqual(["backup", "diagnostics", "settings"]);
    expect(NAV_GROUPS).not.toContain("coding");
    expect(SYSTEM_GROUP).not.toBe("coding");
  });

  it("每组至少一个入口；渲染分组保持 D0 冻结的 6 组（coding 为非渲染组）", () => {
    const groups = new Set(Object.values(VIEW_REGISTRY).map((m) => m.group));
    expect(groups.size).toBe(7);
    for (const group of groups) {
      expect(groupViews(group).length).toBeGreaterThan(0);
    }
    // 旧 NavRail 实际渲染的分组数量不变
    expect(NAV_GROUPS.length + 1).toBe(6);
  });

  it("coding 视图为文档式主区（无通用顶栏）", () => {
    expect(VIEW_REGISTRY.coding.showTopbar).toBe(false);
  });

  it("chat 视图标记任务状态展示", () => {
    expect(VIEW_REGISTRY.chat.showsTaskState).toBe(true);
  });

  it("viewLabel 返回中文短名", () => {
    expect(viewLabel("today")).toBe("今日");
    expect(viewLabel("backup")).toBe("备份");
  });
});
