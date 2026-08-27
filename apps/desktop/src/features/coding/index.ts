/**
 * Coding 领域导出（v0.8.0）：新代码只落在 features/coding/（W0 冻结 §5），
 * 不回填全局 api.ts/types.ts；兼容 re-export 策略见计划 §5.4。
 */
export { default as CodingSidebar } from "./components/CodingSidebar.vue";
export { default as CodingHome } from "./components/CodingHome.vue";
export { default as CodingThreadWorkspace } from "./components/CodingThreadWorkspace.vue";
export { default as ThreadHeader } from "./components/ThreadHeader.vue";
export { default as RunTranscript } from "./components/RunTranscript.vue";
export { default as RunPlanPopover } from "./components/RunPlanPopover.vue";
export { default as DiffArtifact } from "./components/DiffArtifact.vue";
export { default as CommandOutput } from "./components/CommandOutput.vue";
export { default as ContextDrawer } from "./components/ContextDrawer.vue";
export { default as CodingComposer } from "./components/CodingComposer.vue";
export type { CodingComposerSendPayload } from "./components/CodingComposer.vue";
export {
  createCodingWorkspaceStore,
  useCodingWorkspace,
  type CodingLoadPhase,
  type CodingWorkspaceStore,
} from "./model/codingWorkspaceStore";
export type {
  CodingApiError,
  CodingHomeState,
  CodingModelProfileSummary,
  CodingModelProfilesResult,
  CodingPermissionMode,
  CodingProjectNode,
  CodingProjectSummary,
  CodingThreadCreateInput,
  CodingThreadSummary,
  CodingWorkspaceFetchers,
  CodingWorkspaceNode,
  CodingWorkspaceSummary,
} from "./model/contracts";
export { WORKSPACE_STATUS_META, isWorkspaceUsable } from "./model/contracts";
export {
  applyRunFrame,
  cloneRunProjection,
  createRunProjection,
  reconcileRunWithSnapshot,
  type RunProjection,
  type TranscriptEntry,
  type ToolActivityState,
} from "./model/runProjector";
export {
  RUN_STATUS_META,
  PLAN_ITEM_META,
  PERMISSION_MODE_META,
  TERMINAL_RUN_STATUSES,
  isTerminalRunStatus,
  type AgentRunStatus,
  type CodingFileHint,
  type CodingRunCreateInput,
  type RunApprovalPreviewRecord,
  type RunApprovalRecord,
  type RunConnectionPhase,
  type RunEventPage,
  type RunEventRecord,
  type RunExecutionOutputPage,
  type RunExecutionRecord,
  type RunPlanItemRecord,
  type RunPlanItemStatus,
  type RunPlanState,
  type RunSnapshot,
  type RunStreamEventType,
  type RunStreamFrame,
} from "./model/runContracts";
export { useRunStream, type RunStreamController, type RunStreamDeps } from "./composables/useRunStream";
