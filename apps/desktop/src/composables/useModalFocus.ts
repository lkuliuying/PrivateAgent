import {
  nextTick,
  onBeforeUnmount,
  onMounted,
  type Ref,
  watch,
} from "vue";

const FOCUSABLE_SELECTOR = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "[tabindex]:not([tabindex='-1'])",
].join(",");

let backgroundLockCount = 0;
let appPreviousInert = false;
let appPreviousAriaHidden: string | null = null;
let rootReturnFocus: HTMLElement | null = null;
let sessionGeneration = 0;

interface ActiveModal {
  id: symbol;
  container: Ref<HTMLElement | null>;
  layer?: Ref<HTMLElement | null>;
  initialFocus?: Ref<HTMLElement | null>;
  onEscape?: () => void;
  returnFocus: HTMLElement | null;
  accessibilityElement: HTMLElement | null;
  previousInert: boolean;
  previousAriaHidden: string | null;
  suppressed: boolean;
  layerElement: HTMLElement | null;
  previousLayerZIndex: string;
  previousLayerZIndexPriority: string;
}

const modalStack: ActiveModal[] = [];

function lockBackground(): void {
  const app = document.getElementById("app");
  if (backgroundLockCount === 0 && app) {
    appPreviousInert = app.inert === true;
    appPreviousAriaHidden = app.getAttribute("aria-hidden");
    app.inert = true;
    app.setAttribute("aria-hidden", "true");
  }
  backgroundLockCount += 1;
}

function unlockBackground(): void {
  if (backgroundLockCount === 0) return;
  backgroundLockCount -= 1;
  if (backgroundLockCount > 0) return;

  const app = document.getElementById("app");
  if (!app) return;
  app.inert = appPreviousInert;
  if (appPreviousAriaHidden === null) app.removeAttribute("aria-hidden");
  else app.setAttribute("aria-hidden", appPreviousAriaHidden);
}

function focusableElements(container: HTMLElement): HTMLElement[] {
  return Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)).filter(
    (element) =>
      !element.hasAttribute("disabled") &&
      element.getAttribute("aria-hidden") !== "true" &&
      element.tabIndex >= 0
  );
}

export interface ModalFocusOptions {
  container: Ref<HTMLElement | null>;
  /** Optional Teleport layer root. By default the direct child of body is used. */
  layer?: Ref<HTMLElement | null>;
  initialFocus?: Ref<HTMLElement | null>;
  active?: Ref<boolean>;
  onEscape?: () => void;
}

function topModal(): ActiveModal | undefined {
  return modalStack[modalStack.length - 1];
}

function restoreModalAccessibility(modal: ActiveModal): void {
  const element = modal.accessibilityElement;
  if (element && modal.suppressed) {
    element.inert = modal.previousInert;
    if (modal.previousAriaHidden === null) element.removeAttribute("aria-hidden");
    else element.setAttribute("aria-hidden", modal.previousAriaHidden);
  }
  modal.accessibilityElement = null;
  modal.suppressed = false;
}

function setModalSuppressed(modal: ActiveModal, suppressed: boolean): void {
  const element = modal.container.value;
  if (modal.accessibilityElement && modal.accessibilityElement !== element) {
    restoreModalAccessibility(modal);
  }
  if (!element) return;

  if (suppressed && !modal.suppressed) {
    modal.accessibilityElement = element;
    modal.previousInert = element.inert === true;
    modal.previousAriaHidden = element.getAttribute("aria-hidden");
    element.inert = true;
    element.setAttribute("aria-hidden", "true");
    modal.suppressed = true;
  } else if (!suppressed) {
    restoreModalAccessibility(modal);
  }
}

function syncModalAccessibility(): void {
  const topIndex = modalStack.length - 1;
  modalStack.forEach((modal, index) => setModalSuppressed(modal, index !== topIndex));
}

function inferredModalLayer(container: HTMLElement | null): HTMLElement | null {
  if (!container) return null;
  let element = container;
  while (element.parentElement && element.parentElement !== document.body) {
    element = element.parentElement;
  }
  return element.parentElement === document.body ? element : container;
}

function restoreModalLayer(modal: ActiveModal): void {
  const element = modal.layerElement;
  if (!element) return;
  if (modal.previousLayerZIndex) {
    element.style.setProperty(
      "z-index",
      modal.previousLayerZIndex,
      modal.previousLayerZIndexPriority
    );
  } else {
    element.style.removeProperty("z-index");
  }
  modal.layerElement = null;
  modal.previousLayerZIndex = "";
  modal.previousLayerZIndexPriority = "";
}

function setModalLayerDepth(modal: ActiveModal, depth: number): void {
  const element = modal.layer?.value ?? inferredModalLayer(modal.container.value);
  if (modal.layerElement && modal.layerElement !== element) {
    restoreModalLayer(modal);
  }
  if (!element) return;
  if (!modal.layerElement) {
    modal.layerElement = element;
    modal.previousLayerZIndex = element.style.getPropertyValue("z-index");
    modal.previousLayerZIndexPriority = element.style.getPropertyPriority("z-index");
  }
  // Teleport preserves source anchors, so DOM order does not necessarily match
  // activation order. Make the modal stack authoritative while keeping the token base.
  element.style.setProperty("z-index", `calc(var(--z-overlay) + ${depth})`);
}

function syncModalLayers(): void {
  modalStack.forEach((modal, depth) => setModalLayerDepth(modal, depth));
}

function currentFocus(): HTMLElement | null {
  return document.activeElement instanceof HTMLElement ? document.activeElement : null;
}

function focusModal(modal: ActiveModal): void {
  const container = modal.container.value;
  const target =
    modal.initialFocus?.value ??
    (container ? focusableElements(container)[0] : undefined) ??
    container;
  target?.focus();
}

function finishModalSession(generation: number): void {
  if (generation !== sessionGeneration || modalStack.length > 0) return;
  unlockBackground();
  const target = rootReturnFocus;
  rootReturnFocus = null;
  if (target?.isConnected) target.focus();
}

function handleModalKeydown(event: KeyboardEvent): void {
  const modal = topModal();
  if (!modal) return;

  if (event.key === "Escape" && modal.onEscape) {
    event.preventDefault();
    event.stopImmediatePropagation();
    modal.onEscape();
    return;
  }
  if (event.key !== "Tab") return;

  const container = modal.container.value;
  if (!container) return;
  const focusable = focusableElements(container);
  if (focusable.length === 0) {
    event.preventDefault();
    event.stopImmediatePropagation();
    container.focus();
    return;
  }

  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  const current = document.activeElement;
  if (event.shiftKey && (current === first || !container.contains(current))) {
    event.preventDefault();
    event.stopImmediatePropagation();
    last.focus();
  } else if (!event.shiftKey && (current === last || !container.contains(current))) {
    event.preventDefault();
    event.stopImmediatePropagation();
    first.focus();
  }
}

export function hasActiveModalFocus(): boolean {
  return modalStack.length > 0;
}

/**
 * 统一管理 Teleport 浮层的焦点边界：锁定背景、循环 Tab、Esc 关闭并恢复触发点。
 * 每个实例只管理自己的生命周期；计数锁允许确认框等浮层安全地短暂嵌套。
 */
export function useModalFocus(options: ModalFocusOptions): void {
  let active = false;
  let stopActiveWatch: (() => void) | undefined;
  const modal: ActiveModal = {
    id: Symbol("modal-focus"),
    container: options.container,
    layer: options.layer,
    initialFocus: options.initialFocus,
    onEscape: options.onEscape,
    returnFocus: null,
    accessibilityElement: null,
    previousInert: false,
    previousAriaHidden: null,
    suppressed: false,
    layerElement: null,
    previousLayerZIndex: "",
    previousLayerZIndexPriority: "",
  };

  const activate = async (): Promise<void> => {
    if (active) return;
    active = true;
    modal.returnFocus = currentFocus();
    sessionGeneration += 1;
    if (backgroundLockCount === 0) {
      rootReturnFocus = modal.returnFocus;
      lockBackground();
    }
    modalStack.push(modal);
    if (modalStack.length === 1) {
      window.addEventListener("keydown", handleModalKeydown, true);
    }
    await nextTick();
    syncModalAccessibility();
    syncModalLayers();
    if (!active || topModal()?.id !== modal.id) return;
    focusModal(modal);
  };

  const deactivate = (): void => {
    if (!active) return;
    active = false;
    const index = modalStack.findIndex((entry) => entry.id === modal.id);
    const wasTop = index === modalStack.length - 1;
    if (index >= 0) modalStack.splice(index, 1);
    restoreModalAccessibility(modal);
    restoreModalLayer(modal);
    syncModalAccessibility();
    syncModalLayers();
    if (modalStack.length === 0) {
      window.removeEventListener("keydown", handleModalKeydown, true);
    }
    if (modalStack.length === 0) {
      const generation = ++sessionGeneration;
      void nextTick(() => finishModalSession(generation));
      return;
    }
    if (wasTop) {
      const nextTop = topModal();
      const target = modal.returnFocus;
      void nextTick(() => {
        if (!nextTop || topModal()?.id !== nextTop.id) return;
        if (target?.isConnected && nextTop.container.value?.contains(target)) {
          target.focus();
        } else {
          focusModal(nextTop);
        }
      });
    }
  };

  onMounted(() => {
    if (options.active) {
      stopActiveWatch = watch(
        options.active,
        (isOpen) => {
          if (isOpen) void activate();
          else deactivate();
        },
        { immediate: true, flush: "post" }
      );
    } else {
      void activate();
    }
  });

  onBeforeUnmount(() => {
    stopActiveWatch?.();
    deactivate();
  });
}
