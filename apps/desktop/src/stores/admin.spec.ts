import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";

import { useAdminStore } from "./admin";

const adminService = vi.hoisted(() => ({
  createAdminUser: vi.fn(),
  getAdminOverview: vi.fn(),
  getAdminUsers: vi.fn(),
  getAuditLogs: vi.fn(),
  updateAdminUser: vi.fn(),
}));

vi.mock("../services/admin", () => adminService);

const user = {
  id: 9,
  email: "managed@example.com",
  username: "managed-user",
  display_name: "managed-user",
  role: "user" as const,
  status: "active" as const,
  last_login_at: null,
  created_at: "2026-08-29T00:00:00Z",
};

describe("admin store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  it("forwards user filters to the admin service", async () => {
    adminService.getAdminUsers.mockResolvedValue({ total: 0, results: [] });
    const store = useAdminStore();
    const filters = {
      page: 1,
      size: 20,
      search: "managed",
      role: "user" as const,
      status: "active" as const,
    };

    await store.loadUsers(filters);

    expect(adminService.getAdminUsers).toHaveBeenCalledWith(filters);
    expect(store.loading.users).toBe(false);
  });

  it("creates and updates users while exposing mutation loading", async () => {
    adminService.createAdminUser.mockResolvedValue(user);
    adminService.updateAdminUser.mockResolvedValue({ ...user, status: "disabled" });
    const store = useAdminStore();
    const createPayload = {
      email: user.email,
      username: user.username,
      password: "managed-password-123",
      role: "user" as const,
    };

    await expect(store.createUser(createPayload)).resolves.toEqual(user);
    await expect(store.updateUser(user.id, { status: "disabled" })).resolves.toEqual({
      ...user,
      status: "disabled",
    });

    expect(adminService.createAdminUser).toHaveBeenCalledWith(createPayload);
    expect(adminService.updateAdminUser).toHaveBeenCalledWith(user.id, {
      status: "disabled",
    });
    expect(store.loading.mutation).toBe(false);
  });

  it("always clears mutation loading after a failed request", async () => {
    adminService.updateAdminUser.mockRejectedValue(new Error("request failed"));
    const store = useAdminStore();

    await expect(store.updateUser(user.id, { role: "admin" })).rejects.toThrow(
      "request failed"
    );

    expect(store.loading.mutation).toBe(false);
  });
});
