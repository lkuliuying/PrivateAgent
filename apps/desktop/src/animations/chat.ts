import { animate, createTimeline, stagger } from "animejs";
import {
  createAnimationScope,
  type AnimationHandle,
  type AnimationRoot,
} from "./utils";

export function mountChatAnimations(root: AnimationRoot): AnimationHandle {
  return createAnimationScope(root, ({ scope }) => {
    const animated = new WeakSet<HTMLElement>();
    const disclosures = new Map<HTMLDetailsElement, () => void>();
    const streamAnimations = new WeakMap<HTMLElement, ReturnType<typeof animate>>();
    let streamFrame = 0;

    const incrementMotionRevision = (element: HTMLElement, attribute: string) => {
      const current = Number.parseInt(element.getAttribute(attribute) ?? "0", 10);
      element.setAttribute(attribute, String(Number.isFinite(current) ? current + 1 : 1));
    };

    const animateMessage = (message: HTMLElement) => {
      if (animated.has(message)) return;
      animated.add(message);

      const avatar = message.querySelector<HTMLElement>(".avatar");
      const content = message.querySelector<HTMLElement>(".bubble-wrap");
      const toolSections = message.querySelectorAll<HTMLElement>(
        "[data-tool-section]"
      );

      scope.execute(() => {
        const timeline = createTimeline({ defaults: { ease: "out(4)" } });
        timeline.add(message, { opacity: [0, 1], y: [12, 0], duration: 360 });
        if (avatar) {
          timeline.add(avatar, { opacity: [0, 1], scale: [0.86, 1], duration: 300 }, 40);
        }
        if (content) {
          timeline.add(content, { opacity: [0, 1], x: [8, 0], duration: 360 }, 70);
        }
        if (toolSections.length) {
          timeline.add(
            toolSections,
            {
              opacity: [0, 1],
              y: [6, 0],
              delay: stagger(45),
              duration: 280,
            },
            120
          );
        }
      });
    };

    const registerDisclosure = (details: HTMLDetailsElement) => {
      if (disclosures.has(details)) return;
      const onToggle = () => {
        if (!details.open) return;
        const panel = details.querySelector<HTMLElement>("[data-tool-panel]");
        if (!panel) return;
        scope.execute(() =>
          animate(panel, {
            opacity: [0, 1],
            y: [-5, 0],
            duration: 260,
            ease: "out(4)",
          })
        );
        incrementMotionRevision(panel, "data-disclosure-motion-revision");
      };
      details.addEventListener("toggle", onToggle);
      disclosures.set(details, () => details.removeEventListener("toggle", onToggle));
    };

    const sync = () => {
      root
        .querySelectorAll<HTMLElement>("[data-chat-message]")
        .forEach(animateMessage);
      root
        .querySelectorAll<HTMLDetailsElement>("[data-tool-disclosure]")
        .forEach(registerDisclosure);

      disclosures.forEach((cleanup, details) => {
        if (details.isConnected) return;
        cleanup();
        disclosures.delete(details);
      });
    };

    const revealStreamUpdates = (records: MutationRecord[]) => {
      const bubbles = new Set<HTMLElement>();
      records.forEach((record) => {
        if (record.type !== "characterData") return;
        const parent = record.target.parentElement;
        const bubble = parent?.closest<HTMLElement>(".bubble.is-streaming");
        if (bubble) bubbles.add(bubble);
      });
      if (!bubbles.size) return;

      cancelAnimationFrame(streamFrame);
      streamFrame = requestAnimationFrame(() => {
        bubbles.forEach((bubble) => {
          streamAnimations.get(bubble)?.cancel();
          const animation = scope.execute(() =>
            animate(bubble, {
              opacity: [0.94, 1],
              duration: 150,
              ease: "out(2)",
            })
          );
          streamAnimations.set(bubble, animation);
          incrementMotionRevision(bubble, "data-stream-motion-revision");
        });
      });
    };

    sync();
    const observer = new MutationObserver((records) => {
      if (records.some((record) => record.type === "childList")) sync();
      revealStreamUpdates(records);
    });
    observer.observe(root, { childList: true, characterData: true, subtree: true });

    return () => {
      cancelAnimationFrame(streamFrame);
      observer.disconnect();
      disclosures.forEach((cleanup) => cleanup());
      disclosures.clear();
    };
  });
}
