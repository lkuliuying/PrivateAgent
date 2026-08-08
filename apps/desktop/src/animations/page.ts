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
          scale: [0.97, 1],
          duration: 240,
        },
        0
      );
    }

    if (hero) {
      timeline.add(
        hero,
        {
          opacity: [0, 1],
          y: [8, 0],
          duration: 280,
        },
        40
      );
    }

    if (cards.length) {
      cards.forEach((card) => revealedCards.add(card));
      timeline.add(
        cards,
        {
          opacity: [0, 1],
          y: [8, 0],
          scale: [0.99, 1],
          delay: stagger(40),
          duration: 240,
        },
        80
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
          y: [6, 0],
          scale: [0.995, 1],
          delay: stagger(30),
          duration: 200,
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
      let interaction: ReturnType<typeof animate> | null = null;
      const enter = () => {
        card.classList.add("is-motion-hovered");
        interaction?.cancel();
        interaction = scope.execute(() =>
          animate(card, {
            y: -2,
            scale: 1,
            duration: 160,
            ease: "out(4)",
          })
        );
      };
      const leave = () => {
        card.classList.remove("is-motion-hovered");
        interaction?.cancel();
        interaction = scope.execute(() =>
          animate(card, {
            y: 0,
            scale: 1,
            duration: 160,
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
        interaction?.cancel();
        interaction = null;
        card.classList.remove("is-motion-hovered");
        card.removeEventListener("mouseenter", enter);
        card.removeEventListener("mouseleave", leave);
        card.removeEventListener("focusin", enter);
        card.removeEventListener("focusout", focusOut);
        card.style.removeProperty("transform");
        card.style.removeProperty("opacity");
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
