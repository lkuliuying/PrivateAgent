import { describe, expect, it, beforeEach } from "vitest";
import { useViewHistory } from "./useViewHistory";

describe("useViewHistory", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("默认视图为 chat，导航后更新 current", () => {
    const history = useViewHistory("chat");
    expect(history.current.value).toBe("chat");
    history.navigate({ view: "today" });
    expect(history.current.value).toBe("today");
  });

  it("back/forward 在栈内往返", () => {
    const history = useViewHistory("chat");
    history.navigate({ view: "today" });
    history.navigate({ view: "kb" });
    expect(history.state().canGoBack).toBe(true);
    expect(history.state().canGoForward).toBe(false);

    const backTarget = history.back();
    expect(backTarget?.view).toBe("today");
    expect(history.current.value).toBe("today");
    expect(history.state().canGoForward).toBe(true);

    const forwardTarget = history.forward();
    expect(forwardTarget?.view).toBe("kb");
    expect(history.current.value).toBe("kb");
    expect(history.state().canGoForward).toBe(false);
  });

  it("同视图重复导航不重复入栈，且更新定位参数", () => {
    const history = useViewHistory("chat");
    history.navigate({ view: "today" });
    history.navigate({ view: "chat", sessionId: 7 });
    history.navigate({ view: "chat", sessionId: 8 });
    expect(history.state().canGoBack).toBe(true);
    history.back();
    history.back();
    expect(history.state().canGoBack).toBe(false);
    history.forward();
    const restored = history.forward();
    expect(restored?.sessionId).toBe(8);
  });

  it("恢复上次视图（localStorage）", () => {
    const first = useViewHistory("chat");
    first.navigate({ view: "kb" });
    const second = useViewHistory("chat");
    expect(second.current.value).toBe("kb");
  });

  it("返回完整还原 sessionId 与 params（会话级返回）", () => {
    const history = useViewHistory("chat");
    history.navigate({ view: "today" });
    history.navigate({
      view: "chat",
      sessionId: 42,
      params: { doc: "knowledge-base" },
    });
    const backTarget = history.back();
    expect(backTarget?.view).toBe("today");
    expect(backTarget?.sessionId).toBeUndefined();

    const forwardTarget = history.forward();
    expect(forwardTarget?.view).toBe("chat");
    expect(forwardTarget?.sessionId).toBe(42);
    expect(forwardTarget?.params).toEqual({ doc: "knowledge-base" });
  });

  it("前进后再导航会清空前进栈", () => {
    const history = useViewHistory("chat");
    history.navigate({ view: "today" });
    history.navigate({ view: "kb" });
    history.back();
    expect(history.state().canGoForward).toBe(true);
    history.navigate({ view: "projects" });
    expect(history.state().canGoForward).toBe(false);
  });
});
