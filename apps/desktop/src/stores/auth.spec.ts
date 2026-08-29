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
  username: "User",
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

    await store.login({ identifier: user.email, password: "password-123" });

    expect(store.user).toEqual(user);
    expect(store.isAuthenticated).toBe(true);
    expect(getAccessToken()).toBe("user-session-token");
  });

  it("registers with username and email verification code", async () => {
    authService.registerAccount.mockResolvedValue({
      access_token: "registered-session-token",
      token_type: "bearer",
      expires_at: "2026-09-05T00:00:00Z",
      user,
    });
    const store = useAuthStore();
    const payload = {
      email: user.email,
      username: user.username,
      password: "password-123",
      verification_code: "A1B2C3",
    };

    await store.register(payload);

    expect(authService.registerAccount).toHaveBeenCalledWith(payload);
    expect(store.user).toEqual(user);
    expect(getAccessToken()).toBe("registered-session-token");
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
