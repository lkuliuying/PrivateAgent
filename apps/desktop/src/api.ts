import { invoke, isTauri } from "@tauri-apps/api/core";
import type {
  AgentTask,
  Activity,
  BatchImportItem,
  ChatEvent,
  ChunkDetail,
  CodeFileContent,
  CompareResult,
  ContentSearchResponse,
  DocumentItem,
  ExportResult,
  GitDiff,
  GitStatus,
  GradeResult,
  LearningCard,
  LearningNode,
  LearningNote,
  LearningQuiz,
  LearningTopic,
  Message,
  NameSearchResponse,
  Project,
  ProjectFile,
  ProjectStats,
  ProjectTree,
  ScanResponse,
  SectionSummary,
  Session,
  SummarizeResult,
  ToolCall,
  ToolDefinition,
  ToolPlanResponse,
  TrustedPath,
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

export async function runAgentTask(id: number): Promise<AgentTask> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/agent-tasks/${id}/run`, { method: "POST" });
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

// ---- 设置 ----
export interface AppSettings {
  llm_model: string;
  embed_model: string;
  llm_temperature: number;
  llm_context_length: number;
  kb_enabled_by_default: boolean;
  openai_api_key: string;
  openai_base_url: string;
  claude_api_key: string;
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
