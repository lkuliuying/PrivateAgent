import { theme } from "ant-design-vue";
import type { ThemeConfig } from "ant-design-vue/es/config-provider/context";
import type { WallpaperPalette } from "./palette";

export function wallpaperAntTheme(palette?: WallpaperPalette): ThemeConfig {
  // 始终保留 DesignTokenProvider，避免从 undefined 切换时重建整棵业务组件树。
  const sharedTokens = { borderRadius: 8, fontSize: 14, fontFamily: '"Segoe UI", "Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC", sans-serif' };
  if (!palette) return { token: { ...sharedTokens, colorPrimary: "#007c89", colorText: "#0f2838", colorTextSecondary: "#4f666e", colorBorder: "#dce8ea", colorBgLayout: "#f8fafc" } };
  const c = palette.colors;
  return {
    algorithm: palette.mode === "dark" ? theme.darkAlgorithm : theme.defaultAlgorithm,
    token: {
      ...sharedTokens,
      colorPrimary: c.accent, colorPrimaryHover: c.accentHover, colorPrimaryActive: c.accentActive,
      colorPrimaryBg: c.accentSoft, colorPrimaryBgHover: c.hover, colorPrimaryBorder: c.accent,
      colorLink: c.accent, colorLinkHover: c.accentHover, colorLinkActive: c.accentActive,
      colorText: c.text, colorTextSecondary: c.secondary, colorTextTertiary: c.secondary,
      colorTextQuaternary: c.secondary, colorTextPlaceholder: c.secondary, colorTextLightSolid: c.accentText,
      colorBgBase: c.background, colorBgLayout: c.background, colorBgContainer: c.surface,
      colorBgElevated: c.surface, colorFillAlter: c.muted, colorFillSecondary: c.hover,
      colorBorder: c.borderStrong, colorBorderSecondary: c.border,
    },
  };
}
