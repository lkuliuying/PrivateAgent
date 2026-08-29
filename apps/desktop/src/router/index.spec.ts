import { beforeEach, describe, expect, it, vi } from "vitest";

const auth = vi.hoisted(() => ({
  isAdmin: false,
  restoreSession: vi.fn(),
}));

vi.mock("../stores/auth", () => ({
  useAuthStore: () => auth,
}));
vi.mock("../stores/pinia", () => ({ pinia: {} }));
vi.mock("../services/backendStartup", () => ({
  ensureDesktopBackendReady: vi.fn().mockResolvedValue(undefined),
}));

import router from "./index";

describe("router administrator isolation", () => {
  beforeEach(async () => {
    vi.clearAllMocks();
    auth.isAdmin = false;
    auth.restoreSession.mockResolvedValue(false);
    await router.replace({ name: "login", query: { reset: String(Date.now()) } });
  });

  it("redirects an administrator away from the regular workspace", async () => {
    auth.isAdmin = true;
    auth.restoreSession.mockResolvedValue(true);

    await router.push({ name: "workspace" });

    expect(router.currentRoute.value.name).toBe("admin");
  });

  it("redirects a regular user away from the administrator console", async () => {
    auth.isAdmin = false;
    auth.restoreSession.mockResolvedValue(true);

    await router.push({ name: "admin" });

    expect(router.currentRoute.value.name).toBe("workspace");
  });
});
