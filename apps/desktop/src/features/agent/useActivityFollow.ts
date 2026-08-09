/**
 * 活动流自动跟随（0.4.0 D3）
 *
 * 规则（docs/releases/v0.4.0/v0.4.0-ui-ux-redesign-plan.md §6.3）：
 * - 新活动到达时不强制抢走滚动位置；
 * - 用户处于底部（阈值内）时自动跟随；
 * - 离开底部后显示「有新活动」入口，点击回到最新。
 *
 * 竞态防护：watch 触发滚动是异步的，恢复执行时必须复查是否仍在底部，
 * 避免在等待期间离开底部的用户被旧回调强行拉回并覆盖 follow 状态。
 */
import { nextTick, ref, watch, type Ref } from "vue";

const NEAR_BOTTOM_PX = 96;

export function useActivityFollow(scrollRef: Ref<HTMLElement | null>, version: Ref<number>) {
  const follow = ref(true);
  const newActivity = ref(false);

  function nearBottom(): boolean {
    const el = scrollRef.value;
    if (!el) return true;
    return el.scrollHeight - el.scrollTop - el.clientHeight <= NEAR_BOTTOM_PX;
  }

  function onScroll() {
    if (!scrollRef.value) return;
    if (nearBottom()) {
      follow.value = true;
      newActivity.value = false;
    } else {
      follow.value = false;
    }
  }

  async function scrollToLatest(force = false) {
    const el = scrollRef.value;
    if (!el) return;
    await nextTick();
    // 自动跟随回调恢复时若用户已离开底部，不再抢占滚动位置
    if (!force && !nearBottom()) return;
    el.scrollTo({
      top: el.scrollHeight,
      behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches
        ? "auto"
        : "smooth",
    });
    follow.value = true;
    newActivity.value = false;
  }

  function scrollToIndex(index: number) {
    const el = scrollRef.value;
    if (!el) return;
    nextTick().then(() => {
      const nodes = el.querySelectorAll<HTMLElement>("[data-activity-idx]");
      const target = nodes[index];
      if (!target) return;
      el.scrollTo({
        top: Math.max(0, target.offsetTop - el.offsetTop - 24),
        behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches
          ? "auto"
          : "smooth",
      });
    });
  }

  watch(
    version,
    async () => {
      if (!follow.value) {
        newActivity.value = true;
        return;
      }
      await scrollToLatest(false);
    },
    { flush: "post" }
  );

  return { follow, newActivity, onScroll, scrollToLatest, scrollToIndex };
}
