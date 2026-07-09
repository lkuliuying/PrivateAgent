import { defineConfig } from "vitest/config";
import vue from "@vitejs/plugin-vue";

// 第八阶段 M1：Vitest 组件测试配置。
// jsdom 环境；组件用相对导入（../api、../stores），各测试用 vi.mock 注入桩。
export default defineConfig({
  plugins: [vue()],
  test: {
    environment: "jsdom",
    globals: true,
    include: ["src/**/*.spec.ts"],
    coverage: { reporter: ["text", "html"] },
  },
});
