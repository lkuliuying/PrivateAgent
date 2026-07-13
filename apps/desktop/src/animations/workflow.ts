import { animate, createTimeline, stagger, svg } from "animejs";
import {
  createAnimationScope,
  type AnimationHandle,
  type AnimationRoot,
} from "./utils";

type WorkflowVisualState = "idle" | "active" | "complete" | "failed";

export function workflowVisualState(value?: string | null): WorkflowVisualState {
  if (value === "succeeded") return "complete";
  if (value === "failed" || value === "cancelled") return "failed";
  if (
    value === "running" ||
    value === "approved" ||
    value === "waiting_approval" ||
    value === "plan_approved"
  ) {
    return "active";
  }
  return "idle";
}

function buildWorkflowScope(root: AnimationRoot): AnimationHandle {
  return createAnimationScope(root, () => {
    const steps = Array.from(
      root.querySelectorAll<HTMLElement>("[data-workflow-step]")
    );

    steps.forEach((step, index) => {
      const state = workflowVisualState(step.dataset.workflowState);
      const node = step.querySelector<HTMLElement>("[data-workflow-node]");
      const path = step.querySelector<SVGPathElement>("[data-workflow-path]");
      const particle = step.querySelector<SVGCircleElement>("[data-workflow-particle]");
      const checkPath = step.querySelector<SVGPathElement>("[data-workflow-check-path]");

      if (path && (state === "active" || state === "complete")) {
        animate(svg.createDrawable(path), {
          draw: ["0 0", "0 1"],
          duration: 520,
          delay: index * 70,
          ease: "out(3)",
        });
      }

      if (path && particle && state === "active") {
        animate(particle, {
          ...svg.createMotionPath(path),
          opacity: [0, 1, 0],
          duration: 1180,
          ease: "linear",
          loop: true,
        });
      }

      if (node && state === "active") {
        animate(node, {
          scale: [1, 1.12],
          opacity: [0.82, 1],
          duration: 760,
          ease: "inOut(2)",
          loop: true,
          alternate: true,
        });
      }

      if (node && checkPath && state === "complete") {
        createTimeline({ defaults: { ease: "out(4)" } })
          .add(node, { scale: [0.82, 1.08, 1], duration: 440 })
          .add(
            svg.createDrawable(checkPath),
            { draw: ["0 0", "0 1"], duration: 360 },
            100
          );
      }
    });

    const brain = root.querySelector<HTMLElement>("[data-agent-brain]");
    if (brain) {
      const rings = brain.querySelectorAll<HTMLElement>("[data-brain-ring]");
      animate(brain, {
        scale: [1, 1.045],
        duration: 1700,
        ease: "inOut(2)",
        loop: true,
        alternate: true,
      });
      if (rings.length) {
        animate(rings, {
          scale: [0.75, 1.45],
          opacity: [0.32, 0],
          delay: stagger(480),
          duration: 1900,
          ease: "out(3)",
          loop: true,
        });
      }
    }
  });
}

export function mountWorkflowAnimations(root: AnimationRoot): AnimationHandle {
  let active = buildWorkflowScope(root);
  let frame = 0;

  const refresh = () => {
    cancelAnimationFrame(frame);
    frame = requestAnimationFrame(() => {
      active.destroy();
      active = buildWorkflowScope(root);
    });
  };

  const observer = new MutationObserver(refresh);
  observer.observe(root, {
    attributes: true,
    attributeFilter: ["data-workflow-state"],
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
      cancelAnimationFrame(frame);
      observer.disconnect();
      active.destroy();
    },
  };
}
