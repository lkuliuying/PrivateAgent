// ============ 第七阶段：可信赖的日常操作层 ============

/**
 * 工作台视图名。第七阶段从 App.vue/NavRail.vue/TodayView.vue 三处重复定义
 * 提取到此处统一维护，新增视图只改这一处。diagnostics 为第七阶段 M5 诊断中心。
 */
export type View =
  | "chat"
  | "today"
  | "kb"
  | "projects"
  | "learning"
  | "tasks"
  | "memory"
  | "settings"
  | "diagnostics"
  | "extensions"
  | "integrations"
  | "backup";

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

/** Agent 工作台步骤状态。与后端工具/活动状态解耦，由前端适配层统一映射。 */
export type WorkspaceStepStatus =
  | "pending"
  | "running"
  | "completed"
  | "blocked"
  | "failed";

export interface WorkspacePlanStep {
  id: string;
  title: string;
  detail: string;
  status: WorkspaceStepStatus;
}

export type AgentTaskState =
  | "idle"
  | "running"
  | "waiting"
  | "completed"
  | "failed"
  | "stopped";

export type AgentActivityKind =
  | "user"
  | "agent"
  | "tool"
  | "change"
  | "approval"
  | "result"
  | "system";

export type AgentArtifactType = "document" | "image" | "code" | "report";

/** RAG 引用来源。 */
export interface Source {
  doc_name: string;
  ordinal: number;
  chunk_id: number;
  heading?: string | null;
  score?: number | null;
  fusion_score?: number | null;
  bm25_score?: number | null;
  rerank_score?: number | null;
  matched_via?: string[];
  matched_keywords?: string[];
}

export interface ChatEvent {
  type: "run" | "token" | "done" | "title" | "error" | "approval";
  run_id?: string;
  content?: string;
  message_id?: number;
  title?: string;
  message?: string;
  sources?: Source[];
  memories?: MemorySource[];
  approval?: AgentRunApproval;
}

export interface AgentRunApproval {
  id: string;
  run_id: string;
  tool_call_id: string;
  tool_name: string;
  tool_version: string;
  arguments_sha256: string;
  risk_level: string;
  required_capabilities: string[];
  status: "pending" | "approved" | "rejected" | "consumed" | "expired" | "cancelled";
  expires_at: string;
  created_at: string;
}

/** v0.5.0 B1：审批时的文件变更预览（只读 DTO；previewable=false 时仅 reason）。 */
export interface AgentApprovalPreview {
  tool_name: string;
  previewable: boolean;
  rel_path: string | null;
  creates_file: boolean | null;
  old_sha256: string | null;
  new_sha256: string | null;
  diff: string | null;
  truncated: boolean | null;
  reason: string | null;
}

/** v0.5.0 B1：已脱敏/限长并持久化的工具执行结果（UI 展示用）。 */
export interface AgentToolExecution {
  id: string;
  tool_name: string;
  tool_version: string;
  status: string;
  error_code: string | null;
  error_message: string | null;
  output: Record<string, unknown> | null;
  created_at: string;
  completed_at: string | null;
}

/** v0.5.0 B2：流式输出行（已脱敏、单行有界；按 seq 续读）。 */
export interface AgentToolOutputLine {
  seq: number;
  kind: string;
  text: string;
}

export interface AgentToolOutputPage {
  lines: AgentToolOutputLine[];
  last_seq: number;
  finished: boolean;
}

/** v0.5.0 B3：HTTP endpoint profile（非敏感元数据 + keyring secret 引用）。 */
export interface HttpEndpointProfile {
  id: number;
  name: string;
  scheme: string;
  host: string;
  port: number;
  path_prefix: string;
  allowed_methods: string[];
  max_request_bytes: number;
  max_response_bytes: number;
  timeout_ms: number;
  headers: Record<string, string>;
  /** 需要密钥的请求头名（仅声明；keyring 引用见 secret_refs） */
  secret_slots: string[];
  /** 后端生成的 keyring 引用（header → secret://os-keyring/...） */
  secret_refs: Record<string, string>;
  allow_insecure_local: boolean;
  allow_private_network: boolean;
  enabled: boolean;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface HttpProfileDeleteResult {
  secret_refs: Record<string, string>;
}

export interface SqlProfileDeleteResult {
  password_secret_ref: string | null;
}

/** v0.5.0 B4：只读 SQL 连接 profile（非敏感元数据 + keyring 密码引用）。 */
export interface SqlReadonlyProfile {
  id: number;
  name: string;
  dialect: string;
  host: string;
  port: number;
  database: string;
  username: string | null;
  password_secret_ref: string;
  max_rows: number;
  max_bytes: number;
  timeout_ms: number;
  enabled: boolean;
  version: number;
  created_at: string;
  updated_at: string;
}

export type DocStatus =
  | "pending"
  | "processing"
  | "ready"
  | "failed"
  | "deleting"
  | "needs_ocr";

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

export type ActivityKind =
  | "tool"
  | "document_import"
  | "reindex"
  | "system"
  | "ocr";
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
  available?: boolean;
  storage?: "none" | "legacy" | "os_keyring";
}

export interface ProviderConfig {
  provider_type: ProviderType;
  remote_provider_enabled: boolean;
  ollama: { model: string; embed_model: string };
  openai: {
    base_url: string;
    model: string;
    configured: boolean;
    available: boolean;
    storage: "none" | "legacy" | "os_keyring";
  };
  claude: {
    model: string;
    configured: boolean;
    available: boolean;
    storage: "none" | "legacy" | "os_keyring";
  };
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

// ============ 第六阶段 M1/M2：今日中枢 / 收件箱 ============

export type InboxItemType =
  | 'todo'
  | 'reminder'
  | 'review'
  | 'approval'
  | 'failure'
  | 'memory'
  | 'note'
  | 'system';

export type InboxStatus = 'open' | 'snoozed' | 'done' | 'ignored' | 'archived';
export type InboxPriority = 'low' | 'normal' | 'high' | 'urgent';

export interface InboxItem {
  id: number;
  title: string;
  body_md: string | null;
  item_type: InboxItemType;
  status: InboxStatus;
  priority: InboxPriority;
  due_at: string | null;
  source_type: string | null;
  source_id: number | null;
  target_type: string | null;
  target_id: number | null;
  meta_json: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
  handled_at: string | null;
}

export interface InboxCreate {
  title: string;
  item_type: InboxItemType;
  body_md?: string;
  priority?: InboxPriority;
  due_at?: string;
  source_type?: string;
  source_id?: number;
}

export interface InboxUpdate {
  title?: string;
  body_md?: string;
  status?: InboxStatus;
  priority?: InboxPriority;
  due_at?: string | null;
}

/** 今日快照中的卡片项：各来源共用一个宽松结构（仅展示与跳转来源所需字段）。 */
export interface TodayItem {
  id: number;
  title?: string;
  front?: string;
  status?: string;
  item_type?: string;
  priority?: string;
  kind?: string;
  due_at?: string | null;
  next_fire_at?: string | null;
  recurring?: boolean;
  topic_id?: number;
  ref_type?: string | null;
  ref_id?: number | null;
  error_message?: string | null;
  summary?: string | null;
  source_type: string;
  source_id: number;
  origin_source_type?: string | null;
  origin_source_id?: number | null;
}

export interface TodaySummary {
  due_cards: number;
  attention_tasks: number;
  failed_activities: number;
  draft_memories: number;
  due_reminders: number;
  open_inbox: number;
  last_backup_at: string | null;
}

export interface TodaySnapshot {
  generated_at: string;
  summary: TodaySummary;
  due_cards: TodayItem[];
  attention_tasks: TodayItem[];
  failed_activities: TodayItem[];
  draft_memories: TodayItem[];
  due_reminders: TodayItem[];
  open_inbox: TodayItem[];
  backup: { last_backup_at: string | null; count: number };
  // 第七阶段 M1：最近来源（真实数据，替代静态演示）。
  recent_checkins: TodayRecentItem[];
  recent_briefings: TodayRecentItem[];
  recent_docs: TodayRecentItem[];
  recent_sessions: TodayRecentItem[];
  maintenance: {
    last_backup_at: string | null;
    backup_count: number;
    failed_activities: number;
    draft_memories: number;
    orphan_evidence: number;
  };
}

/** 今日页「最近来源」卡片项（check-in/简报/文档/会话），宽松结构供展示与跳转。 */
export interface TodayRecentItem {
  id: number;
  title?: string;
  name?: string;
  kind?: string;
  status?: string;
  doc_type?: string | null;
  goal_id?: number;
  goal_title?: string;
  checkin_date?: string | null;
  progress_note_md?: string | null;
  confidence?: number | null;
  created_at?: string;
  updated_at?: string;
  source_type: string;
  source_id: number;
}

/** 今日页筛选（第七阶段 §5.1）。 */
export interface TodayFilters {
  type?:
    | "learning"
    | "task"
    | "doc"
    | "memory"
    | "reminder"
    | "goal"
    | "inbox"
    | "system";
  priority?: "urgent" | "high" | "normal" | "low";
  time?: "today" | "overdue" | "this-week" | "future";
  status?: "open" | "snoozed" | "done" | "ignored";
}

// ============ 第六阶段 M3：提醒 ============

export type ReminderStatus = 'active' | 'snoozed' | 'done' | 'cancelled';
export type RecurrenceFreq = 'none' | 'daily' | 'weekly' | 'monthly';

export interface RecurrenceRule {
  freq: RecurrenceFreq;
  interval: number;
}

export interface Reminder {
  id: number;
  title: string;
  body_md: string | null;
  status: ReminderStatus;
  due_at: string;
  recurrence_rule: RecurrenceRule | null;
  next_fire_at: string | null;
  last_fired_at: string | null;
  source_type: string | null;
  source_id: number | null;
  created_at: string;
  updated_at: string;
}

export interface ReminderCreate {
  title: string;
  due_at: string;
  body_md?: string;
  recurrence_rule?: RecurrenceRule;
  source_type?: string;
  source_id?: number;
}

export interface ReminderUpdate {
  title?: string;
  body_md?: string;
  due_at?: string;
  recurrence_rule?: RecurrenceRule;
  status?: ReminderStatus;
}

// ============ 第六阶段 M4/M5/M6：目标 / 简报 / 隐私维护 ============

export type GoalStatus = 'active' | 'paused' | 'done' | 'archived';
export type GoalPriority = 'low' | 'normal' | 'high';

export interface PersonalGoal {
  id: number;
  title: string;
  description: string | null;
  domain: string;
  status: GoalStatus;
  priority: GoalPriority;
  start_date: string | null;
  target_date: string | null;
  success_criteria_md: string | null;
  created_at: string;
  updated_at: string;
}

export interface GoalCreate {
  title: string;
  description?: string;
  domain?: string;
  status?: GoalStatus;
  priority?: GoalPriority;
  start_date?: string | null;
  target_date?: string | null;
  success_criteria_md?: string;
}

export interface GoalUpdate {
  title?: string;
  description?: string;
  domain?: string;
  status?: GoalStatus;
  priority?: GoalPriority;
  start_date?: string | null;
  target_date?: string | null;
  success_criteria_md?: string;
}

export interface GoalLink {
  id: number;
  goal_id: number;
  target_type: string;
  target_id: number;
  relation: string;
  created_at: string;
}

export interface GoalCheckin {
  id: number;
  goal_id: number;
  checkin_date: string;
  progress_note_md: string | null;
  confidence: number | null;
  blockers_json: string[] | null;
  next_actions_json: string[] | null;
  created_at: string;
}

export interface GoalDetail {
  goal: PersonalGoal;
  links: GoalLink[];
  checkins: GoalCheckin[];
}

export interface Briefing {
  id: number;
  kind: 'today' | 'weekly' | 'learning' | 'project' | 'goal';
  title: string;
  body_md: string;
  sources_json: Array<Record<string, unknown>> | null;
  created_at: string;
}

export interface PrivacyPreview {
  audit_id: number;
  provider_type: string;
  remote: boolean;
  remote_provider_enabled: boolean;
  context_types: string[];
  estimated_input_chars: number;
  safe_memory_count: number;
  sensitive_memory_excluded: number;
  will_send_raw_sensitive_memory: boolean;
}

export interface ProviderCallAudit {
  id: number;
  provider_type: string;
  model: string | null;
  purpose: string;
  remote: boolean;
  context_types_json: string[] | null;
  estimated_input_chars: number | null;
  estimated_output_chars: number | null;
  status: string;
  error_message: string | null;
  created_at: string;
  finished_at: string | null;
}

export interface MaintenanceHealthReport {
  generated_at: string;
  summary: {
    last_backup_at: string | null;
    backup_count: number;
    failed_activities: number;
    draft_memories: number;
    attention_tasks: number;
    orphan_evidence: number;
    open_inbox: number;
    due_reminders: number;
  };
  recommendations: string[];
}

// ============ 第七阶段 M4：统一通知中心 ============

export type NotificationLevel = "info" | "success" | "warning" | "error";
export type NotificationStatus = "unread" | "read" | "archived";

/** 持久化通知（app_notifications 表），只存摘要，不存敏感正文。 */
export interface AppNotification {
  id: number;
  level: NotificationLevel;
  kind: string;
  title: string;
  message: string | null;
  status: NotificationStatus;
  source_type: string | null;
  source_id: number | null;
  action_type: string | null;
  action_payload_json: Record<string, unknown> | null;
  created_at: string;
  read_at: string | null;
}

export interface AppNotificationCreate {
  level?: NotificationLevel;
  kind: string;
  title: string;
  message?: string;
  source_type?: string;
  source_id?: number;
  action_type?: string;
  action_payload?: Record<string, unknown>;
}
