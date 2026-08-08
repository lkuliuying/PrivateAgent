/**
 * Vitest 全局 setup：jsdom 缺失 API 补丁。
 * matchMedia 用于 prefers-reduced-motion 检测；测试默认视为未启用减少动态效果。
 */
if (!window.matchMedia) {
  window.matchMedia = ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
}
