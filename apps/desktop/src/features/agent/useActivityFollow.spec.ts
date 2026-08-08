import { describe, expect, it, vi } from "vitest";
import { flushPromises } from "@vue/test-utils";
import { nextTick, ref } from "vue";
import { useActivityFollow } from "./useActivityFollow";

/** scrollTop 越远离底部（remaining = scrollHeight - scrollTop - clientHeight） */
function makeScroller(scrollTop: number) {
  const el = {
    scrollHeight: 2000,
    scrollTop,
    clientHeight: 600,
    scrollTo: vi.fn(),
  } as unknown as HTMLElement;
  return el;
}

async function settle() {
  await flushPromises();
  await nextTick();
  await flushPromises();
}

describe("useActivityFollow", () => {
  it("内容更新且位于底部时自动滚动到最新", async () => {
    const scrollRef = ref<HTMLElement | null>(makeScroller(1400));
    const version = ref(0);
    const follow = useActivityFollow(scrollRef, version);
    await settle();
    version.value += 1;
    await settle();
    expect(scrollRef.value!.scrollTo).toHaveBeenCalled();
    expect(follow.newActivity.value).toBe(false);
  });

  it("用户离开底部后不强制滚动，并提示「有新活动」", async () => {
    const scrollRef = ref<HTMLElement | null>(makeScroller(200));
    const version = ref(0);
    const follow = useActivityFollow(scrollRef, version);
    follow.onScroll();
    expect(follow.follow.value).toBe(false);
    version.value += 1;
    await settle();
    expect(scrollRef.value!.scrollTo).not.toHaveBeenCalled();
    expect(follow.newActivity.value).toBe(true);
  });

  it("回到底部后恢复跟随并清除提示", () => {
    const scrollRef = ref<HTMLElement | null>(makeScroller(200));
    const version = ref(0);
    const follow = useActivityFollow(scrollRef, version);
    follow.onScroll();
    expect(follow.follow.value).toBe(false);
    scrollRef.value!.scrollTop = 1400;
    follow.onScroll();
    expect(follow.follow.value).toBe(true);
    expect(follow.newActivity.value).toBe(false);
  });

  it("scrollToIndex 定位到目标活动", async () => {
    const el = makeScroller(0);
    const target = document.createElement("div");
    Object.defineProperty(target, "offsetTop", { value: 500 });
    el.querySelectorAll = vi.fn(() => [null, null, target] as never);
    const scrollRef = ref<HTMLElement | null>(el);
    const version = ref(0);
    const follow = useActivityFollow(scrollRef, version);
    follow.scrollToIndex(2);
    await settle();
    expect(el.scrollTo).toHaveBeenCalled();
  });
});
