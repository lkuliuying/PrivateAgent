import { createRouter, createWebHashHistory } from "vue-router";
import { ensureDesktopBackendReady } from "../services/backendStartup";

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: "/app", name: "workspace", component: () => import("../App.vue") },
    { path: "/", redirect: "/app" },
    { path: "/:pathMatch(.*)*", redirect: "/app" },
  ],
});

router.beforeEach(async () => {
  try {
    await ensureDesktopBackendReady();
  } catch {
    // 根组件显示启动失败及重试入口，失败时不会挂载工作台。
  }
  return true;
});

export default router;
