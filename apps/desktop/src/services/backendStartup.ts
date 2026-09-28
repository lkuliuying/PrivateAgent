import { reactive, readonly } from "vue";
import { bindLocalAccess, startLocalExecutor } from "./localExecutor";
import { clearLocalSession, discardLegacyAccountSession, setLocalAccessToken } from "../auth/session";

let startupPromise: Promise<void> | null = null;

export type BackendStartupStatus = "idle" | "starting" | "ready" | "error";

const mutableBackendStartupState = reactive({
  status: "idle" as BackendStartupStatus,
  error: "",
});

export const backendStartupState = readonly(mutableBackendStartupState);

async function startDesktopBackend(): Promise<void> {
  discardLegacyAccountSession();
  clearLocalSession();
  await startLocalExecutor();
  setLocalAccessToken(await bindLocalAccess());
}

/** 并发入口共享启动和本机身份绑定，工作台挂载前即拥有有效凭证。 */
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
        reason instanceof Error ? reason.message : "客户端连接准备失败，请重试";
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
