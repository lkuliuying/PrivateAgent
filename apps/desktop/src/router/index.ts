import { createRouter, createWebHashHistory } from "vue-router";

import { useAuthStore } from "../stores/auth";
import { pinia } from "../stores/pinia";

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
  const auth = useAuthStore(pinia);
  const authenticated = await auth.restoreSession();

  if (to.meta.publicOnly && authenticated) return { name: "workspace" };
  if (to.meta.requiresAuth && !authenticated) {
    return {
      name: "login",
      query: { redirect: to.fullPath },
    };
  }
  if (to.meta.requiresAdmin && !auth.isAdmin) return { name: "workspace" };
  return true;
});

export default router;
