import { reactive, readonly } from "vue";
import { startLocalExecutor, usesLocalExecutor } from "./localExecutor";
import { ensureApiBase } from "../api/http";

let startupPromise: Promise<void> | null = null;

export type BackendStartupStatus = "idle" | "starting" | "ready" | "error";

const mutableBackendStartupState = reactive({
  status: "idle" as BackendStartupStatus,
  error: "",
});

export const backendStartupState = readonly(mutableBackendStartupState);

async function startDesktopBackend(): Promise<void> {
  await ensureApiBase();
  if (usesLocalExecutor()) await startLocalExecutor();
}

/** 先核对服务器地址并准备本机执行器，不启动完整业务后端或创建本机账号。 */
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
