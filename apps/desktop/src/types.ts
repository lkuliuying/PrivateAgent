export interface Session {
  id: number;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface Message {
  id: number;
  session_id: number;
  role: "user" | "assistant" | "system";
  content: string;
  created_at: string;
}

/** RAG 引用来源。 */
export interface Source {
  doc_name: string;
  ordinal: number;
  chunk_id: number;
  heading?: string | null;
  score?: number | null;
  matched_via?: string[];
  matched_keywords?: string[];
}

export interface ChatEvent {
  type: "token" | "done" | "title" | "error";
  content?: string;
  message_id?: number;
  title?: string;
  message?: string;
  sources?: Source[];
}

export type DocStatus = "pending" | "processing" | "ready" | "failed" | "deleting";

export interface DocumentItem {
  id: number;
  name: string;
  mime_type: string | null;
  size_bytes: number | null;
  content_hash: string | null;
  embedding_model: string | null;
  chunk_count: number;
  status: DocStatus;
  enabled: boolean;
  error_message: string | null;
  last_error_at: string | null;
  indexed_at: string | null;
  // 第三阶段 M2：元数据
  doc_type: string | null;
  topic: string | null;
  tags_json: string[] | null;
  language: string | null;
  project_id: number | null;
  created_at: string;
  updated_at: string;
}

// ============ 第二阶段：工具调用 / 授权路径 ============

export type RiskLevel = "safe" | "confirm" | "restricted";

export type ToolCallStatus =
  | "pending_approval"
  | "approved"
  | "rejected"
  | "running"
  | "succeeded"
  | "failed"
  | "cancelled";

export interface ToolDefinition {
  name: string;
  description: string;
  risk_level: RiskLevel;
  input_schema: Record<string, unknown>;
  output_schema: Record<string, unknown>;
}

export interface ToolCall {
  id: number;
  session_id: number | null;
  task_id: number | null;
  step_id: number | null;
  tool_name: string;
  risk_level: RiskLevel;
  status: ToolCallStatus;
  input_json: Record<string, unknown> | null;
  output_json: Record<string, unknown> | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface ToolPlanResponse {
  tool_call: ToolCall | null;
}

export interface TrustedPath {
  id: number;
  path: string;
  kind: "file" | "directory";
  granted_at: string;
}

// ============ 第二阶段 M3/M4：知识库增强 / 活动流 / 文件 ============

export interface ChunkDetail {
  id: number;
  doc_id: number;
  ordinal: number;
  content: string;
  token_count: number | null;
  created_at: string;
}

export interface BatchImportItem {
  name: string;
  status: "imported" | "duplicate" | "error";
  doc_id: number | null;
  error: string | null;
}

export type ActivityKind = "tool" | "document_import" | "reindex" | "system";
export type ActivityStatus =
  | "pending"
  | "waiting_approval"
  | "running"
  | "succeeded"
  | "failed"
  | "cancelled";

export interface Activity {
  id: number;
  session_id: number | null;
  kind: ActivityKind;
  title: string;
  status: ActivityStatus;
  ref_type: string | null;
  ref_id: number | null;
  detail_json: Record<string, unknown> | null;
  error_message: string | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ScanFile {
  path: string;
  name: string;
  size_bytes: number;
}

export interface ScanResponse {
  path: string;
  files: ScanFile[];
  count: number;
  truncated: boolean;
}

export interface SummarizeResult {
  summary: string;
  name: string;
  path: string;
  size_bytes: number;
  truncated: boolean;
}

// ============ 第三阶段 M0：项目 / 学习（骨架） ============

export interface Project {
  id: number;
  name: string;
  root_path: string;
  language: string | null;
  framework: string | null;
  status: "active" | "archived";
  last_scanned_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface LearningTopic {
  id: number;
  title: string;
  goal: string | null;
  level: string | null;
  status: "active" | "paused" | "completed" | "archived";
  tags_json: string[] | null;
  created_at: string;
  updated_at: string;
}

// ============ 第三阶段 M3：学习系统 ============

export interface LearningNode {
  id: number;
  topic_id: number;
  parent_id: number | null;
  title: string;
  summary: string | null;
  mastery_level: string | null;
  order_index: number;
}

export interface LearningNote {
  id: number;
  topic_id: number | null;
  title: string;
  body_md: string;
  source_refs_json: unknown[] | null;
  created_at: string;
  updated_at: string;
}

export interface LearningQuiz {
  id: number;
  topic_id: number;
  node_id: number | null;
  question: string;
  answer: string;
  explanation: string | null;
  created_at: string;
}

export interface LearningAttempt {
  id: number;
  quiz_id: number;
  user_answer: string | null;
  result: "correct" | "partial" | "wrong";
  created_at: string;
}

export interface GradeResult {
  result: "correct" | "partial" | "wrong";
  explanation: string;
  attempt: LearningAttempt | null;
}

export interface LearningCard {
  id: number;
  topic_id: number;
  node_id: number | null;
  front: string;
  back: string;
  created_at: string;
}

// ============ 第三阶段 M1：项目工作区 ============

export interface ProjectFile {
  id: number;
  rel_path: string;
  language: string | null;
  size_bytes: number | null;
  is_binary: boolean;
}

export interface TreeFile {
  name: string;
  path: string;
  language: string | null;
  size_bytes: number | null;
  is_binary: boolean;
}

export interface TreeNode {
  name: string;
  path: string;
  dirs: TreeNode[];
  files: TreeFile[];
}

export interface ProjectTree {
  dirs: TreeNode[];
  files: TreeFile[];
}

export interface NameSearchResult {
  rel_path: string;
  name: string;
  language: string | null;
  size_bytes: number | null;
}

export interface ContentSearchResult {
  rel_path: string;
  line: number;
  context: string;
  language: string | null;
}

export interface NameSearchResponse {
  results: NameSearchResult[];
  count: number;
}

export interface ContentSearchResponse {
  results: ContentSearchResult[];
  count: number;
  truncated: boolean;
}

export interface CodeFileContent {
  path: string;
  abs_path?: string;
  content: string;
  language: string | null;
  start_line: number;
  line_count: number;
  size_bytes: number;
  truncated: boolean;
}

export interface GitChangedFile {
  status: string;
  path: string;
}

export interface GitStatus {
  branch: string | null;
  upstream: string | null;
  ahead: number | null;
  behind: number | null;
  clean: boolean;
  changed: GitChangedFile[];
}

export interface GitDiff {
  stat: string;
  diff: string;
  truncated: boolean;
}

export interface ProjectStats {
  total: number;
  binary: number;
  by_language: Record<string, number>;
}

// ============ 第三阶段 M6：多步任务 ============

export type AgentTaskStatus =
  | "planned"
  | "waiting_approval"
  | "running"
  | "succeeded"
  | "failed"
  | "cancelled";

export type AgentStepStatus =
  | "planned"
  | "waiting_approval"
  | "running"
  | "succeeded"
  | "failed"
  | "skipped"
  | "cancelled";

export interface AgentTaskStep {
  id: number;
  task_id: number;
  ordinal: number;
  title: string;
  tool_name: string | null;
  status: AgentStepStatus;
  tool_call_id: number | null;
  input_json: Record<string, unknown> | null;
  output_json: Record<string, unknown> | null;
  error_message: string | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
}

export interface AgentEvidence {
  id: number;
  task_id: number;
  step_id: number | null;
  kind: "tool_output" | "error" | "note" | "report";
  title: string;
  content_md: string;
  meta_json: Record<string, unknown> | null;
  created_at: string;
}

export interface AgentTask {
  id: number;
  session_id: number | null;
  title: string;
  goal: string | null;
  status: AgentTaskStatus;
  plan_json: Record<string, unknown> | null;
  final_report_md: string | null;
  created_at: string;
  updated_at: string;
  steps: AgentTaskStep[];
  evidence: AgentEvidence[];
}

// ============ 第三阶段 M4：文档工作台 ============

export interface SectionSummary {
  heading: string;
  summary: string;
}

export interface GlossaryTerm {
  term: string;
  definition: string;
}

export interface CompareDifference {
  doc: string;
  point: string;
}

export interface CompareResult {
  doc_names: string[];
  common: string[];
  differences: CompareDifference[];
  conflicts: string[];
  reading_order: string[];
}

export interface ExportResult {
  path: string;
  size_bytes: number;
}
