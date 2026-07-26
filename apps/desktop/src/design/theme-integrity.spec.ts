import { describe, expect, it } from "vitest";
// Vitest executes this contract in Node; the application tsconfig intentionally omits Node globals.
// @ts-expect-error -- node:fs is available to Vitest even though @types/node is not an app dependency.
import { readFileSync } from "node:fs";
import configWizardSource from "../components/ConfigWizard.vue?raw";
import sessionListSource from "../components/SessionList.vue?raw";
import settingsViewSource from "../components/SettingsView.vue?raw";
import statusBarSource from "../components/StatusBar.vue?raw";
import statusViewSource from "../components/StatusView.vue?raw";
import updateCheckerSource from "../components/UpdateChecker.vue?raw";

const tokensSource = readFileSync("src/design/tokens.css", "utf8");
const componentsSource = readFileSync("src/design/components.css", "utf8");
const allComponentSources = import.meta.glob<string>("../components/**/*.vue", {
  eager: true,
  query: "?raw",
  import: "default",
});

const themedComponents = {
  ConfigWizard: configWizardSource,
  SessionList: sessionListSource,
  SettingsView: settingsViewSource,
  StatusBar: statusBarSource,
  StatusView: statusViewSource,
  UpdateChecker: updateCheckerSource,
};

const rawColorPattern =
  /(?:#[\da-f]{3,8}\b|(?:rgb|hsl)a?\s*\(|(?:^|[\s:,])(?:white|black)(?=\s*[;,)\}]))/im;

function scopedStyles(source: string): string {
  return source.match(/<style scoped>([\s\S]*?)<\/style>/)?.[1] ?? "";
}

describe("theme token integrity", () => {
  it.each(Object.entries(allComponentSources))(
    "%s keeps visual color declarations theme-aware",
    (_path, source) => {
      const styles = scopedStyles(source).replace(/mask-image\s*:[^;]+;/gi, "");

      expect(styles).not.toMatch(rawColorPattern);
    },
  );

  it("keeps shared component styles free of raw visual colors", () => {
    expect(componentsSource).not.toMatch(rawColorPattern);
  });

  it.each(Object.entries(themedComponents))(
    "%s does not bind its scoped styles to light-theme color literals",
    (_name, source) => {
      const styles = scopedStyles(source);

      expect(styles).not.toBe("");
      expect(styles).not.toMatch(rawColorPattern);
    },
  );

  it("declares every color token referenced by the themed components", () => {
    const declarations = new Set(
      Array.from(tokensSource.matchAll(/--(color-[\w-]+)\s*:/g), ([, token]) => token),
    );

    for (const [name, source] of Object.entries(themedComponents)) {
      const references = Array.from(
        scopedStyles(source).matchAll(/var\(--(color-[\w-]+)/g),
        ([, token]) => token,
      );

      expect(references.filter((token) => !declarations.has(token)), name).toEqual([]);
    }
  });

  it("maps status semantics for dark, high-contrast, and forced-color modes", () => {
    expect(tokensSource).toMatch(
      /\[data-theme="dark"\][\s\S]*--color-success-border:[\s\S]*--color-danger-border:/,
    );
    expect(tokensSource).toMatch(
      /\[data-contrast="more"\][\s\S]*--color-success-border:[\s\S]*--color-danger-border:/,
    );
    expect(tokensSource).toMatch(
      /@media \(forced-colors: active\)[\s\S]*--color-success-on-solid: HighlightText;[\s\S]*--color-danger-border: Highlight;/,
    );
  });
});
