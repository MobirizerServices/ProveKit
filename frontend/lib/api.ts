// Same-origin by default: /api and /v1 are proxied to the backend (Next.js rewrites in
// dev, the reverse proxy in prod), so one frontend build works everywhere and session
// cookies are first-party. Set NEXT_PUBLIC_API_BASE only for a split-domain setup.
const BASE = process.env.NEXT_PUBLIC_API_BASE ?? "";

export interface Me { id: number; email: string; name: string; auth_provider: string; is_superuser?: boolean; }
export interface ApiKey { id: number; name: string; prefix: string; revoked: boolean; last_used_at: string | null; created_at?: string; }
export interface RunSummary { id: number; type: string; label: string; status: string; duration_ms: number; created_at: string; }

// A captured run's full detail (a gen_ai span mapped to a run).
export interface RunDetail {
  id: number; type: string; label: string; status: string; duration_ms: number;
  created_at: string; error?: string;
  request?: { type?: string; provider?: string; model?: string; operation?: string; input?: string };
  result?: { text?: string | null; output?: any; meta?: Record<string, any> };
}

// One trace = a decorated run and everything nested beneath it.
export interface TraceSummary {
  id: number; trace_id: string; label: string; type: string; status: string;
  duration_ms: number; span_count: number; tokens?: number; session_id?: string;
  model?: string | null; created_at: string;
}
export interface TraceSpan extends RunDetail {
  span_id: string; parent_span_id: string; session_id?: string;
}

// A score or annotation attached to a whole trace (human, sdk, or eval).
export interface Feedback {
  id: number; trace_id: string; name: string; score: number | null; value: string;
  comment: string; source: string; created_at: string;
}

// `cursor` is the id of the last row you were given; keyset paging, so a trace landing mid-scroll
// can't shift the window and make a row repeat or vanish the way an offset would.
export interface TraceQuery { status?: string; window_hours?: number; limit?: number; q?: string; cursor?: number; }

export interface Project { id: number; name: string; role: string; is_default: boolean; member_count: number; retention?: number; redact_pii?: boolean; replay_url?: string; created_at: string; }
export interface Member { user_id: number; email: string; name: string; role: string; }
export interface AdminStats { users: number; projects: number; members: number; spans: number; traces: number; datasets: number; experiments: number; }
export interface AdminUser { id: number; email: string; name: string; auth_provider: string; is_superuser: boolean; is_bootstrap: boolean; project_count: number; created_at: string; }
export interface AdminQuery { limit?: number; offset?: number; q?: string; }
// The admin tables are paged, so the row array arrives under a named key beside the totals.
export type Paged<K extends string, T> = { total: number; limit: number; offset: number } & { [P in K]: T[] };
function adminQs(p?: AdminQuery): string {
  const qs = new URLSearchParams();
  if (p?.limit != null) qs.set("limit", String(p.limit));
  if (p?.offset != null) qs.set("offset", String(p.offset));
  if (p?.q) qs.set("q", p.q);
  const s = qs.toString();
  return s ? `?${s}` : "";
}
export interface AdminProject { id: number; name: string; owner: string; member_count: number; span_count: number; retention: number; redact_pii: boolean; created_at: string; }
export interface Alert {
  id: number; name: string; metric: string; comparator: string; threshold: number;
  window_hours: number; email: string; webhook_url: string; enabled: boolean; last_triggered_at: string | null; created_at: string;
}
export interface AlertIn { name?: string; metric: string; comparator?: string; threshold?: number; window_hours?: number; email?: string; webhook_url?: string; enabled?: boolean; }

export interface Metrics {
  window_hours: number; trace_count: number; error_count: number; error_rate: number;
  latency_p50_ms: number; latency_p95_ms: number; total_tokens: number;
  series: { t: string; count: number; errors: number; p50?: number; p95?: number; tokens?: number; by_model?: Record<string, number> }[];
  by_model: { model: string; calls: number; tokens: number }[];
  fail_by_type?: { type: string; count: number }[];
  top_errors?: { error: string; type: string; count: number }[];
  recent_failures?: { label: string; type: string; error: string; trace_id: string; at: string }[];
  generated_at: string;
}

export interface ProviderConnection {
  id: number; provider: string; label: string; key_hint: string; base_url: string;
  last_used_at: string | null; created_at: string;
}
export interface ConnectionIn { provider: string; label?: string; key?: string; base_url?: string; }
export interface PlaygroundMessage { role: string; content: string; }
export interface PlaygroundIn {
  model: string; messages: PlaygroundMessage[]; params?: Record<string, any>;
  connection_id?: number | null; provider?: string; from_span_id?: string;
}
export interface PlaygroundResult {
  output: string; usage: { input_tokens: number; output_tokens: number };
  latency_ms: number; finish_reason: string; provider: string; model: string;
}
export interface ReplayIn extends PlaygroundIn { origin_trace_id: string; fork_span_id: string; mode?: string; }
export interface SavedPrompt {
  id: number; name: string; version: number; model: string;
  messages: PlaygroundMessage[]; params: Record<string, any>; created_at: string;
}
export interface ExperimentSummary {
  id: number; name: string; dataset_id: number | null; created_at: string;
  result_count: number; scorer_means: Record<string, number>; mean_score: number | null;
}
export interface PlaygroundExperimentIn extends PlaygroundIn { dataset_id: number; name?: string; scorers?: string[]; }
export interface SpanNote { id: number; trace_id: string; span_id: string; author: string; body: string; created_at: string; }
export interface ReplayResult {
  new_trace_id: string; replay_run_id: number; fork_output: string;
  live_count: number; span_count: number;
}

export interface Dataset { id: number; name: string; description: string; item_count: number; created_at: string; }
export interface DatasetItem { id: number; dataset_id: number; input: string; expected: string; meta: any; created_at: string; }
export interface DatasetDetail extends Dataset { items: DatasetItem[]; }
export interface Experiment {
  id: number; name: string; dataset_id: number | null; created_at: string;
  result_count: number; mean_score: number | null; scorer_means: Record<string, number>;
}

// The active project id (persisted client-side). Sent as X-Project-Id so every request is
// scoped to the selected project; the backend validates membership and falls back to the
// user's default, so a stale value is harmless.
const PROJECT_KEY = "pk_project";
export function getProjectId(): string | null {
  return typeof window === "undefined" ? null : localStorage.getItem(PROJECT_KEY);
}
export function setProjectId(id: number | string | null): void {
  if (typeof window === "undefined") return;
  if (id == null) localStorage.removeItem(PROJECT_KEY);
  else localStorage.setItem(PROJECT_KEY, String(id));
}

// Redirect to /login on an unexpected 401 (expired session). Auth calls opt out via
// `noAuthRedirect` so the login page can surface "invalid credentials" itself.
async function j<T>(path: string, opts?: RequestInit & { noAuthRedirect?: boolean }): Promise<T> {
  const { noAuthRedirect, ...init } = opts || {};
  const pid = getProjectId();
  const res = await fetch(`${BASE}${path}`, {
    credentials: "include",
    ...init,
    headers: { "Content-Type": "application/json", ...(init.headers || {}), ...(pid ? { "X-Project-Id": pid } : {}) },
  });
  if (!res.ok) {
    if (res.status === 401 && !noAuthRedirect && typeof window !== "undefined" && !location.pathname.startsWith("/login")) {
      location.href = "/login?next=" + encodeURIComponent(location.pathname);
    }
    if (res.status === 429) throw new Error("Rate limit reached — wait a moment and try again.");
    // Unwrap FastAPI's {"detail": "..."} so the UI can show the message rather than raw JSON.
    // The status stays in the string — callers match on it (e.g. AuthForm's `includes("409")`).
    const body = (await res.text()).slice(0, 300);
    let detail = body;
    try { const p = JSON.parse(body); if (typeof p?.detail === "string") detail = p.detail; } catch { /* not JSON */ }
    throw new Error(`${res.status}: ${detail}`);
  }
  return res.status === 204 ? (undefined as T) : res.json();
}

export const api = {
  base: BASE,
  // auth
  me: () => j<Me>("/api/auth/me", { noAuthRedirect: true }),
  login: (email: string, password: string) => j<Me>("/api/auth/login", { method: "POST", noAuthRedirect: true, body: JSON.stringify({ email, password }) }),
  register: (email: string, password: string, name = "") => j<Me>("/api/auth/register", { method: "POST", noAuthRedirect: true, body: JSON.stringify({ email, password, name }) }),
  logout: () => j("/api/auth/logout", { method: "POST", noAuthRedirect: true }),
  forgotPassword: (email: string) => j("/api/auth/forgot", { method: "POST", noAuthRedirect: true, body: JSON.stringify({ email }) }),
  resetPassword: (token: string, password: string) => j("/api/auth/reset", { method: "POST", noAuthRedirect: true, body: JSON.stringify({ token, password }) }),
  verifyEmail: (token: string) => j<Me>("/api/auth/verify", { method: "POST", noAuthRedirect: true, body: JSON.stringify({ token }) }),
  // project keys
  apiKeys: () => j<ApiKey[]>("/api/api-keys"),
  createApiKey: (name: string) => j<ApiKey & { key: string }>("/api/api-keys", { method: "POST", body: JSON.stringify({ name }) }),
  revokeApiKey: (id: number) => j(`/api/api-keys/${id}`, { method: "DELETE" }),
  // captured runs (flat) — kept for compatibility
  runs: () => j<RunSummary[]>("/api/runs"),
  getRun: (id: number) => j<RunDetail>(`/api/runs/${id}`),
  // traces (a run + its nested spans, as a tree)
  traces: (query?: TraceQuery) => {
    const p = new URLSearchParams();
    if (query?.status) p.set("status", query.status);
    if (query?.window_hours) p.set("window_hours", String(query.window_hours));
    if (query?.limit) p.set("limit", String(query.limit));
    if (query?.q) p.set("q", query.q);
    if (query?.cursor) p.set("cursor", String(query.cursor));
    const qs = p.toString();
    return j<TraceSummary[]>(`/api/traces${qs ? `?${qs}` : ""}`);
  },
  trace: (traceId: string) => j<TraceSpan[]>(`/api/traces/${encodeURIComponent(traceId)}`),
  // one shared, public (read-only) trace by signed token
  sharedTrace: (token: string) => j<TraceSpan[]>(`/v1/share/${encodeURIComponent(token)}`),
  // feedback / scoring on a trace
  feedback: (traceId: string) => j<Feedback[]>(`/api/traces/${encodeURIComponent(traceId)}/feedback`),
  addFeedback: (traceId: string, body: { name: string; score?: number | null; value?: string; comment?: string }) =>
    j<Feedback>(`/api/traces/${encodeURIComponent(traceId)}/feedback`, { method: "POST", body: JSON.stringify(body) }),
  // mint a shareable link token for a trace
  shareTrace: (traceId: string) => j<{ token: string; trace_id: string; expires_in_days: number }>(`/api/traces/${encodeURIComponent(traceId)}/share`, { method: "POST" }),
  // dashboard metrics
  metrics: (window_hours = 24) => j<Metrics>(`/api/metrics?window_hours=${window_hours}`),
  // alerts
  alerts: () => j<Alert[]>("/api/alerts"),
  createAlert: (a: AlertIn) => j<Alert>("/api/alerts", { method: "POST", body: JSON.stringify(a) }),
  toggleAlert: (id: number, enabled: boolean) => j<Alert>(`/api/alerts/${id}`, { method: "PATCH", body: JSON.stringify({ enabled }) }),
  deleteAlert: (id: number) => j(`/api/alerts/${id}`, { method: "DELETE" }),
  checkAlerts: () => j<{ fired: any[] }>("/api/alerts/check", { method: "POST" }),

  // model connections + playground (interactive debugging)
  connections: () => j<ProviderConnection[]>("/api/connections"),
  createConnection: (c: ConnectionIn) => j<ProviderConnection>("/api/connections", { method: "POST", body: JSON.stringify(c) }),
  deleteConnection: (id: number) => j(`/api/connections/${id}`, { method: "DELETE" }),
  playgroundRun: (p: PlaygroundIn) => j<PlaygroundResult>("/api/playground/run", { method: "POST", body: JSON.stringify(p) }),
  replay: (p: ReplayIn) => j<ReplayResult>("/api/replay", { method: "POST", body: JSON.stringify(p) }),
  prompts: () => j<SavedPrompt[]>("/api/prompts"),
  savePrompt: (p: { name: string; model?: string; messages?: PlaygroundMessage[]; params?: Record<string, any> }) =>
    j<SavedPrompt>("/api/prompts", { method: "POST", body: JSON.stringify(p) }),
  deletePrompt: (id: number) => j(`/api/prompts/${id}`, { method: "DELETE" }),
  playgroundExperiment: (p: PlaygroundExperimentIn) => j<ExperimentSummary>("/api/playground/experiment", { method: "POST", body: JSON.stringify(p) }),
  notes: (traceId: string) => j<SpanNote[]>(`/api/traces/${traceId}/notes`),
  addNote: (traceId: string, n: { span_id?: string; body: string }) => j<SpanNote>(`/api/traces/${traceId}/notes`, { method: "POST", body: JSON.stringify(n) }),
  deleteNote: (id: number) => j(`/api/notes/${id}`, { method: "DELETE" }),
  // datasets
  datasets: () => j<Dataset[]>("/api/datasets"),
  dataset: (id: number) => j<DatasetDetail>(`/api/datasets/${id}`),
  createDataset: (name: string, description = "") => j<Dataset>("/api/datasets", { method: "POST", body: JSON.stringify({ name, description }) }),
  deleteDataset: (id: number) => j(`/api/datasets/${id}`, { method: "DELETE" }),
  addDatasetItem: (id: number, input: string, expected = "") => j<DatasetItem>(`/api/datasets/${id}/items`, { method: "POST", body: JSON.stringify({ input, expected }) }),
  addDatasetItemFromTrace: (id: number, trace_id: string) => j<DatasetItem>(`/api/datasets/${id}/items/from-trace`, { method: "POST", body: JSON.stringify({ trace_id }) }),
  // experiments
  experiments: (dataset_id?: number) => j<Experiment[]>(`/api/experiments${dataset_id != null ? `?dataset_id=${dataset_id}` : ""}`),
  // projects (workspaces)
  projects: () => j<Project[]>("/api/projects"),
  createProject: (name: string) => j<Project>("/api/projects", { method: "POST", body: JSON.stringify({ name }) }),
  renameProject: (id: number, name: string) => j<{ id: number; name: string }>(`/api/projects/${id}`, { method: "PATCH", body: JSON.stringify({ name }) }),
  updateProject: (id: number, patch: { name?: string; retention?: number; redact_pii?: boolean; replay_url?: string }) => j<{ id: number; name: string; retention: number; redact_pii: boolean; replay_url: string }>(`/api/projects/${id}`, { method: "PATCH", body: JSON.stringify(patch) }),
  deleteProject: (id: number) => j(`/api/projects/${id}`, { method: "DELETE" }),
  members: (id: number) => j<Member[]>(`/api/projects/${id}/members`),
  addMember: (id: number, email: string, role = "member") => j<Member>(`/api/projects/${id}/members`, { method: "POST", body: JSON.stringify({ email, role }) }),
  removeMember: (id: number, userId: number) => j(`/api/projects/${id}/members/${userId}`, { method: "DELETE" }),
  // platform superadmin
  adminStats: () => j<AdminStats>("/api/admin/stats"),
  adminUsers: (p?: AdminQuery) => j<Paged<"users", AdminUser>>(`/api/admin/users${adminQs(p)}`),
  adminProjects: (p?: AdminQuery) => j<Paged<"projects", AdminProject>>(`/api/admin/projects${adminQs(p)}`),
  setSuperuser: (uid: number, is_superuser: boolean) => j<{ id: number; is_superuser: boolean; is_bootstrap: boolean }>(`/api/admin/users/${uid}`, { method: "PATCH", body: JSON.stringify({ is_superuser }) }),
  // health (for the backend-down banner; never redirects/throws loudly)
  health: async (): Promise<boolean> => {
    try { const r = await fetch(`${BASE}/healthz`, { credentials: "include" }); return r.ok; } catch { return false; }
  },
};
