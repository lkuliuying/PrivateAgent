export interface AuthUser {
  id: number;
  email: string;
  display_name: string;
  role: "admin" | "user";
  status: "active" | "disabled";
  last_login_at: string | null;
  created_at: string;
}

export interface AuthResponse {
  access_token: string;
  token_type: "bearer";
  expires_at: string;
  user: AuthUser;
}

export interface AdminOverview {
  users_total: number;
  users_active: number;
  admins_total: number;
  sessions_total: number;
  operations_24h: number;
  errors_24h: number;
  health: Record<string, { ok?: boolean; [key: string]: unknown }>;
  generated_at: string;
}

export interface AdminUserRow extends AuthUser {
  session_count: number;
  project_count: number;
  document_count: number;
  operation_count: number;
}

export interface AuditLogRow {
  id: number;
  request_id: string;
  actor_user_id: number | null;
  actor_type: string;
  method: string;
  path: string;
  status_code: number;
  duration_ms: number;
  client_ip: string | null;
  created_at: string;
}

export interface PagedResult<T> {
  total: number;
  results: T[];
}
