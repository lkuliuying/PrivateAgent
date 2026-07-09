import { invoke, isTauri } from "@tauri-apps/api/core";
import type {
  AgentTask,
  Activity,
  BackupExportResult,
  BatchImportItem,
  ChatEvent,
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
  Message,
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
  Session,
  SummarizeResult,
  ToolCall,
  ToolDefinition,
  ToolPlanResponse,
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
  AppNotification,
  AppNotificationCreate,
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

let API_BASE: string | null = null;

/**
 * 获取后端 API base：
 * - Tauri 打包模式：用 Rust sidecar 协商的端口（get_api_port 命令）。
 * - 开发模式 / 浏览器：回退到 http://127.0.0.1:8000（手动启动的后端）。
 * 结果缓存，后续调用直接返回。
 */
export async function ensureApiBase(): Promise<string> {
  if (API_BASE) return API_BASE;
  if (isTauri()) {
    try {
      const port = await invoke<number | null>("get_api_port");
      if (port) {
        API_BASE = `http://127.0.0.1:${port}`;
        return API_BASE;
      }
    } catch {
      // 命令失败，回退默认端口
    }
  }
  API_BASE = "http://127.0.0.1:8000";
  return API_BASE;
}

/** 直接指定后端端口（start_sidecar 返回端口后用，绕过缓存）。 */
export function setApiBase(port: number): void {
  API_BASE = `http://127.0.0.1:${port}`;
}

/** 回退到默认手动后端 127.0.0.1:8000（dev 模式）。 */
export function setApiBaseDefault(): void {
  API_BASE = "http://127.0.0.1:8000";
}

/** 清除缓存的 base，下次 ensureApiBase 重新解析。 */
export function resetApiBase(): void {
  API_BASE = null;
}

export async function getHealth(): Promise<Record<string, unknown>> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/health`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function listSessions(): Promise<Session[]> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/sessions`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function createSession(): Promise<Session> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/sessions`, { method: "POST" });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function getMessages(sessionId: number): Promise<Message[]> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/sessions/${sessionId}/messages`);
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

export async function planTools(
  sessionId: number,
  message: string
): Promise<ToolPlanResponse> {
  const base = await ensureApiBase();
  // 30s 超时：Ollama 连接但卡住时避免无限挂起（App.vue 的 .catch 会降级为普通回复）
  const controller = new AbortController();
  const t = setTimeout(() => controller.abort(), 30000);
  try {
    const r = await fetch(`${base}/tools/plan`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, message }),
      signal: controller.signal,
    });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return r.json();
  } finally {
    clearTimeout(t);
  }
}

export async function approveToolCall(id: number): Promise<ToolCall> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/tool-calls/${id}/approve`, { method: "POST" });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function rejectToolCall(id: number): Promise<ToolCall> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/tool-calls/${id}/reject`, { method: "POST" });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function listToolCalls(
  sessionId?: number
): Promise<ToolCall[]> {
  const base = await ensureApiBase();
  const qs = sessionId ? `?session_id=${sessionId}` : "";
  const r = await fetch(`${base}/tool-calls${qs}`);
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

/** Tauri 目录选择器；浏览器/dev 模式返回 null（调用方回退文本输入）。 */
export async function pickDirectory(): Promise<string | null> {
  if (!isTauri()) return null;
  try {
    const { open } = await import("@tauri-apps/plugin-dialog");
    const selected = await open({ directory: true, multiple: false });
    return typeof selected === "string" ? selected : null;
  } catch {
    return null;
  }
}

/** Tauri 文件选择器（单个文件，可带扩展名过滤）；浏览器/dev 模式返回 null。 */
export async function pickFile(
  filters?: { name: string; extensions: string[] }[]
): Promise<string | null> {
  if (!isTauri()) return null;
  try {
    const { open } = await import("@tauri-apps/plugin-dialog");
    const selected = await open({ multiple: false, filters });
    return typeof selected === "string" ? selected : null;
  } catch {
    return null;
  }
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

/**
 * SSE 流式对话。fetch + ReadableStream 解析。返回 AbortController 用于停止生成。
 */
export function streamChat(
  sessionId: number,
  message: string,
  knowledgeBase: boolean,
  onEvent: (e: ChatEvent) => void,
  onError: (err: string) => void,
  onClose?: () => void,
  toolResult?: { tool_name: string; output: Record<string, unknown> }
): AbortController {
  const controller = new AbortController();

  ensureApiBase()
    .then((base) =>
      fetch(`${base}/chat/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sessionId,
          message,
          knowledge_base: knowledgeBase,
          ...(toolResult ? { tool_result: toolResult } : {}),
        }),
        signal: controller.signal,
      }).then(async (resp) => {
        if (!resp.ok || !resp.body) {
          onError(`HTTP ${resp.status}`);
          return;
        }
        const reader = resp.body.getReader();
        const decoder = new TextDecoder("utf-8");
        let buffer = "";
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          let idx: number;
          while ((idx = buffer.indexOf("\n\n")) >= 0) {
            const raw = buffer.slice(0, idx);
            buffer = buffer.slice(idx + 2);
            const line = raw.split("\n").find((l) => l.startsWith("data:"));
            if (!line) continue;
            try {
              onEvent(JSON.parse(line.slice(5).trim()));
            } catch {
              // 忽略解析失败的事件
            }
          }
        }
        onClose?.();
      })
    )
    .catch((e) => {
      if (e?.name === "AbortError") {
        onClose?.();
      } else {
        onError(String(e));
      }
    });

  return controller;
}

// ============ 引导 / 配置 / sidecar / 更新（第五阶段） ============
// 这些命令只在 Tauri 打包/桌面环境可用；浏览器开发模式 invoke 会抛错，调用方需 try/catch。

/** 连接配置（对应 Rust ConfigData，字段与 .env 的 PA_ 项对齐）。 */
export interface ConfigData {
  db_host: string;
  db_port: number;
  db_user: string;
  db_password: string;
  db_name: string;
  ollama_base_url: string;
  llm_model: string;
  embed_model: string;
}

export interface DepResult {
  mysql_reachable: boolean;
  ollama_reachable: boolean;
}

export interface ConnResult {
  mysql_ok: boolean;
  mysql_error: string | null;
  ollama_ok: boolean;
  ollama_error: string | null;
  ollama_models: string[];
  llm_model_available: boolean;
  embed_model_available: boolean;
}

export interface SidecarStartResult {
  ok: boolean;
  dev_mode: boolean;
  port: number | null;
  error: string | null;
}

export interface UpdateInfo {
  version: string;
  date: string | null;
  body: string | null;
}

/** 是否已存在连接配置（%APPDATA%/personal-assistant/.env）。 */
export async function cmdConfigExists(): Promise<boolean> {
  return invoke<boolean>("config_exists");
}

/** 读取配置；不存在时返回默认值。 */
export async function cmdReadConfig(): Promise<ConfigData> {
  return invoke<ConfigData>("read_config");
}

/** 写入配置（生成 .env）。 */
export async function cmdWriteConfig(cfg: ConfigData): Promise<void> {
  return invoke<void>("write_config", { cfg });
}

/** 默认端口探测 MySQL/Ollama 是否在跑（向导首屏环境提示）。 */
export async function cmdCheckDependencies(): Promise<DepResult> {
  return invoke<DepResult>("check_dependencies");
}

/** 按配置测试 MySQL + Ollama 连接，并校验模型是否已拉取。 */
export async function cmdTestConnections(cfg: ConfigData): Promise<ConnResult> {
  return invoke<ConnResult>("test_connections", { cfg });
}

/** 启动 sidecar；dev 模式返回 dev_mode=true。 */
export async function cmdStartSidecar(): Promise<SidecarStartResult> {
  return invoke<SidecarStartResult>("start_sidecar");
}

/** 检查更新；无更新返回 null。 */
export async function cmdCheckForUpdates(): Promise<UpdateInfo | null> {
  return invoke<UpdateInfo | null>("check_for_updates");
}

/** 下载并安装更新（安装后需 relaunch）。 */
export async function cmdDownloadAndInstallUpdate(): Promise<void> {
  return invoke<void>("download_and_install_update");
}

/** 重启应用以应用更新。 */
export async function cmdRelaunchApp(): Promise<void> {
  return invoke<void>("relaunch_app");
}

// ---- 通知中心（第七阶段 M4）----
export async function listNotifications(
  opts?: { status?: string; kind?: string; limit?: number }
): Promise<AppNotification[]> {
  const base = await ensureApiBase();
  const qs = new URLSearchParams();
  if (opts?.status) qs.set("status", opts.status);
  if (opts?.kind) qs.set("kind", opts.kind);
  if (opts?.limit) qs.set("limit", String(opts.limit));
  const q = qs.toString();
  const r = await fetch(`${base}/notifications${q ? `?${q}` : ""}`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function createNotification(
  body: AppNotificationCreate
): Promise<AppNotification> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/notifications`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function patchNotification(
  id: number,
  status: "read" | "archived"
): Promise<AppNotification> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/notifications/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status }),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function readAllNotifications(): Promise<{ marked: number }> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/notifications/read-all`, { method: "POST" });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

// ---- 全局搜索 / 命令面板（第七阶段 M2）----
export interface SearchResult {
  type: string;
  id: number;
  title: string;
  snippet: string | null;
  source: string;
  updated_at: string | null;
  action: string;
  meta: Record<string, unknown> | null;
}

export async function search(
  q: string,
  opts?: { types?: string[]; limit?: number }
): Promise<SearchResult[]> {
  const base = await ensureApiBase();
  const qs = new URLSearchParams({ q });
  if (opts?.types?.length) qs.set("types", opts.types.join(","));
  if (opts?.limit) qs.set("limit", String(opts.limit));
  const r = await fetch(`${base}/search?${qs}`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function recordRecentOpen(
  objectType: string,
  objectId: number,
  title?: string
): Promise<void> {
  const base = await ensureApiBase();
  await fetch(`${base}/search/recent`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ object_type: objectType, object_id: objectId, title }),
  });
}

// ---- 快速捕获（第七阶段 M3）----
export interface CaptureItem {
  id: number;
  title: string | null;
  content_md: string;
  source: string;
  candidate_type: string | null;
  status: string;
  target_type: string | null;
  target_id: number | null;
  created_at: string;
  handled_at: string | null;
}

export async function listCapture(opts?: { status?: string }): Promise<CaptureItem[]> {
  const base = await ensureApiBase();
  const qs = new URLSearchParams();
  if (opts?.status) qs.set("status", opts.status);
  const q = qs.toString();
  const r = await fetch(`${base}/capture${q ? `?${q}` : ""}`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function createCapture(body: {
  content_md: string;
  source?: string;
  title?: string;
  candidate_type?: string;
}): Promise<CaptureItem> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/capture`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function captureToInbox(id: number, itemType = "note"): Promise<void> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/capture/${id}/to-inbox`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ item_type: itemType }),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
}

export async function captureToReminder(id: number, dueAt?: string): Promise<void> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/capture/${id}/to-reminder`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ due_at: dueAt }),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
}

export async function captureToMemory(id: number, kind = "note"): Promise<void> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/capture/${id}/to-memory`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ kind }),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
}

// ---- OCR 队列（第七阶段 M3）----
export interface OcrAvailability {
  available: boolean;
  reason: string;
  engine: string | null;
}
export interface OcrJob {
  id: number;
  doc_id: number | null;
  file_path: string | null;
  source: string;
  status: string;
  engine: string | null;
  output_text: string | null;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export async function getOcrAvailability(): Promise<OcrAvailability> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/ocr/availability`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function listOcrJobs(opts?: { status?: string }): Promise<OcrJob[]> {
  const base = await ensureApiBase();
  const qs = new URLSearchParams();
  if (opts?.status) qs.set("status", opts.status);
  const q = qs.toString();
  const r = await fetch(`${base}/ocr-jobs${q ? `?${q}` : ""}`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function retryOcrJob(id: number): Promise<OcrJob> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/ocr-jobs/${id}/retry`, { method: "POST" });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

// ---- 诊断中心（第七阶段 M5）----
export interface DiagnosticsSnapshot {
  generated_at: string;
  version: string;
  migration_head: string | null;
  health: Record<string, unknown>;
  backup: { last_backup_at: string | null; count: number };
  failed_activities: Array<Record<string, unknown>>;
  provider_failures: Array<Record<string, unknown>>;
  reminder_tick: Record<string, unknown>;
  import_queue: Record<string, number>;
  integrity_summary: Record<string, number>;
  recent_errors: string[];
  settings_redacted: Record<string, string>;
  db_url_redacted: string;
}

export async function getDiagnostics(): Promise<DiagnosticsSnapshot> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/diagnostics`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function exportDiagnostics(
  outputDir?: string
): Promise<{ path: string; run_id: number; size_bytes: number }> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/diagnostics/export`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ output_dir: outputDir ?? null }),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

// ---- 数据完整性体检（第七阶段 M7）----
export interface IntegrityFinding {
  id: number;
  check_name: string;
  severity: string;
  ref_type: string | null;
  ref_id: number | null;
  detail_json: Record<string, unknown> | null;
  suggested_action: string | null;
  status: string;
  created_at: string;
  updated_at: string;
}
export interface RepairPlanItem {
  finding_id: number;
  check_name: string;
  severity: string;
  ref_type: string | null;
  ref_id: number | null;
  suggested_action: string | null;
  detail: Record<string, unknown> | null;
  impact: string;
  destructive: boolean;
}

export async function listIntegrity(status?: string): Promise<IntegrityFinding[]> {
  const base = await ensureApiBase();
  const qs = status ? `?status=${status}` : "";
  const r = await fetch(`${base}/maintenance/integrity${qs}`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function runIntegrity(): Promise<IntegrityFinding[]> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/maintenance/integrity/run`, { method: "POST" });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function repairPlan(): Promise<RepairPlanItem[]> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/maintenance/repair-plan`, { method: "POST" });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function applyRepair(
  findingId: number
): Promise<Record<string, unknown>> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/maintenance/repair-plan/${findingId}/apply`, {
    method: "POST",
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

// ---- 扩展注册表（第八阶段 M7）----
export interface ExtensionDescriptor {
  id: string;
  title: string;
  kind: string;
  description: string;
  risk_level: string;
  permissions: string[];
  input_schema: Record<string, unknown> | null;
  output_summary: string | null;
  ui_entry: Record<string, unknown> | null;
  enabled: boolean;
  configurable: boolean;
}

export async function listExtensions(kind?: string): Promise<ExtensionDescriptor[]> {
  const base = await ensureApiBase();
  const qs = kind ? `?kind=${encodeURIComponent(kind)}` : "";
  const r = await fetch(`${base}/extensions${qs}`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function patchExtension(
  extId: string,
  enabled: boolean
): Promise<ExtensionDescriptor> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/extensions/${encodeURIComponent(extId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled }),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

// ---- 本地集成（第八阶段 M8）----
export interface IntegrationSource {
  id: number;
  kind: string;
  title: string;
  config_json: Record<string, unknown> | null;
  enabled: boolean;
  last_run_at: string | null;
  last_status: string | null;
}
export interface IntegrationImport {
  id: number;
  source_id: number | null;
  source_kind: string;
  summary_json: Record<string, unknown> | null;
  target_type: string | null;
  target_id: number | null;
  reversible: boolean;
  reversal_info_json: Record<string, unknown> | null;
  status: string;
  error_message: string | null;
  created_at: string;
  reverted_at: string | null;
}
export interface IntegrationPreview {
  file_path: string;
  event_count: number;
  sample_titles: string[];
  events: Array<Record<string, unknown>>;
  target: string;
}

export async function listIntegrationSources(): Promise<IntegrationSource[]> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/integrations/sources`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function createIntegrationSource(data: {
  kind?: string;
  title: string;
  file_path: string;
  target?: string;
}): Promise<IntegrationSource> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/integrations/sources`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function previewIntegration(
  sourceId: number
): Promise<IntegrationPreview> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/integrations/preview`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source_id: sourceId }),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function runIntegrationImport(
  sourceId: number,
  target?: string
): Promise<IntegrationImport> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/integrations/import`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source_id: sourceId, target }),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function listIntegrationImports(): Promise<IntegrationImport[]> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/integrations/imports`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function revertIntegrationImport(importId: number): Promise<IntegrationImport> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/integrations/imports/${importId}`, {
    method: "DELETE",
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

// ---- 备份恢复演练 / 迁移 runbook（第八阶段 M9）----
export async function restoreDrillBackup(
  path: string
): Promise<Record<string, unknown>> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/backup/restore/drill`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path }),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function getMigrationRunbook(): Promise<Record<string, string>> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/backup/migration-runbook`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  const d = await r.json();
  return d.runbook as Record<string, string>;
}

// ---- 测试 / 发布运行摘要（第八阶段 M3）----
export async function listTestRuns(
  kind?: string
): Promise<Array<Record<string, unknown>>> {
  const base = await ensureApiBase();
  const qs = kind ? `?kind=${encodeURIComponent(kind)}` : "";
  const r = await fetch(`${base}/testing/runs${qs}`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function listUpgradeSmokeRuns(): Promise<
  Array<Record<string, unknown>>
> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/testing/upgrade-smoke-runs`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}
