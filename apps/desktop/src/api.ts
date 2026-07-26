import { ensureApiBase } from "./api/http";
import type {
  AgentTask,
  Activity,
  BackupExportResult,
  BatchImportItem,
  ChunkDetail,
  CodeFileContent,
  CompareResult,
  ContentSearchResponse,
  CollectionDetail,
  CollectionDetailItem,
  DocumentCollection,
  DocumentExtraction,
  DocumentItem,
  ExtractRequest,
  OcrResult,
  TemplateReportRequest,
  TemplateReportResponse,
  ExportResult,
  GitDiff,
  GitStatus,
  GradeResult,
  LearningCard,
  LearningDashboard,
  LearningNode,
  LearningNote,
  LearningQuiz,
  LearningTopic,
  MemoryEvent,
  MemoryItem,
  MemoryKind,
  MemoryStatus,
  NameSearchResponse,
  ApplyResult,
  CommandProfileCreate,
  CommandProfileUpdate,
  DiagnoseRequest,
  DiagnoseResult,
  PatchSet,
  PatchSetCreate,
  Project,
  ProjectCommandProfile,
  ProjectFile,
  ProjectStats,
  ProjectTree,
  ProviderStatus,
  ReviewRating,
  ReviewResponse,
  RunResult,
  ScanResponse,
  SectionSummary,
  SummarizeResult,
  ToolDefinition,
  TrustedPath,
  WeakPoint,
  WeeklyReport,
  WrongAnswer,
  BackupRestorePreview,
  InboxCreate,
  InboxItem,
  InboxUpdate,
  Reminder,
  ReminderCreate,
  ReminderUpdate,
  TodaySnapshot,
  TodayFilters,
  Briefing,
  GoalCheckin,
  GoalCreate,
  GoalDetail,
  GoalLink,
  GoalUpdate,
  MaintenanceHealthReport,
  PersonalGoal,
  PrivacyPreview,
  ProviderCallAudit,
} from "./types";

export {
  ensureApiBase,
  resetApiBase,
  setApiBase,
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

export async function getHealth(): Promise<Record<string, unknown>> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/health`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function getApiInfo(): Promise<Record<string, unknown>> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

// ---- 文档 / 知识库 ----
export async function listDocuments(
  search?: string,
  status?: string,
  enabled?: boolean,
  docType?: string,
  topic?: string,
  language?: string
): Promise<DocumentItem[]> {
  const base = await ensureApiBase();
  const params = new URLSearchParams();
  if (search) params.set("search", search);
  if (status) params.set("status", status);
  if (enabled !== undefined) params.set("enabled", String(enabled));
  if (docType) params.set("doc_type", docType);
  if (topic) params.set("topic", topic);
  if (language) params.set("language", language);
  const qs = params.toString() ? `?${params}` : "";
  const r = await fetch(`${base}/documents${qs}`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function importDocument(file: File): Promise<DocumentItem> {
  const base = await ensureApiBase();
  const fd = new FormData();
  fd.append("file", file);
  const r = await fetch(`${base}/documents/import`, { method: "POST", body: fd });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function deleteDocument(id: number): Promise<void> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/documents/${id}`, { method: "DELETE" });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
}

export async function retryDocument(id: number): Promise<DocumentItem> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/documents/${id}/retry`, { method: "POST" });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

// ---- 知识库增强（第二阶段 M3）----
export async function batchImportDocuments(
  files: File[]
): Promise<BatchImportItem[]> {
  const base = await ensureApiBase();
  const fd = new FormData();
  for (const f of files) fd.append("files", f);
  const r = await fetch(`${base}/documents/batch-import`, {
    method: "POST",
    body: fd,
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function patchDocument(
  id: number,
  enabled: boolean,
  metadata?: {
    doc_type?: string;
    topic?: string;
    tags?: string[];
    language?: string;
    project_id?: number;
  }
): Promise<DocumentItem> {
  const base = await ensureApiBase();
  const body: Record<string, unknown> = { enabled };
  if (metadata) Object.assign(body, metadata);
  const r = await fetch(`${base}/documents/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function reindexDocument(id: number): Promise<DocumentItem> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/documents/${id}/reindex`, { method: "POST" });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function reindexAllDocuments(): Promise<{
  triggered: number;
  skipped: number;
}> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/documents/reindex-all`, { method: "POST" });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function getChunk(id: number): Promise<ChunkDetail> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/chunks/${id}`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

// ---- 工具调用（第二阶段 M1）----
export async function listTools(): Promise<ToolDefinition[]> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/tools`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

// ---- 文件授权（M1 文本式，M2 替换为 Tauri 选择器）----
export async function authorizeFile(
  path: string,
  kind: "file" | "directory" = "file"
): Promise<TrustedPath> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/files/authorize`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path, kind }),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function listTrustedPaths(): Promise<TrustedPath[]> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/files/trusted`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

// ---- 活动流（第二阶段 M4）----
export async function listActivities(
  sessionId?: number,
  kind?: string,
  status?: string
): Promise<Activity[]> {
  const base = await ensureApiBase();
  const params = new URLSearchParams();
  if (sessionId) params.set("session_id", String(sessionId));
  if (kind) params.set("kind", kind);
  if (status) params.set("status", status);
  const qs = params.toString() ? `?${params}` : "";
  const r = await fetch(`${base}/activities${qs}`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function retryActivity(id: number): Promise<Activity> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/activities/${id}/retry`, { method: "POST" });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

// ---- 文件处理（第二阶段 M2）----
export async function summarizeFile(path: string): Promise<SummarizeResult> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/files/summarize`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path }),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function scanDirectory(path: string): Promise<ScanResponse> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/files/scan?path=${encodeURIComponent(path)}`);
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

// ---- 文档工作台（第三阶段 M4）----
export async function summarizeSections(
  docId: number
): Promise<SectionSummary[]> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/documents/${docId}/sections/summary`, {
    method: "POST",
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json().then((b) => b.sections);
}

export async function compareDocuments(
  docIds: number[]
): Promise<CompareResult> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/documents/compare`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ doc_ids: docIds }),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function exportMarkdown(
  content: string,
  filename: string,
  targetDir: string
): Promise<ExportResult> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/documents/export`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content, filename, target_dir: targetDir }),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function importNoteToKb(
  title: string,
  content: string
): Promise<BatchImportItem> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/documents/import-note`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title, content }),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

// ---- 项目工作区（第三阶段 M0 骨架 / M1 实现）----
export async function listProjects(): Promise<Project[]> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/projects`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function createProject(
  name: string,
  rootPath: string
): Promise<Project> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/projects`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, root_path: rootPath }),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function archiveProject(id: number): Promise<Project> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/projects/${id}`, { method: "DELETE" });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function scanProject(id: number): Promise<Project> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/projects/${id}/scan`, { method: "POST" });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function getProjectStats(id: number): Promise<ProjectStats> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/projects/${id}/stats`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function getProjectTree(id: number): Promise<ProjectTree> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/projects/${id}/tree`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function getProjectFiles(
  id: number,
  opts?: { ext?: string; language?: string }
): Promise<ProjectFile[]> {
  const base = await ensureApiBase();
  const params = new URLSearchParams();
  if (opts?.ext) params.set("ext", opts.ext);
  if (opts?.language) params.set("language", opts.language);
  const qs = params.toString() ? `?${params}` : "";
  const r = await fetch(`${base}/projects/${id}/files${qs}`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function searchProject(
  id: number,
  query: string,
  kind: "name" | "content"
): Promise<NameSearchResponse | ContentSearchResponse> {
  const base = await ensureApiBase();
  const r = await fetch(
    `${base}/projects/${id}/search?query=${encodeURIComponent(query)}&kind=${kind}`
  );
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function readProjectFile(
  id: number,
  relPath: string,
  opts?: { startLine?: number; maxLines?: number }
): Promise<CodeFileContent> {
  const base = await ensureApiBase();
  const params = new URLSearchParams({ rel_path: relPath });
  if (opts?.startLine) params.set("start_line", String(opts.startLine));
  if (opts?.maxLines) params.set("max_lines", String(opts.maxLines));
  const r = await fetch(`${base}/projects/${id}/read?${params}`);
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function getProjectGitStatus(id: number): Promise<GitStatus> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/projects/${id}/git/status`);
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function getProjectGitDiff(
  id: number,
  cached = false
): Promise<GitDiff> {
  const base = await ensureApiBase();
  const r = await fetch(
    `${base}/projects/${id}/git/diff?cached=${cached}`
  );
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

// ---- 多步 Agent 任务（第三阶段 M6）----
export async function listAgentTasks(): Promise<AgentTask[]> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/agent-tasks`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function createAgentTask(data: {
  title: string;
  goal?: string;
  project_id?: number;
  steps?: Array<{
    title: string;
    tool_name: string;
    input_json: Record<string, unknown>;
  }>;
}): Promise<AgentTask> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/agent-tasks`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function createAgentTaskPlan(data: {
  title: string;
  goal: string;
  project_id?: number;
}): Promise<AgentTask> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/agent-tasks/plan`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function runAgentTask(id: number): Promise<AgentTask> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/agent-tasks/${id}/run`, { method: "POST" });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function updateAgentTaskPlan(
  id: number,
  data: {
    title?: string;
    goal?: string;
    steps: Array<{
      title: string;
      tool_name: string;
      input_json: Record<string, unknown>;
    }>;
  }
): Promise<AgentTask> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/agent-tasks/${id}/plan`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function approveAgentTaskPlan(id: number): Promise<AgentTask> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/agent-tasks/${id}/approve-plan`, { method: "POST" });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function pauseAgentTask(id: number): Promise<AgentTask> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/agent-tasks/${id}/pause`, { method: "POST" });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function cancelAgentTask(id: number): Promise<AgentTask> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/agent-tasks/${id}/cancel`, { method: "POST" });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function resumeAgentTask(id: number): Promise<AgentTask> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/agent-tasks/${id}/resume`, { method: "POST" });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function resumeAgentTaskFrom(id: number, stepId: number): Promise<AgentTask> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/agent-tasks/${id}/resume-from/${stepId}`, {
    method: "POST",
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function approveAgentTaskStep(stepId: number): Promise<AgentTask> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/agent-task-steps/${stepId}/approve`, {
    method: "POST",
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function retryAgentTaskStep(stepId: number): Promise<AgentTask> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/agent-task-steps/${stepId}/retry`, {
    method: "POST",
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

// ---- 学习系统（第三阶段 M0 骨架 / M3 实现）----
export async function listLearningTopics(): Promise<LearningTopic[]> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/learning/topics`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function createLearningTopic(data: {
  title: string;
  goal?: string;
  level?: string;
  tags?: string[];
}): Promise<LearningTopic> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/learning/topics`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function updateLearningTopic(
  id: number,
  data: Partial<{
    title: string;
    goal: string;
    level: string;
    status: string;
    tags: string[];
  }>
): Promise<LearningTopic> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/learning/topics/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function generateLearningPlan(
  topicId: number,
  sourceDocIds?: number[]
): Promise<LearningNode[]> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/learning/topics/${topicId}/plan`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source_doc_ids: sourceDocIds }),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function listLearningNodes(topicId: number): Promise<LearningNode[]> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/learning/topics/${topicId}/nodes`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function saveLearningNote(data: {
  topic_id?: number;
  title: string;
  body_md: string;
  source_refs?: unknown[];
}): Promise<LearningNote> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/learning/notes`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function listLearningNotes(
  topicId?: number
): Promise<LearningNote[]> {
  const base = await ensureApiBase();
  const qs = topicId ? `?topic_id=${topicId}` : "";
  const r = await fetch(`${base}/learning/notes${qs}`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function generateQuiz(
  topicId: number,
  sourceDocIds?: number[],
  count = 5
): Promise<LearningQuiz[]> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/learning/topics/${topicId}/quizzes`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source_doc_ids: sourceDocIds, count }),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function listQuizzes(topicId: number): Promise<LearningQuiz[]> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/learning/topics/${topicId}/quizzes`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function gradeQuizAnswer(
  quizId: number,
  userAnswer: string
): Promise<GradeResult> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/learning/quiz-attempts`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ quiz_id: quizId, user_answer: userAnswer }),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function generateCards(
  topicId: number,
  sourceDocIds?: number[],
  count = 5
): Promise<LearningCard[]> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/learning/topics/${topicId}/cards`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source_doc_ids: sourceDocIds, count }),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function listCards(topicId: number): Promise<LearningCard[]> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/learning/topics/${topicId}/cards`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

// ---- 长期记忆（第四阶段 M1）----
export async function listMemories(opts?: {
  kind?: string;
  status?: string;
  project_id?: number;
  topic_id?: number;
  search?: string;
  enabled?: boolean;
}): Promise<MemoryItem[]> {
  const base = await ensureApiBase();
  const params = new URLSearchParams();
  if (opts?.kind) params.set("kind", opts.kind);
  if (opts?.status) params.set("status", opts.status);
  if (opts?.project_id !== undefined)
    params.set("project_id", String(opts.project_id));
  if (opts?.topic_id !== undefined)
    params.set("topic_id", String(opts.topic_id));
  if (opts?.search) params.set("search", opts.search);
  if (opts?.enabled !== undefined) params.set("enabled", String(opts.enabled));
  const qs = params.toString() ? `?${params}` : "";
  const r = await fetch(`${base}/memories${qs}`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function getMemory(id: number): Promise<MemoryItem> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/memories/${id}`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function createMemory(data: {
  kind: MemoryKind;
  title: string;
  content_md: string;
  summary?: string;
  source_type?: string;
  source_id?: number;
  project_id?: number;
  topic_id?: number;
  tags?: string[];
  confidence?: number;
  sensitive?: boolean;
}): Promise<MemoryItem> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/memories`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function updateMemory(
  id: number,
  data: {
    title?: string;
    content_md?: string;
    summary?: string;
    tags?: string[];
    confidence?: number;
    enabled?: boolean;
    sensitive?: boolean;
    status?: MemoryStatus;
  }
): Promise<MemoryItem> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/memories/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function deleteMemory(id: number): Promise<void> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/memories/${id}`, { method: "DELETE" });
  if (!r.ok && r.status !== 204) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
}

export async function searchMemories(req: {
  query?: string;
  kind?: string;
  status?: string;
  enabled?: boolean;
  project_id?: number;
  topic_id?: number;
}): Promise<MemoryItem[]> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/memories/search`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function candidateMemories(req: {
  source_type: "agent_task" | "chat_session" | "learning_review";
  source_id: number;
}): Promise<MemoryItem[]> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/memories/candidates`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function useMemory(
  id: number,
  ref?: { ref_type?: string; ref_id?: number }
): Promise<void> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/memories/${id}/use`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(ref || {}),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
}

export async function listMemoryEvents(id: number): Promise<MemoryEvent[]> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/memories/${id}/events`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

// ---- 学习复习（第四阶段 M2）----
export async function listReviewsToday(
  topicId?: number
): Promise<LearningCard[]> {
  const base = await ensureApiBase();
  const qs = topicId != null ? `?topic_id=${topicId}` : "";
  const r = await fetch(`${base}/learning/reviews/today${qs}`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function reviewCard(
  cardId: number,
  rating: ReviewRating
): Promise<ReviewResponse> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/learning/cards/${cardId}/review`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ rating }),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function topicDashboard(
  topicId: number
): Promise<LearningDashboard> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/learning/topics/${topicId}/dashboard`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function weakPoints(topicId: number): Promise<WeakPoint[]> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/learning/topics/${topicId}/weak-points`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function wrongAnswers(topicId: number): Promise<WrongAnswer[]> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/learning/topics/${topicId}/wrong-answers`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function weeklyReport(topicId: number): Promise<WeeklyReport> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/learning/topics/${topicId}/weekly-report`, {
    method: "POST",
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

// ---- 文档集合 / 抽取 / 模板报告（第四阶段 M3）----
export async function listDocumentCollections(): Promise<DocumentCollection[]> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/document-collections`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function createDocumentCollection(data: {
  title: string;
  goal?: string;
  tags?: string[];
}): Promise<DocumentCollection> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/document-collections`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function getDocumentCollection(
  id: number
): Promise<CollectionDetail> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/document-collections/${id}`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function updateDocumentCollection(
  id: number,
  data: { title?: string; goal?: string; tags?: string[] }
): Promise<DocumentCollection> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/document-collections/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function deleteDocumentCollection(id: number): Promise<void> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/document-collections/${id}`, { method: "DELETE" });
  if (!r.ok && r.status !== 204) throw new Error(`HTTP ${r.status}`);
}

export async function addCollectionItem(
  collectionId: number,
  docId: number
): Promise<CollectionDetailItem> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/document-collections/${collectionId}/items`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ doc_id: docId }),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function removeCollectionItem(
  collectionId: number,
  docId: number
): Promise<void> {
  const base = await ensureApiBase();
  const r = await fetch(
    `${base}/document-collections/${collectionId}/items/${docId}`,
    { method: "DELETE" }
  );
  if (!r.ok && r.status !== 204) throw new Error(`HTTP ${r.status}`);
}

export async function extractDocument(
  docId: number,
  kind: ExtractRequest["kind"]
): Promise<DocumentExtraction> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/documents/${docId}/extract`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ kind }),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function extractCollection(
  collectionId: number,
  kind: ExtractRequest["kind"]
): Promise<DocumentExtraction> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/document-collections/${collectionId}/extract`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ kind }),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function templateReport(
  req: TemplateReportRequest
): Promise<TemplateReportResponse> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/documents/template-report`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function ocrDocument(docId: number): Promise<OcrResult> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/documents/${docId}/ocr`, { method: "POST" });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function listDocumentExtractions(
  docId: number,
  kind?: string
): Promise<DocumentExtraction[]> {
  const base = await ensureApiBase();
  const qs = kind ? `?kind=${kind}` : "";
  const r = await fetch(`${base}/documents/${docId}/extractions${qs}`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function listCollectionExtractions(
  collectionId: number,
  kind?: string
): Promise<DocumentExtraction[]> {
  const base = await ensureApiBase();
  const qs = kind ? `?kind=${kind}` : "";
  const r = await fetch(
    `${base}/document-collections/${collectionId}/extractions${qs}`
  );
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

// ---- Patch set（第四阶段 M4）----
export async function listPatchSets(projectId: number): Promise<PatchSet[]> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/projects/${projectId}/patch-sets`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function createPatchSet(
  projectId: number,
  data: PatchSetCreate
): Promise<PatchSet> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/projects/${projectId}/patch-sets`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function getPatchSet(patchSetId: number): Promise<PatchSet> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/patch-sets/${patchSetId}`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function submitPatchSet(patchSetId: number): Promise<PatchSet> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/patch-sets/${patchSetId}/submit`, { method: "POST" });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function applyPatchSet(patchSetId: number): Promise<ApplyResult> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/patch-sets/${patchSetId}/apply`, { method: "POST" });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function rejectPatchSet(patchSetId: number): Promise<PatchSet> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/patch-sets/${patchSetId}/reject`, { method: "POST" });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function rollbackPatchSet(patchSetId: number): Promise<ApplyResult> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/patch-sets/${patchSetId}/rollback`, { method: "POST" });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

// ---- 命令配置 / 诊断（第四阶段 M4）----
export async function listProjectCommands(
  projectId: number
): Promise<ProjectCommandProfile[]> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/projects/${projectId}/commands`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function createProjectCommand(
  projectId: number,
  data: CommandProfileCreate
): Promise<ProjectCommandProfile> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/projects/${projectId}/commands`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function updateProjectCommand(
  projectId: number,
  commandId: number,
  data: CommandProfileUpdate
): Promise<ProjectCommandProfile> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/projects/${projectId}/commands/${commandId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function deleteProjectCommand(
  projectId: number,
  commandId: number
): Promise<ProjectCommandProfile> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/projects/${projectId}/commands/${commandId}`, {
    method: "DELETE",
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function runProjectCommand(
  projectId: number,
  commandId: number
): Promise<RunResult> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/projects/${projectId}/commands/${commandId}/run`, {
    method: "POST",
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function diagnoseCommandOutput(
  projectId: number,
  data: DiagnoseRequest
): Promise<DiagnoseResult> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/projects/${projectId}/diagnose-command-output`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

// ---- Provider（第四阶段 M6）----
export async function listProviders(): Promise<ProviderStatus> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/providers`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function updateProviders(data: {
  provider_type?: "ollama" | "openai" | "claude";
  remote_provider_enabled?: boolean;
  openai_api_key?: string;
  openai_base_url?: string;
  openai_model?: string;
  claude_api_key?: string;
  claude_model?: string;
}): Promise<ProviderStatus> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/providers`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function testProvider(): Promise<Record<string, unknown>> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/providers/test`, { method: "POST" });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

// ---- 备份（第四阶段 M6）----
export async function listBackups(): Promise<{ items: BackupExportResult[]; last_backup_at: string | null }> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/backup`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function exportBackup(): Promise<BackupExportResult> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/backup/export`, { method: "POST" });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function previewRestoreBackup(path: string): Promise<BackupRestorePreview> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/backup/restore/preview`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path }),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

// ---- 今日中枢 / 收件箱（第六阶段 M2）----
export async function getToday(filters?: TodayFilters): Promise<TodaySnapshot> {
  const base = await ensureApiBase();
  const qs = new URLSearchParams();
  if (filters?.type) qs.set("type", filters.type);
  if (filters?.priority) qs.set("priority", filters.priority);
  if (filters?.time) qs.set("time", filters.time);
  if (filters?.status) qs.set("status", filters.status);
  const q = qs.toString();
  const r = await fetch(`${base}/today${q ? `?${q}` : ""}`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function listInbox(opts?: {
  status?: string;
  item_type?: string;
  priority?: string;
  source_type?: string;
}): Promise<InboxItem[]> {
  const base = await ensureApiBase();
  const params = new URLSearchParams();
  if (opts?.status) params.set("status", opts.status);
  if (opts?.item_type) params.set("item_type", opts.item_type);
  if (opts?.priority) params.set("priority", opts.priority);
  if (opts?.source_type) params.set("source_type", opts.source_type);
  const qs = params.toString() ? `?${params}` : "";
  const r = await fetch(`${base}/inbox${qs}`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function createInbox(data: InboxCreate): Promise<InboxItem> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/inbox`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function updateInbox(
  id: number,
  data: InboxUpdate
): Promise<InboxItem> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/inbox/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function deleteInbox(id: number): Promise<void> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/inbox/${id}`, { method: "DELETE" });
  if (!r.ok && r.status !== 204) throw new Error(`HTTP ${r.status}`);
}

export async function inboxToTask(id: number): Promise<InboxItem> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/inbox/${id}/to-task`, { method: "POST" });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function inboxToReminder(
  id: number,
  data?: { due_at?: string; recurrence_rule?: Record<string, unknown> }
): Promise<InboxItem> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/inbox/${id}/to-reminder`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data || {}),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

// ---- 提醒（第六阶段 M3）----
export async function listReminders(status?: string): Promise<Reminder[]> {
  const base = await ensureApiBase();
  const qs = status ? `?status=${status}` : "";
  const r = await fetch(`${base}/reminders${qs}`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function createReminder(data: ReminderCreate): Promise<Reminder> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/reminders`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function updateReminder(
  id: number,
  data: ReminderUpdate
): Promise<Reminder> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/reminders/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function snoozeReminder(
  id: number,
  data: { next_fire_at?: string; minutes?: number }
): Promise<Reminder> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/reminders/${id}/snooze`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function doneReminder(id: number): Promise<Reminder> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/reminders/${id}/done`, { method: "POST" });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function tickReminders(): Promise<{ fired: number }> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/reminders/tick`, { method: "POST" });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function deleteReminder(id: number): Promise<void> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/reminders/${id}`, { method: "DELETE" });
  if (!r.ok && r.status !== 204) throw new Error(`HTTP ${r.status}`);
}

// ---- 目标 / 简报 / 隐私维护（第六阶段 M4/M5/M6）----
export async function listGoals(opts?: {
  status?: string;
  domain?: string;
}): Promise<PersonalGoal[]> {
  const base = await ensureApiBase();
  const params = new URLSearchParams();
  if (opts?.status) params.set("status", opts.status);
  if (opts?.domain) params.set("domain", opts.domain);
  const qs = params.toString() ? `?${params}` : "";
  const r = await fetch(`${base}/goals${qs}`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function createGoal(data: GoalCreate): Promise<PersonalGoal> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/goals`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function getGoal(id: number): Promise<GoalDetail> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/goals/${id}`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function updateGoal(
  id: number,
  data: GoalUpdate
): Promise<PersonalGoal> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/goals/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function addGoalLink(
  goalId: number,
  data: { target_type: string; target_id: number; relation?: string }
): Promise<GoalLink> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/goals/${goalId}/links`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function addGoalCheckin(
  goalId: number,
  data: {
    checkin_date?: string;
    progress_note_md?: string;
    confidence?: number;
    blockers_json?: string[];
    next_actions_json?: string[];
  }
): Promise<GoalCheckin> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/goals/${goalId}/checkins`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function createGoalTaskDraft(
  goalId: number
): Promise<{ task_id: number }> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/goals/${goalId}/task-draft`, { method: "POST" });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function createGoalBriefing(goalId: number): Promise<Briefing> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/goals/${goalId}/briefing`, { method: "POST" });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function createTodayBriefing(): Promise<Briefing> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/today/briefing`, { method: "POST" });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function createWeeklyBriefing(): Promise<Briefing> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/briefings/weekly`, { method: "POST" });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function listBriefings(kind?: string): Promise<Briefing[]> {
  const base = await ensureApiBase();
  const qs = kind ? `?kind=${encodeURIComponent(kind)}` : "";
  const r = await fetch(`${base}/briefings${qs}`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function briefingToTask(id: number): Promise<{ task_id: number }> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/briefings/${id}/to-task`, { method: "POST" });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function privacyPreview(data: {
  purpose?: string;
  provider_type?: string;
  include_kb?: boolean;
  include_memories?: boolean;
  include_messages?: boolean;
  estimated_message_chars?: number;
}): Promise<PrivacyPreview> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/privacy/preview`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function listPrivacyAudits(
  remote?: boolean
): Promise<ProviderCallAudit[]> {
  const base = await ensureApiBase();
  const qs = remote === undefined ? "" : `?remote=${String(remote)}`;
  const r = await fetch(`${base}/privacy/audits${qs}`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function getMaintenanceHealthReport(): Promise<MaintenanceHealthReport> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/maintenance/health-report`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

// ---- 设置 ----
export interface AppSettings {
  llm_model: string;
  embed_model: string;
  llm_temperature: number;
  llm_context_length: number;
  kb_enabled_by_default: boolean;
  provider_type: "ollama" | "openai" | "claude";
  remote_provider_enabled: boolean;
  openai_api_key: string;
  openai_base_url: string;
  openai_model: string;
  claude_api_key: string;
  claude_model: string;
  reminders_enabled: boolean;
  reminder_tick_seconds: number;
  desktop_notifications_enabled: boolean;
}

export async function getSettings(): Promise<AppSettings> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/settings`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function updateSettings(
  data: Partial<AppSettings>
): Promise<AppSettings> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/settings`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}
