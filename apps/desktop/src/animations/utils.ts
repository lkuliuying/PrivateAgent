import { createScope, type Scope } from "animejs";

export type AnimationRoot = HTMLElement | SVGElement;

export interface AnimationHandle {
  readonly destroyed: boolean;
  destroy: () => void;
}

export interface ScopedAnimationContext {
  root: AnimationRoot;
  scope: Scope;
}

export const motionMediaQueries = {
  reduceMotion: "(prefers-reduced-motion: reduce)",
} as const;

export function markMotionRevision(element: HTMLElement, motion: string): number {
  const attribute = `data-${motion}-motion-revision`;
  const current = Number.parseInt(element.getAttribute(attribute) ?? "0", 10);
  const next = Number.isSafeInteger(current) && current >= 0 ? current + 1 : 1;
  element.setAttribute(attribute, String(next));
  return next;
}

export function queryAll<T extends Element>(
  root: ParentNode,
  selector: string
): T[] {
  return Array.from(root.querySelectorAll<T>(selector));
}

export function createAnimationScope(
  root: AnimationRoot,
  setup: (context: ScopedAnimationContext) => void | (() => void)
): AnimationHandle {
  const scope = createScope({
    root,
    mediaQueries: motionMediaQueries,
  });

  scope.add((activeScope) => {
    if (activeScope?.matches.reduceMotion) return;
    return setup({ root, scope: activeScope ?? scope });
  });

  let destroyed = false;
  return {
    get destroyed() {
      return destroyed;
    },
    destroy() {
      if (destroyed) return;
      destroyed = true;
      scope.revert();
    },
  };
}
export function createCompositeHandle(handles: AnimationHandle[]): AnimationHandle {
  let destroyed = false;
  return {
    get destroyed() {
      return destroyed;
    },
    destroy() {
      if (destroyed) return;
      destroyed = true;
      handles.forEach((handle) => handle.destroy());
    },
  };
}

export function observeElements(
  root: AnimationRoot,
  selector: string,
  onAdd: (element: HTMLElement) => (() => void) | void
): () => void {
  const cleanups = new Map<HTMLElement, () => void>();

  const sync = () => {
    const current = new Set(queryAll<HTMLElement>(root, selector));

    current.forEach((element) => {
      if (cleanups.has(element)) return;
      cleanups.set(element, onAdd(element) ?? (() => undefined));
    });

    cleanups.forEach((cleanup, element) => {
      if (current.has(element) && element.isConnected) return;
      cleanup();
      cleanups.delete(element);
    });
  };

  sync();
  const observer = new MutationObserver(sync);
  observer.observe(root, { childList: true, subtree: true });

  return () => {
    observer.disconnect();
    cleanups.forEach((cleanup) => cleanup());
    cleanups.clear();
  };
}
