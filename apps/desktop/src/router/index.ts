import { createRouter, createWebHashHistory } from "vue-router";

import { useAuthStore } from "../stores/auth";
import { pinia } from "../stores/pinia";
import { ensureDesktopBackendReady } from "../services/backendStartup";

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    {
      path: "/login",
      name: "login",
      component: () => import("../pages/AuthPage.vue"),
      props: { mode: "login" },
      meta: { publicOnly: true },
    },
    {
      path: "/register",
      name: "register",
      component: () => import("../pages/AuthPage.vue"),
      props: { mode: "register" },
      meta: { publicOnly: true },
    },
    {
      path: "/app",
      name: "workspace",
      component: () => import("../App.vue"),
      meta: { requiresAuth: true },
    },
    {
      path: "/admin",
      name: "admin",
      component: () => import("../pages/AdminPage.vue"),
      meta: { requiresAuth: true, requiresAdmin: true },
    },
    { path: "/", redirect: "/app" },
    { path: "/:pathMatch(.*)*", redirect: "/app" },
  ],
});

router.beforeEach(async (to) => {
  try {
    await ensureDesktopBackendReady();
  } catch {
    // 公共登录页展示服务器配置或本机执行器启动错误，不回退到其他连接方式。
    if (to.meta.requiresAuth) {
      return { name: "login", query: { redirect: to.fullPath } };
    }
    return true;
  }
  const auth = useAuthStore(pinia);
  const authenticated = await auth.restoreSession();

  if (to.meta.requiresAuth && !authenticated) {
    return {
      name: "login",
      query: { redirect: to.fullPath },
    };
  }
  if (to.meta.publicOnly && authenticated) {
    return { name: auth.isAdmin ? "admin" : "workspace" };
  }
  // 管理员账号只使用监控与用户管理控制台，不进入普通项目工作台。
  if (authenticated && auth.isAdmin && to.name !== "admin") {
    return { name: "admin" };
  }
  if (to.meta.requiresAdmin && !auth.isAdmin) return { name: "workspace" };
  return true;
});

export default router;
