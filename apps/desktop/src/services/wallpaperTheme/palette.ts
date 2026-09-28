export type ThemeMode = "light" | "dark";
type RGB = [number, number, number];

export interface WallpaperPalette {
  mode: ThemeMode;
  seed: string;
  neutral: boolean;
  opacity: number;
  colors: {
    background: string; surface: string; sunken: string; muted: string; hover: string;
    text: string; secondary: string; border: string; borderStrong: string;
    accent: string; accentHover: string; accentActive: string; accentText: string; accentSoft: string;
  };
}

const rgb = (hex: string): RGB => [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16)) as RGB;
const hex = (value: RGB) => `#${value.map(v => Math.round(v).toString(16).padStart(2, "0")).join("")}`;
export const mix = (foreground: string, background: string, opacity: number): string =>
  hex(rgb(foreground).map((v, i) => v * opacity + rgb(background)[i] * (1 - opacity)) as RGB);

function luminance(color: string): number {
  const linear = rgb(color).map(v => v / 255).map(v => v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4);
  return linear[0] * 0.2126 + linear[1] * 0.7152 + linear[2] * 0.0722;
}

export function contrast(a: string, b: string): number {
  const x = luminance(a), y = luminance(b);
  return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
}

function readable(color: string, backgrounds: string[], dark: boolean): string {
  const target = dark ? "#ffffff" : "#000000";
  for (let step = 0; step <= 100; step++) {
    const adjusted = mix(target, color, step / 100);
    if (backgrounds.every(bg => contrast(adjusted, bg) >= 4.6)) return adjusted;
  }
  return target;
}

export function createPalette(seed: string, mode: ThemeMode, neutral: boolean): WallpaperPalette {
  const dark = mode === "dark";
  const tint = neutral ? "#808080" : seed;
  const base = dark ? "#000000" : "#ffffff";
  const surface = mix(tint, base, dark ? 0.18 : 0.035);
  const background = mix(tint, base, dark ? 0.12 : 0.07);
  const sunken = mix(tint, base, dark ? 0.14 : 0.1);
  const muted = mix(tint, base, dark ? 0.23 : 0.06);
  const hover = mix(tint, base, dark ? 0.32 : 0.14);
  const accentSoft = mix(neutral ? "#06777e" : seed, base, dark ? 0.3 : 0.14);
  const text = dark ? "#f5f5f5" : "#161616";
  // 黑、白极值覆盖任意壁纸像素；缩略采样漏掉的亮点也不能降低文字对比度。
  let opacity = 0.88;
  while (opacity < 1 && ["#000000", "#ffffff"].some(bg => contrast(text, mix(surface, bg, opacity)) < 4.6)) {
    opacity = Math.min(1, Math.round((opacity + 0.01) * 100) / 100);
  }
  const backgrounds = [surface, background, sunken, muted, hover, accentSoft,
    mix(surface, "#000000", opacity), mix(surface, "#ffffff", opacity)];
  const secondary = readable(dark ? "#acacac" : "#636363", backgrounds, dark);
  const accent = readable(neutral ? (dark ? "#5fe0e5" : "#06777e") : seed, backgrounds, dark);
  const accentHover = mix(dark ? "#ffffff" : "#000000", accent, 0.1);
  const accentActive = mix(dark ? "#ffffff" : "#000000", accent, 0.2);
  const accentText = dark ? "#000000" : "#ffffff";
  return {
    seed, mode, neutral, opacity,
    colors: {
      background, surface, sunken, muted, hover, text, secondary,
      border: mix(text, surface, 0.18), borderStrong: mix(text, surface, 0.32),
      accent, accentHover, accentActive, accentText, accentSoft,
    },
  };
}

export function extractPalette(pixels: Uint8ClampedArray): WallpaperPalette {
  if (!pixels.length || pixels.length % 4 !== 0) throw new Error("图片没有可用的像素。");
  const bins = new Map<number, { weight: number; sum: RGB }>();
  let brightness = 0, chromaWeight = 0, totalWeight = 0;
  for (let i = 0; i < pixels.length; i += 4) {
    const color: RGB = [pixels[i], pixels[i + 1], pixels[i + 2]];
    const alpha = pixels[i + 3] / 255;
    brightness += luminance(mix(hex(color), "#ffffff", alpha));
    const chroma = (Math.max(...color) - Math.min(...color)) / 255;
    totalWeight += alpha;
    chromaWeight += chroma * alpha;
    if (alpha < 0.05 || chroma < 0.03) continue;
    const key = (color[0] >> 5) * 64 + (color[1] >> 5) * 8 + (color[2] >> 5);
    const weight = alpha * (0.25 + chroma);
    const bin = bins.get(key) ?? { weight: 0, sum: [0, 0, 0] as RGB };
    bin.weight += weight;
    color.forEach((value, channel) => bin.sum[channel] += value * weight);
    bins.set(key, bin);
  }
  const neutral = totalWeight === 0 || chromaWeight / totalWeight < 0.06 || bins.size === 0;
  const dominant = [...bins.entries()].sort((a, b) => b[1].weight - a[1].weight || a[0] - b[0])[0]?.[1];
  const seed = neutral || !dominant ? "#808080" : hex(dominant.sum.map(v => v / dominant.weight) as RGB);
  return createPalette(seed, brightness / (pixels.length / 4) < 0.25 ? "dark" : "light", neutral);
}

export function themeVariables(palette: WallpaperPalette): Record<string, string> {
  const c = palette.colors;
  const panel = `rgba(${rgb(c.surface).join(", ")}, ${palette.opacity})`;
  const semantic: Record<string, string> = {};
  if (palette.mode === "dark") {
    // 保留绿、橙、红、蓝的状态语义，深色下仅调整亮度及底色，避免差异和错误文字不可读。
    for (const [name, color] of Object.entries({ success: "#157052", warning: "#8e5d10", danger: "#a3313b", info: "#1e40af" })) {
      const soft = mix(color, c.surface, 0.15);
      semantic[`--color-${name}-soft`] = soft;
      semantic[`--color-${name}-fg`] = readable(color, [soft, c.surface, c.sunken, c.muted,
        mix(c.surface, "#ffffff", palette.opacity)], true);
    }
  }
  return {
    ...semantic,
    "--color-bg": c.background, "--color-surface": c.surface, "--color-surface-raised": c.surface,
    "--color-panel": c.muted, "--color-surface-sunken": c.sunken, "--color-surface-muted": c.muted,
    "--color-surface-hover": c.hover, "--color-fg": c.text,
    "--color-fg-muted": c.secondary, "--color-fg-subtle": c.secondary, "--color-fg-faint": c.secondary,
    "--color-fg-disabled": c.borderStrong, "--color-border": c.border, "--color-border-strong": c.borderStrong,
    "--color-accent": c.accent, "--color-accent-hover": c.accentHover, "--color-accent-active": c.accentActive,
    "--color-accent-fg": c.accentText, "--color-accent-soft": c.accentSoft, "--color-accent-soft-fg": c.accent,
    "--color-rail-bg": c.surface, "--color-rail-surface": c.muted, "--color-rail-active": c.accentSoft,
    "--color-rail-border": c.border, "--color-rail-fg": c.secondary, "--color-rail-fg-strong": c.text,
    "--color-rail-fg-muted": c.secondary, "--color-rail-accent": c.accent,
    "--pa-btn-primary-bg": c.accent, "--pa-btn-primary-bg-hover": c.accentHover,
    "--pa-rail-brand-border": c.border, "--pa-rail-brand-bg": c.accentSoft,
    "--pa-rail-active-border": c.border, "--pa-rail-icon-bg": c.muted, "--pa-rail-running-glow": c.accentSoft,
    "--wallpaper-panel": panel,
  };
}
