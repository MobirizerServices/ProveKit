// Same-origin by default: /api and /v1 are proxied to the backend (Next.js rewrites in
// dev, the reverse proxy in prod), so one frontend build works everywhere and session
// cookies are first-party. Set NEXT_PUBLIC_API_BASE only for a split-domain setup.
const BASE = process.env.NEXT_PUBLIC_API_BASE ?? "";

export interface Me { id: number; email: string; name: string; auth_provider: string; }
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
  duration_ms: number; span_count: number; tokens?: number; session_id?: string; created_at: string;
}
export interface TraceSpan extends RunDetail {
  span_id: string; parent_span_id: string; session_id?: string;
}

// A score or annotation attached to a whole trace (human, sdk, or eval).
export interface Feedback {
  id: number; trace_id: string; name: string; score: number | null; value: string;
  comment: string; source: string; created_at: string;
}

export interface TraceQuery { status?: string; window_hours?: number; limit?: number; }

export interface Project { id: number; name: string; role: string; is_default: boolean; member_count: number; created_at: string; }
export interface Member { user_id: number; email: string; name: string; role: string; }

export interface Metrics {
  window_hours: number; trace_count: number; error_count: number; error_rate: number;
  latency_p50_ms: number; latency_p95_ms: number; total_tokens: number;
  series: { t: string; count: number; errors: number }[];
  by_model: { model: string; calls: number; tokens: number }[];
  generated_at: string;
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
    throw new Error(`${res.status}: ${(await res.text()).slice(0, 300)}`);
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
  shareTrace: (traceId: string) => j<{ token: string; trace_id: string }>(`/api/traces/${encodeURIComponent(traceId)}/share`, { method: "POST" }),
  // dashboard metrics
  metrics: (window_hours = 24) => j<Metrics>(`/api/metrics?window_hours=${window_hours}`),
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
  deleteProject: (id: number) => j(`/api/projects/${id}`, { method: "DELETE" }),
  members: (id: number) => j<Member[]>(`/api/projects/${id}/members`),
  addMember: (id: number, email: string, role = "member") => j<Member>(`/api/projects/${id}/members`, { method: "POST", body: JSON.stringify({ email, role }) }),
  removeMember: (id: number, userId: number) => j(`/api/projects/${id}/members/${userId}`, { method: "DELETE" }),
  // health (for the backend-down banner; never redirects/throws loudly)
  health: async (): Promise<boolean> => {
    try { const r = await fetch(`${BASE}/healthz`, { credentials: "include" }); return r.ok; } catch { return false; }
  },
};
