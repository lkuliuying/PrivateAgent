/**
 * 轻量导航历史（0.4.0 D2）
 * 内部历史栈：返回 / 前进 / 恢复上次视图；不引入 Vue Router。
 * 历史保存完整 NavigationTarget（view + sessionId + params），
 * 会话级返回/前进可还原定位参数，视图切换不创建重复请求或协调器。
 */
import { ref } from "vue";
import type { View } from "../types";
import { VIEW_REGISTRY, type NavigationTarget } from "../models/viewRegistry";

const LAST_VIEW_KEY = "pa_last_view";

function restoreLastView(): View | null {
  try {
    const stored = window.localStorage.getItem(LAST_VIEW_KEY);
    if (stored && stored in VIEW_REGISTRY) return stored as View;
  } catch {
    /* localStorage 不可用时忽略 */
  }
  return null;
}

export interface ViewHistoryState {
  current: View;
  canGoBack: boolean;
  canGoForward: boolean;
}

export function useViewHistory(defaultView: View) {
  const backStack = ref<NavigationTarget[]>([]);
  const forwardStack = ref<NavigationTarget[]>([]);
  const currentTarget = ref<NavigationTarget>({
    view: restoreLastView() ?? defaultView,
  });
  const current = ref<View>(currentTarget.value.view);

  function persist(view: View) {
    try {
      window.localStorage.setItem(LAST_VIEW_KEY, view);
    } catch {
      /* ignore */
    }
  }

  /** 导航到新目标；同视图重复导航只更新目标参数，不重复入栈。 */
  function navigate(target: NavigationTarget) {
    if (target.view === currentTarget.value.view) {
      // 同视图：更新参数（如会话切换）不入栈
      currentTarget.value = { ...target };
      return;
    }
    backStack.value.push({ ...currentTarget.value });
    if (backStack.value.length > 50) backStack.value.shift();
    forwardStack.value = [];
    currentTarget.value = { ...target };
    current.value = target.view;
    persist(target.view);
  }

  /** 返回上一视图；返回完整目标（含 sessionId/params），调用方负责定位。 */
  function back(): NavigationTarget | null {
    const previous = backStack.value.pop();
    if (!previous) return null;
    forwardStack.value.push({ ...currentTarget.value });
    currentTarget.value = { ...previous };
    current.value = previous.view;
    persist(current.value);
    return { ...previous };
  }

  function forward(): NavigationTarget | null {
    const next = forwardStack.value.pop();
    if (!next) return null;
    backStack.value.push({ ...currentTarget.value });
    currentTarget.value = { ...next };
    current.value = next.view;
    persist(current.value);
    return { ...next };
  }

  /** 当前目标（含定位参数），供视图消费。 */
  function target(): NavigationTarget {
    return { ...currentTarget.value };
  }

  function state(): ViewHistoryState {
    return {
      current: current.value,
      canGoBack: backStack.value.length > 0,
      canGoForward: forwardStack.value.length > 0,
    };
  }

  return { current, currentTarget, navigate, back, forward, target, state };
}
