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
  memories?: MemorySource[];
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
  // 第四阶段 M0：间隔重复（ALTER ADDITIVE，不重排既有字段）
  due_at: string | null;
  interval_days: number;
  ease_factor: number;
  review_count: number;
  lapse_count: number;
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
  | "plan_draft"
  | "plan_approved"
  | "planned"
  | "waiting_approval"
  | "paused"
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

// ============ 第四阶段 M1：长期记忆 ============

export type MemoryKind =
  | 'preference'
  | 'learning'
  | 'project'
  | 'document'
  | 'workflow'
  | 'note';

export type MemoryStatus = 'draft' | 'confirmed' | 'archived';

export type MemoryEventType =
  | 'created'
  | 'used'
  | 'edited'
  | 'disabled'
  | 'deleted';

export interface MemoryItem {
  id: number;
  kind: MemoryKind;
  title: string;
  content_md: string;
  summary: string | null;
  source_type: string | null;
  source_id: number | null;
  project_id: number | null;
  topic_id: number | null;
  tags_json: string[] | null;
  confidence: number | null;
  enabled: boolean;
  sensitive: boolean;
  status: MemoryStatus;
  created_at: string;
  updated_at: string;
}

/** 聊天回答中「使用了哪些记忆」的来源条目。 */
export interface MemorySource {
  id: number;
  title: string;
  kind: MemoryKind;
  summary: string | null;
}

export interface MemoryEvent {
  id: number;
  memory_id: number;
  event_type: MemoryEventType;
  ref_type: string | null;
  ref_id: number | null;
  detail_json: Record<string, unknown> | null;
  created_at: string;
}

export interface MemoryCreate {
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
}

export interface MemoryUpdate {
  title?: string;
  content_md?: string;
  summary?: string;
  tags?: string[];
  confidence?: number;
  enabled?: boolean;
  sensitive?: boolean;
  status?: MemoryStatus;
}

export interface MemorySearchRequest {
  query?: string;
  kind?: MemoryKind;
  status?: MemoryStatus;
  enabled?: boolean;
  project_id?: number;
  topic_id?: number;
}

export interface MemoryCandidateRequest {
  source_type: 'agent_task' | 'chat_session' | 'learning_review';
  source_id: number;
}

// ============ 第四阶段 M0：学习复习（骨架） ============

export type ReviewRating = 'again' | 'hard' | 'good' | 'easy';

export interface LearningReview {
  id: number;
  card_id: number;
  topic_id: number;
  rating: ReviewRating;
  previous_due_at: string | null;
  next_due_at: string | null;
  created_at: string;
}

// ============ 第四阶段 M2：学习复习 2.0 ============

export interface ReviewResponse {
  card: LearningCard;
  review: LearningReview;
}

export interface LearningDashboard {
  topic_id: number;
  topic_title: string;
  total_cards: number;
  due_today: number;
  reviewed_cards: number;
  total_lapses: number;
  total_nodes: number;
  mastered_nodes: number;
  weak_nodes: number;
  reviews_7d: number;
  rating_counts_7d: Record<string, number>;
}

export interface WeakPoint {
  kind: 'node' | 'card';
  id: number;
  title: string;
  summary: string | null;
  mastery_level: string | null;
  lapse_count: number | null;
  due_at: string | null;
}

export interface WrongAnswer {
  attempt_id: number;
  quiz_id: number;
  question: string;
  reference_answer: string;
  explanation: string | null;
  user_answer: string | null;
  result: 'wrong' | 'partial';
  created_at: string | null;
}

export interface WeeklyReport {
  report_md: string;
  stats: {
    reviews_7d: number;
    rating_counts: Record<string, number>;
    wrong_count: number;
    weak_count: number;
  };
}

// ============ 第四阶段 M0：文档集合 / 抽取（骨架） ============

export type ExtractionKind =
  | 'terms'
  | 'table_summary'
  | 'actions'
  | 'claims'
  | 'code'
  | 'template_report';

export interface DocumentCollection {
  id: number;
  title: string;
  goal: string | null;
  tags_json: string[] | null;
  created_at: string;
  updated_at: string;
}

export interface DocumentCollectionItem {
  id: number;
  collection_id: number;
  doc_id: number;
  order_index: number;
}

export interface DocumentExtraction {
  id: number;
  doc_id: number | null;
  collection_id: number | null;
  kind: ExtractionKind;
  content_json: Record<string, unknown> | null;
  content_md: string | null;
  source_refs_json: unknown[] | null;
  created_at: string;
}

// ============ 第四阶段 M3：文档集合 / 抽取 / 模板报告 ============

export type DocExtractionKind =
  | 'terms'
  | 'table_summary'
  | 'actions'
  | 'claims'
  | 'code';

export type TemplateKind =
  | 'study_note'
  | 'tech_summary'
  | 'paper_reading'
  | 'project_materials'
  | 'meeting_minutes';

export interface CollectionDetailItem {
  id: number;
  collection_id: number;
  doc_id: number;
  doc_name: string | null;
  doc_status: string | null;
  order_index: number;
}

export interface CollectionDetail extends DocumentCollection {
  items: CollectionDetailItem[];
}

export interface ExtractRequest {
  kind: DocExtractionKind;
}

export interface TemplateReportRequest {
  template: TemplateKind;
  doc_ids?: number[];
  collection_id?: number;
}

export interface TemplateReportResponse {
  report_md: string;
  extraction: DocumentExtraction;
}

export interface OcrResult {
  doc_id: number;
  status: string;
  message: string;
}

// ============ 第四阶段 M0：Patch set / 命令配置 / Provider / 备份（骨架） ============

export type PatchSetStatus =
  | 'draft'
  | 'waiting_approval'
  | 'applied'
  | 'rejected'
  | 'rolled_back';

export type PatchFileStatus =
  | 'draft'
  | 'applied'
  | 'rejected'
  | 'rolled_back';

export type CommandProfileKind =
  | 'test'
  | 'build'
  | 'lint'
  | 'format'
  | 'typecheck'
  | 'custom';

export type ProviderType = 'ollama' | 'openai' | 'claude';

export interface ProjectCommandProfile {
  id: number;
  project_id: number;
  name: string;
  command_json: Record<string, unknown>;
  kind: CommandProfileKind;
  timeout_seconds: number;
  enabled: boolean;
  created_at: string;
}

export interface PatchFile {
  id: number;
  patch_set_id: number;
  rel_path: string;
  old_sha256: string | null;
  new_sha256: string | null;
  diff_text: string;
  status: PatchFileStatus;
}

export interface PatchSet {
  id: number;
  project_id: number;
  task_id: number | null;
  title: string;
  status: PatchSetStatus;
  created_at: string;
  updated_at: string;
  files: PatchFile[];
}

// ============ 第四阶段 M4：编码工作流 ============

export interface PatchFileCreate {
  rel_path: string;
  new_content: string;
  create?: boolean;
}

export interface PatchSetCreate {
  title: string;
  files: PatchFileCreate[];
  task_id?: number;
}

export interface ApplyResult {
  patch_set_id: number;
  status: string;
  written?: Array<{ rel_path: string; size_bytes?: number }>;
  restored?: Array<{ rel_path: string; action: string }>;
}

export interface CommandProfileCreate {
  name: string;
  command_json: Record<string, unknown>;
  kind: CommandProfileKind;
  timeout_seconds?: number;
  enabled?: boolean;
}

export interface CommandProfileUpdate {
  name?: string;
  command_json?: Record<string, unknown>;
  kind?: CommandProfileKind;
  timeout_seconds?: number;
  enabled?: boolean;
}

export interface RunResult {
  project_id: number;
  profile_id: number;
  profile_name: string;
  args: string[];
  cwd: string;
  returncode: number;
  stdout: string;
  stderr: string;
  output: string;
  truncated: boolean;
  succeeded: boolean;
}

export interface DiagnoseRequest {
  output: string;
  returncode: number;
  args?: string[];
}

export interface ErrorFileOut {
  file: string;
  line: number;
  message: string;
}

export interface DiagnoseResult {
  summary: string;
  error_files: ErrorFileOut[];
  suggestion: string;
}

export interface ProviderInfo {
  type: ProviderType;
  enabled: boolean;
  remote: boolean;
  configured?: boolean;
}

export interface ProviderConfig {
  provider_type: ProviderType;
  remote_provider_enabled: boolean;
  ollama: { model: string; embed_model: string };
  openai: { base_url: string; model: string; configured: boolean };
  claude: { model: string; configured: boolean };
}

export interface ProviderPrivacy {
  provider_type: ProviderType;
  remote_provider_enabled: boolean;
  sends: string[];
}

export interface ProviderStatus {
  config: ProviderConfig;
  privacy: ProviderPrivacy;
  items: ProviderInfo[];
}

export interface BackupExportResult {
  path: string;
  size_bytes: number;
  created_at: string;
  tables?: Record<string, number>;
}

export interface BackupRestorePreview {
  path: string;
  created_at: string;
  tables: Record<string, number>;
  will_restore: string[];
  preview_only: string[];
  note: string;
}
