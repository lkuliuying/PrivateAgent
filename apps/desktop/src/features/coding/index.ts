/**
 * Coding 领域导出（v0.8.0 W1）：新代码只落在 features/coding/（W0 冻结 §5），
 * 不回填全局 api.ts/types.ts；兼容 re-export 策略见计划 §5.4。
 */
export { default as CodingSidebar } from "./components/CodingSidebar.vue";
export { default as CodingHome } from "./components/CodingHome.vue";
export { default as CodingThreadWorkspace } from "./components/CodingThreadWorkspace.vue";
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
