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

// Redirect to /login on an unexpected 401 (expired session). Auth calls opt out via
// `noAuthRedirect` so the login page can surface "invalid credentials" itself.
async function j<T>(path: string, opts?: RequestInit & { noAuthRedirect?: boolean }): Promise<T> {
  const { noAuthRedirect, ...init } = opts || {};
  const res = await fetch(`${BASE}${path}`, {
    credentials: "include", headers: { "Content-Type": "application/json" }, ...init,
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
  // captured runs (traces)
  runs: () => j<RunSummary[]>("/api/runs"),
  getRun: (id: number) => j<RunDetail>(`/api/runs/${id}`),
  // health (for the backend-down banner; never redirects/throws loudly)
  health: async (): Promise<boolean> => {
    try { const r = await fetch(`${BASE}/healthz`, { credentials: "include" }); return r.ok; } catch { return false; }
  },
};
