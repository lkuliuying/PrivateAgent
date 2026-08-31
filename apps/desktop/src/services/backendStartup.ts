import { reactive, readonly } from "vue";
import { startLocalExecutor, usesLocalExecutor } from "./localExecutor";

import { getApiInfo } from "../api";
import {
  hasConfiguredRemoteApi,
  ensureApiBase,
  setApiBase,
  setApiBaseDefault,
} from "../api/http";
import {
  cmdStartSidecar,
  getApiConnection,
  getSidecarStartupError,
  isDesktopRuntime,
} from "../api/tauri";

let startupPromise: Promise<void> | null = null;

export type BackendStartupStatus = "idle" | "starting" | "ready" | "error";

const mutableBackendStartupState = reactive({
  status: "idle" as BackendStartupStatus,
  error: "",
});

export const backendStartupState = readonly(mutableBackendStartupState);

function wait(milliseconds: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}

async function waitForApi(attempts: number): Promise<boolean> {
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    try {
      await getApiInfo();
      return true;
    } catch {
      const startupError = await getSidecarStartupError().catch(() => null);
      if (startupError) throw new Error(startupError);
      if (attempt < attempts - 1) await wait(200);
    }
  }
  return false;
}

async function startDesktopBackend(): Promise<void> {
  if (hasConfiguredRemoteApi() || !isDesktopRuntime()) {
    setApiBaseDefault();
    if (hasConfiguredRemoteApi() && usesLocalExecutor()) await startLocalExecutor(await ensureApiBase());
    return;
  }

  const existing = await getApiConnection().catch(() => null);
  if (existing) {
    setApiBase(existing.port, existing.token);
    if (await waitForApi(5)) return;
  }

  const result = await cmdStartSidecar();
  if (result.dev_mode) {
    setApiBaseDefault();
    return;
  }
  if (!result.ok || !result.port || !result.token) {
    throw new Error(result.error || "本地后端启动失败");
  }

  setApiBase(result.port, result.token);
  if (!(await waitForApi(450))) {
    throw new Error("本地后端启动超时，请检查数据库连接后重试");
  }
}

/** Ensure auth requests never race the packaged sidecar startup. */
export function ensureDesktopBackendReady(): Promise<void> {
  if (startupPromise) return startupPromise;
  mutableBackendStartupState.status = "starting";
  mutableBackendStartupState.error = "";
  const current = startDesktopBackend();
  startupPromise = current;
  void current.then(
    () => {
      if (startupPromise !== current) return;
      mutableBackendStartupState.status = "ready";
    },
    (reason: unknown) => {
      if (startupPromise !== current) return;
      startupPromise = null;
      mutableBackendStartupState.status = "error";
      mutableBackendStartupState.error =
        reason instanceof Error ? reason.message : "本地后端启动失败，请重试";
    }
  );
  return current;
}

export function resetDesktopBackendStartup(): void {
  startupPromise = null;
  mutableBackendStartupState.status = "idle";
  mutableBackendStartupState.error = "";
}

export function retryDesktopBackendStartup(): Promise<void> {
  resetDesktopBackendStartup();
  return ensureDesktopBackendReady();
}
