import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

// @ts-expect-error process is a nodejs global
const host = process.env.TAURI_DEV_HOST;
// @ts-expect-error process is a nodejs global
const connectedDesktop = process.env.VITE_LOCAL_EXECUTOR === "true";

// https://vite.dev/config/
export default defineConfig(async () => ({
  plugins: [vue()],
  // Connected installers receive only the sanitized build environment.
  envDir: connectedDesktop ? false : undefined,

  // Vite options tailored for Tauri development and only applied in `tauri dev` or `tauri build`
  //
  // 1. prevent Vite from obscuring rust errors
  clearScreen: false,
  // 2. code-split vendor libs into a stable chunk（避免单个 574KB chunk）
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          vendor: ["vue", "@phosphor-icons/vue"],
          framework: ["pinia", "vue-router"],
          antd: ["ant-design-vue", "@ant-design/icons-vue"],
          tauri: ["@tauri-apps/api", "@tauri-apps/plugin-dialog", "@tauri-apps/plugin-opener"],
        },
      },
    },
  },
  // 3. tauri expects a fixed port, fail if that port is not available
  server: {
    port: 1420,
    strictPort: true,
    host: host || false,
    hmr: host
      ? {
          protocol: "ws",
          host,
          port: 1421,
        }
      : undefined,
    watch: {
      // 3. tell Vite to ignore watching `src-tauri`
      ignored: ["**/src-tauri/**"],
    },
  },
}));
