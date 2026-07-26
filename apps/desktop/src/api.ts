export {
  apiFetch,
  ensureApiBase,
  resetApiBase,
  setApiBase,
  setApiConnection,
  setApiBaseDefault,
} from "./api/http";
export {
  approveToolCall,
  createSession,
  getMessages,
  listSessions,
  listToolCalls,
  planTools,
  rejectToolCall,
  streamChat,
} from "./api/chat";
export {
  cmdCheckForUpdates,
  cmdCheckDependencies,
  cmdConfigExists,
  cmdDownloadAndInstallUpdate,
  cmdReadConfig,
  cmdRelaunchApp,
  cmdStartSidecar,
  cmdTestConnections,
  cmdWriteConfig,
  isDesktopRuntime,
  pickDirectory,
  pickFile,
} from "./api/tauri";
export {
  createNotification,
  listNotifications,
  patchNotification,
  readAllNotifications,
} from "./api/notifications";
export { recordRecentOpen, search } from "./api/search";
export type { SearchResult } from "./api/search";
export {
  captureToInbox,
  captureToMemory,
  captureToReminder,
  createCapture,
  listCapture,
} from "./api/capture";
export type { CaptureItem } from "./api/capture";
export { getOcrAvailability, listOcrJobs, retryOcrJob } from "./api/ocr";
export type { OcrAvailability, OcrJob } from "./api/ocr";
export { exportDiagnostics, getDiagnostics } from "./api/diagnostics";
export type { DiagnosticsSnapshot } from "./api/diagnostics";
export {
  applyRepair,
  listIntegrity,
  repairPlan,
  runIntegrity,
} from "./api/maintenance";
export type { IntegrityFinding, RepairPlanItem } from "./api/maintenance";
export { listExtensions, patchExtension } from "./api/extensions";
export type { ExtensionDescriptor } from "./api/extensions";
export {
  createIntegrationSource,
  listIntegrationImports,
  listIntegrationSources,
  previewIntegration,
  revertIntegrationImport,
  runIntegrationImport,
} from "./api/integrations";
export type {
  IntegrationImport,
  IntegrationPreview,
  IntegrationSource,
} from "./api/integrations";
export { getMigrationRunbook, restoreDrillBackup } from "./api/backup";
export { listTestRuns, listUpgradeSmokeRuns } from "./api/testing";
export type {
  ConfigData,
  ConnResult,
  DepResult,
  SidecarStartResult,
  UpdateInfo,
} from "./api/tauri";
export * from "./api/system";
export * from "./api/documents";
export * from "./api/tools";
export * from "./api/activities";
export * from "./api/files";
export * from "./api/projects";
export * from "./api/agent-tasks";
export * from "./api/learning";
export * from "./api/memory";
export * from "./api/collections";
export * from "./api/patches";
export * from "./api/project-commands";
export * from "./api/providers";
export * from "./api/backups";
export * from "./api/today";
export * from "./api/inbox";
export * from "./api/reminders";
export * from "./api/goals";
export * from "./api/briefings";
export * from "./api/privacy";
export * from "./api/settings";
