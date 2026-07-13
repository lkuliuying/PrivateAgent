import { animate, stagger } from "animejs";
import {
  createAnimationScope,
  type AnimationHandle,
  type AnimationRoot,
} from "./utils";

export type AgentMotionState = "idle" | "thinking" | "executing";

export function normalizeAgentMotionState(value?: string | null): AgentMotionState {
  if (value === "thinking" || value === "executing") return value;
  return "idle";
}

function mountAgentElement(element: HTMLElement): AnimationHandle {
  return createAnimationScope(element, () => {
    const state = normalizeAgentMotionState(element.dataset.agentState);
    const core = element.querySelector<HTMLElement>("[data-agent-core]") ?? element;
    const halos = element.querySelectorAll<HTMLElement>("[data-agent-halo]");
    const flowDots = element.querySelectorAll<HTMLElement>("[data-agent-flow-dot]");

    if (state === "idle") {
      animate(core, {
        scale: [1, 1.025],
        opacity: [0.9, 1],
        duration: 2600,
        ease: "inOut(2)",
        loop: true,
        alternate: true,
      });
      return;
    }

    if (state === "thinking") {
      animate(core, {
        scale: [1, 1.06],
        duration: 920,
        ease: "inOut(3)",
        loop: true,
        alternate: true,
      });
      if (halos.length) {
        animate(halos, {
          scale: [0.72, 1.65],
          opacity: [0.48, 0],
          delay: stagger(420),
          duration: 1680,
          ease: "out(3)",
          loop: true,
        });
      }
      return;
    }

    animate(core, {
      scale: [1, 1.045],
      duration: 620,
      ease: "inOut(2)",
      loop: true,
      alternate: true,
    });
    if (flowDots.length) {
      animate(flowDots, {
        x: [-8, 12],
        opacity: [0, 1, 0],
        scale: [0.7, 1, 0.7],
        delay: stagger(170),
        duration: 980,
        ease: "linear",
        loop: true,
      });
    }
  });
}

export function mountAgentAnimations(root: AnimationRoot): AnimationHandle {
  const mounted = new Map<HTMLElement, { state: string; handle: AnimationHandle }>();

  const sync = () => {
    const current = new Set(
      Array.from(root.querySelectorAll<HTMLElement>("[data-agent-state]"))
    );

    current.forEach((element) => {
      const state = normalizeAgentMotionState(element.dataset.agentState);
      const existing = mounted.get(element);
      if (existing?.state === state) return;
      existing?.handle.destroy();
      mounted.set(element, { state, handle: mountAgentElement(element) });
    });

    mounted.forEach((entry, element) => {
      if (current.has(element) && element.isConnected) return;
      entry.handle.destroy();
      mounted.delete(element);
    });
  };

  sync();
  const observer = new MutationObserver(sync);
  observer.observe(root, {
    attributes: true,
    attributeFilter: ["data-agent-state"],
    childList: true,
    subtree: true,
  });

  let destroyed = false;
  return {
    get destroyed() {
      return destroyed;
    },
    destroy() {
      if (destroyed) return;
      destroyed = true;
      observer.disconnect();
      mounted.forEach((entry) => entry.handle.destroy());
      mounted.clear();
    },
  };
}
