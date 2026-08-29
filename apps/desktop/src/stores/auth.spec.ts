import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";

import { getAccessToken } from "../auth/session";
import { useAuthStore } from "./auth";

const authService = vi.hoisted(() => ({
  loginAccount: vi.fn(),
  registerAccount: vi.fn(),
  getCurrentAccount: vi.fn(),
  logoutAccount: vi.fn(),
}));

vi.mock("../services/auth", () => authService);

const user = {
  id: 7,
  email: "user@example.com",
  display_name: "User",
  role: "user" as const,
  status: "active" as const,
  last_login_at: null,
  created_at: "2026-08-29T00:00:00Z",
};

describe("auth store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    window.sessionStorage.clear();
    vi.clearAllMocks();
  });

  it("stores the server session after login", async () => {
    authService.loginAccount.mockResolvedValue({
      access_token: "user-session-token",
      token_type: "bearer",
      expires_at: "2026-09-05T00:00:00Z",
      user,
    });
    const store = useAuthStore();

    await store.login({ email: user.email, password: "password-123" });

    expect(store.user).toEqual(user);
    expect(store.isAuthenticated).toBe(true);
    expect(getAccessToken()).toBe("user-session-token");
  });

  it("clears an invalid persisted session", async () => {
    window.sessionStorage.setItem("pa_access_token", "expired-token");
    authService.getCurrentAccount.mockRejectedValue(new Error("Unauthorized"));
    const store = useAuthStore();

    await expect(store.restoreSession()).resolves.toBe(false);

    expect(store.user).toBeNull();
    expect(getAccessToken()).toBeNull();
  });
});
