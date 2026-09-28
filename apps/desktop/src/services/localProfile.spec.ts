import { effectScope, type EffectScope } from "vue";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LOCAL_PROFILE_KEY, useLocalProfile } from "./localProfile";

const scopes: EffectScope[] = [];
function openProfile() {
  const scope = effectScope();
  scopes.push(scope);
  return scope.run(() => useLocalProfile())!;
}
beforeEach(() => localStorage.clear());
afterEach(() => { scopes.splice(0).forEach(scope => scope.stop()); vi.restoreAllMocks(); });

describe("本机资料共享状态", () => {
  it("读取原有格式，保存后所有消费者同步且不新增存储键", () => {
    localStorage.setItem(LOCAL_PROFILE_KEY, JSON.stringify({ nickname: "旧称呼", bio: "原简介", avatarDataUrl: "" }));
    const first = openProfile();
    const second = openProfile();
    expect(first.profile.value.nickname).toBe("旧称呼");
    first.save({ nickname: " 新称呼 ", bio: "新简介", avatarDataUrl: "" });
    expect(second.profile.value).toEqual({ nickname: "新称呼", bio: "新简介", avatarDataUrl: "" });
    expect(localStorage.length).toBe(1);
    expect(JSON.parse(localStorage.getItem(LOCAL_PROFILE_KEY)!)).toEqual(second.profile.value);
  });

  it("存储失败时保留已保存的状态和旧内容", () => {
    const state = openProfile();
    state.save({ nickname: "原资料", bio: "", avatarDataUrl: "" });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new DOMException("quota", "QuotaExceededError"); });
    expect(() => state.save({ nickname: "未保存", bio: "", avatarDataUrl: "" })).toThrow();
    expect(state.profile.value.nickname).toBe("原资料");
    expect(JSON.parse(localStorage.getItem(LOCAL_PROFILE_KEY)!).nickname).toBe("原资料");
  });

  it("损坏记录给出可见错误而不改写原始存储", () => {
    localStorage.setItem(LOCAL_PROFILE_KEY, "invalid-json");
    const state = openProfile();
    expect(state.readError.value).toContain("无法读取本机资料");
    expect(state.profile.value.nickname).toBe("");
    expect(localStorage.getItem(LOCAL_PROFILE_KEY)).toBe("invalid-json");
  });

  it("拒绝超长资料和外部头像地址，不写入错误值", () => {
    const state = openProfile();
    expect(() => state.save({ nickname: "长".repeat(51), bio: "", avatarDataUrl: "" })).toThrow("长度");
    expect(() => state.save({ nickname: "", bio: "长".repeat(241), avatarDataUrl: "" })).toThrow("长度");
    expect(() => state.save({ nickname: "", bio: "", avatarDataUrl: "https://example.invalid/avatar.png" })).toThrow("图片");
    expect(localStorage.getItem(LOCAL_PROFILE_KEY)).toBeNull();
  });

  it("处理跨窗口变化并在作用域销毁后移除监听", () => {
    const remove = vi.spyOn(window, "removeEventListener");
    const state = openProfile();
    localStorage.setItem(LOCAL_PROFILE_KEY, JSON.stringify({ nickname: "另一窗口", bio: "", avatarDataUrl: "" }));
    window.dispatchEvent(new StorageEvent("storage", { key: LOCAL_PROFILE_KEY }));
    expect(state.profile.value.nickname).toBe("另一窗口");
    scopes[0].stop();
    expect(remove).toHaveBeenCalledWith("storage", expect.any(Function));
  });
});
