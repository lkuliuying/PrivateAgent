// 由 scripts/protocol_codegen.py 生成，禁止手改。
// 唯一类型源：private_agent_core/coding_contracts.py；应用边界提供版本化扩展。

export type CapabilitySnapshot = { "protocol_version"?: "1.0"; "tools"?: Array<ToolCapability>; "execution"?: boolean; "stdin"?: boolean; "pty"?: boolean; "model_streaming"?: boolean; "output_streaming"?: boolean; "recovery"?: boolean };

export type ContentRef = { "sha256": string; "bytes": number };

export type ContextItem = { "item_id": string; "session_id": number; "run_id": string; "ordinal": number; "role": "system" | "user" | "assistant" | "tool"; "kind": "message" | "instruction" | "tool_call" | "tool_result" | "summary"; "content_ref": ContentRef; "source": "user" | "project_instruction" | "model" | "tool" | "summary" | "legacy"; "created_at": string; "tool_call_id"?: string | null; "execution_id"?: string | null; "operation_id"?: string | null; "source_sequence"?: number | null; "summary_of"?: Array<string> };

export type EventEnvelope = { "schema_version"?: "1.0"; "run_id": string; "sequence": number; "type": string; "payload"?: Record<string, unknown> };

export type EvidenceRef = { "evidence_id": string; "run_id": string; "operation_id": string; "tool_call_id"?: string | null; "execution_id"?: string | null; "source_sequence": number; "content_ref": ContentRef; "verified_at": string; "workspace_version": number };

export type ExecutionResult = { "schema_version"?: "1.0"; "execution_id": string; "operation_id": string; "outcome": "exited" | "timed_out" | "cancelled" | "failed" | "unknown"; "exit_code"?: number | null; "output_ref"?: ContentRef | null; "command_kind"?: "test" | "search" | "development" | "unclassified"; "validation_outcome"?: "succeeded" | "failed" | "unknown" };

export type Requirement = { "requirement_id": string; "description": string; "required"?: boolean; "kind"?: "file_changed" | "command" | "test" | "artifact" | "preview" | "manual"; "scope"?: string; "origin"?: "user" | "intent_rule" | "tool" | "legacy"; "evidence_policy"?: "disk" | "exit" | "test_exit" | "response" | "manual" };

export type RunOutcome = { "schema_version"?: "1.0"; "run_id": string; "goal_outcome": "answered" | "verified" | "unmet" | "blocked" | "unknown"; "requirements"?: Array<Requirement>; "verification_results"?: Array<VerificationResult>; "evidence_ids"?: Array<string>; "unverified_items"?: Array<string>; "evidence_refs"?: Array<EvidenceRef> };

export type ToolCapability = { "name": string; "version": string };

export type VerificationResult = { "requirement_id": string; "status": "passed" | "failed" | "blocked" | "unverified"; "evidence_ids"?: Array<string>; "message"?: string };

export type WorkspaceIdentity = { "project_id": number; "workspace_id": number; "root_path": string; "canonical_path": string; "git_available": boolean; "initial_head"?: string | null; "initial_dirty"?: boolean | null };
