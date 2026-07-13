import { animate, createTimeline, stagger } from "animejs";
import {
  createAnimationScope,
  createCompositeHandle,
  observeElements,
  type AnimationHandle,
  type AnimationRoot,
} from "./utils";

function mountEntranceTimeline(root: AnimationRoot): AnimationHandle {
  return createAnimationScope(root, ({ scope }) => {
    const logo = root.querySelector<HTMLElement>("[data-motion-logo]");
    const hero = root.querySelector<HTMLElement>("[data-motion-hero]");
    const cards = root.querySelectorAll<HTMLElement>("[data-agent-card]");
    const revealedCards = new WeakSet<HTMLElement>();

    const timeline = createTimeline({
      defaults: { ease: "out(4)" },
    });

    if (logo) {
      timeline.add(
        logo,
        {
          opacity: [0, 1],
          scale: [0.94, 1],
          duration: 420,
        },
        0
      );
    }

    if (hero) {
      timeline.add(
        hero,
        {
          opacity: [0, 1],
          y: [20, 0],
          duration: 560,
        },
        80
      );
    }

    if (cards.length) {
      cards.forEach((card) => revealedCards.add(card));
      timeline.add(
        cards,
        {
          opacity: [0, 1],
          y: [16, 0],
          scale: [0.985, 1],
          delay: stagger(55),
          duration: 480,
        },
        160
      );
    }

    const revealNewCards = () => {
      const added = Array.from(
        root.querySelectorAll<HTMLElement>("[data-agent-card]")
      ).filter((card) => !revealedCards.has(card));
      if (!added.length) return;
      added.forEach((card) => revealedCards.add(card));
      scope.execute(() =>
        createTimeline({ defaults: { ease: "out(4)" } }).add(added, {
          opacity: [0, 1],
          y: [12, 0],
          scale: [0.99, 1],
          delay: stagger(45),
          duration: 420,
        })
      );
    };

    const observer = new MutationObserver(revealNewCards);
    observer.observe(root, { childList: true, subtree: true });
    return () => observer.disconnect();
  });
}

function mountCardInteractions(root: AnimationRoot): AnimationHandle {
  return createAnimationScope(root, ({ scope }) => {
    return observeElements(root, "[data-agent-card]", (card) => {
      const enter = () => {
        card.classList.add("is-motion-hovered");
        scope.execute(() =>
          animate(card, {
            y: -6,
            scale: 1.02,
            duration: 260,
            ease: "out(4)",
          })
        );
      };
      const leave = () => {
        card.classList.remove("is-motion-hovered");
        scope.execute(() =>
          animate(card, {
            y: 0,
            scale: 1,
            duration: 360,
            ease: "out(4)",
          })
        );
      };
      const focusOut = (event: FocusEvent) => {
        if (event.relatedTarget instanceof Node && card.contains(event.relatedTarget)) {
          return;
        }
        leave();
      };

      card.addEventListener("mouseenter", enter);
      card.addEventListener("mouseleave", leave);
      card.addEventListener("focusin", enter);
      card.addEventListener("focusout", focusOut);

      return () => {
        card.classList.remove("is-motion-hovered");
        card.removeEventListener("mouseenter", enter);
        card.removeEventListener("mouseleave", leave);
        card.removeEventListener("focusin", enter);
        card.removeEventListener("focusout", focusOut);
      };
    });
  });
}

export function mountPageAnimations(root: AnimationRoot): AnimationHandle {
  return createCompositeHandle([
    mountEntranceTimeline(root),
    mountCardInteractions(root),
  ]);
}
