import { describe, expect, it } from "vitest";
import { contrast, createPalette, extractPalette, mix, themeVariables } from "./palette";

describe("壁纸配色", () => {
  it.each([
    [[240, 230, 220, 255], "light", false], [[15, 20, 40, 255], "dark", false],
    [[128, 128, 128, 255], "dark", true], [[0, 0, 0, 0], "light", true],
    [[255, 255, 255, 255], "light", true], [[255, 0, 0, 255], "dark", false],
  ] as const)("稳定识别 %j 的明暗和灰度", (pixel, mode, neutral) => {
    const data = new Uint8ClampedArray([...pixel, ...pixel]);
    const palette = extractPalette(data);
    expect(palette.mode).toBe(mode);
    expect(palette.neutral).toBe(neutral);
    expect(extractPalette(data)).toEqual(palette);
  });

  it("按颜色分布选主色，透明像素不污染取色", () => {
    const data = new Uint8ClampedArray([220, 40, 60, 255, 220, 40, 60, 255, 0, 255, 0, 0]);
    expect(extractPalette(data).seed).toBe("#dc283c");
    expect(() => extractPalette(new Uint8ClampedArray())).toThrow("像素");
  });

  it("各色调在所有普通表面和壁纸明暗极值上保持文字及按钮对比度", () => {
    for (const r of [0, 85, 170, 255]) for (const g of [0, 85, 170, 255]) for (const b of [0, 85, 170, 255]) {
      const seed = `#${[r, g, b].map(v => v.toString(16).padStart(2, "0")).join("")}`;
      for (const mode of ["light", "dark"] as const) {
        const palette = createPalette(seed, mode, r === g && g === b);
        const c = palette.colors;
        const backgrounds = [c.surface, c.background, c.sunken, c.muted, c.hover, c.accentSoft,
          mix(c.surface, "#000000", palette.opacity), mix(c.surface, "#ffffff", palette.opacity)];
        for (const foreground of [c.text, c.secondary, c.accent]) for (const background of backgrounds) {
          expect(contrast(foreground, background), `${seed} ${mode} ${foreground}/${background}`).toBeGreaterThanOrEqual(4.5);
        }
        for (const background of [c.accent, c.accentHover, c.accentActive]) {
          expect(contrast(c.accentText, background)).toBeGreaterThanOrEqual(4.5);
        }
      }
    }
  });

  it("仅输出颜色变量，不改变布局或语义状态色", () => {
    const vars = themeVariables(createPalette("#808080", "light", true));
    expect(Object.keys(vars).some(key => /space|radius|font|height|width|success|warning|danger/.test(key))).toBe(false);
    expect(vars["--color-accent"]).toBe(createPalette("#ff0000", "light", true).colors.accent);
  });

  it("深色状态和代码差异仍保留独立语义色，普通与状态文字均可读", () => {
    for (const seed of ["#ff0000", "#ffff00", "#00ff00", "#0000ff", "#ffffff", "#000000"]) {
      const palette = createPalette(seed, "dark", false);
      const vars = themeVariables(palette);
      const colors = ["success", "warning", "danger", "info"].map(name => vars[`--color-${name}-fg`]);
      expect(new Set(colors).size).toBe(4);
      for (const name of ["success", "warning", "danger", "info"]) {
        const background = vars[`--color-${name}-soft`];
        for (const text of [vars[`--color-${name}-fg`], palette.colors.text, palette.colors.secondary]) {
          expect(contrast(text, background)).toBeGreaterThanOrEqual(4.5);
        }
      }
    }
  });
});
