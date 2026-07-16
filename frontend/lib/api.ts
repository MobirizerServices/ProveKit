// Same-origin by default: /api and /v1 are proxied to the backend (Next.js rewrites in
// dev, the reverse proxy in prod), so one frontend build works in every environment and
// session cookies are first-party. Set NEXT_PUBLIC_API_BASE only for a split-domain setup.
const BASE = process.env.NEXT_PUBLIC_API_BASE ?? "";

export type Kind = "llm" | "mcp" | "agent" | "a2a";
export type ReqType = "prompt" | "tool" | "agent" | "a2a";

export interface Connection {
  id: number; name: string; kind: Kind; config: Record<string, any>; created_at?: string;
}
export interface ToolDef { name: string; description: string; input_schema: Record<string, any>; }
export interface SavedRequest { id: number; name: string; type: ReqType; payload?: any; collection_id: number | null; }
export interface CollectionT { id: number; name: string; requests: SavedRequest[]; }
export interface EnvironmentT { id: number; name: string; variables: Record<string, string>; is_active: boolean; }
export interface RunSummary { id: number; type: string; label: string; status: string; duration_ms: number; created_at: string; }

export interface RunEvent {
  type: "start" | "delta" | "node" | "result" | "assert" | "done" | "error";
  run_id?: string; request_type?: string;
  text?: string; data?: any; meta?: any; error?: string; results?: any[];
  status?: string; duration_ms?: number;
}
export interface DatasetRow { name: string; status: string; text: string | null; output: any; assertions: any[]; pass: boolean; duration_ms: number; }
export interface DatasetResult { rows: DatasetRow[]; summary: { passed: number; total: number }; }
export interface SavedDataset { id: number; name: string; rows: { name: string; variables: Record<string, string> }[]; }
export interface PromptT { id: number; key: string; name: string; description: string; content: string; updated_at?: string; }
export interface FlowT { id: number; name: string; description: string; nodes: any[]; edges: any[]; updated_at?: string; }
export interface FlowSummary { id: number; name: string; description: string; updated_at?: string; }
export interface NodeTypeDef { label: string; category: string; color: string; branches?: string[]; }
export interface FlowEvent {
  type: "start" | "node" | "pause" | "done" | "error";
  run_id?: string; node_id?: string; node_type?: string; title?: string; status?: string;
  branch?: string | null; input?: any; output?: any; duration_ms?: number; error?: string; reason?: string;
}

// Redirect to /login on an unexpected 401 (hosted mode, expired session). Auth calls opt
// out via `noAuthRedirect` so the login page can surface "invalid credentials" itself.
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

export interface Me { id: number; email: string; name: string; auth_provider: string; }

// Parse one SSE event block (may contain multiple `data:` lines per the spec). Returns true on [DONE].
function _emitSSE(block: string, onEvent: (e: any) => void): boolean {
  const data = block.split(/\r?\n/).filter((l) => l.startsWith("data:")).map((l) => l.slice(5).trim());
  if (!data.length) return false;
  const d = data.join("\n");
  if (d === "[DONE]") return true;
  try { onEvent(JSON.parse(d)); } catch {}
  return false;
}

export const api = {
  base: BASE,
  // auth
  me: () => j<Me>("/api/auth/me", { noAuthRedirect: true }),
  login: (email: string, password: string) => j<Me>("/api/auth/login", { method: "POST", noAuthRedirect: true, body: JSON.stringify({ email, password }) }),
  register: (email: string, password: string, name = "") => j<Me>("/api/auth/register", { method: "POST", noAuthRedirect: true, body: JSON.stringify({ email, password, name }) }),
  logout: () => j("/api/auth/logout", { method: "POST", noAuthRedirect: true }),
  // connections
  connections: () => j<Connection[]>("/api/connections"),
  createConnection: (c: Partial<Connection>) => j<Connection>("/api/connections", { method: "POST", body: JSON.stringify(c) }),
  updateConnection: (id: number, c: Partial<Connection>) => j<Connection>(`/api/connections/${id}`, { method: "PUT", body: JSON.stringify(c) }),
  deleteConnection: (id: number) => j(`/api/connections/${id}`, { method: "DELETE" }),
  tools: (id: number) => j<{ tools: ToolDef[] }>(`/api/connections/${id}/tools`),
  testConnection: (id: number) => j<{ ok: boolean; detail: string }>(`/api/connections/${id}/test`, { method: "POST" }),
  authenticate: (id: number, payload: any) => j<{ ok: boolean; header: string; token: string }>(`/api/connections/${id}/authenticate`, { method: "POST", body: JSON.stringify(payload) }),
  agentCard: (id: number) => j<{ card: Record<string, any> }>(`/api/connections/${id}/agent-card`),
  // library
  collections: () => j<{ collections: CollectionT[]; loose: SavedRequest[] }>("/api/collections"),
  createCollection: (name: string) => j<CollectionT>("/api/collections", { method: "POST", body: JSON.stringify({ name }) }),
  deleteCollection: (id: number) => j(`/api/collections/${id}`, { method: "DELETE" }),
  saveRequest: (r: { name: string; type: string; payload: any; collection_id: number | null }) =>
    j<SavedRequest>("/api/requests", { method: "POST", body: JSON.stringify(r) }),
  getRequest: (id: number) => j<SavedRequest>(`/api/requests/${id}`),
  deleteRequest: (id: number) => j(`/api/requests/${id}`, { method: "DELETE" }),
  // environments
  environments: () => j<EnvironmentT[]>("/api/environments"),
  createEnvironment: (e: Partial<EnvironmentT>) => j<EnvironmentT>("/api/environments", { method: "POST", body: JSON.stringify(e) }),
  updateEnvironment: (id: number, e: Partial<EnvironmentT>) => j<EnvironmentT>(`/api/environments/${id}`, { method: "PUT", body: JSON.stringify(e) }),
  deleteEnvironment: (id: number) => j(`/api/environments/${id}`, { method: "DELETE" }),
  // runs
  runs: () => j<RunSummary[]>("/api/runs"),
  getRun: (id: number) => j<any>(`/api/runs/${id}`),
  runOnce: (request: any, variables: Record<string, any> = {}) =>
    j<{ result: any; status: string; duration_ms: number; assertions: any[] }>("/api/run", { method: "POST", body: JSON.stringify({ request, variables, save: false }) }),
  datasetRun: (request: any, rows: { name: string; variables: Record<string, string> }[]) =>
    j<DatasetResult>("/api/dataset/run", { method: "POST", body: JSON.stringify({ request, rows }) }),
  // prompts
  prompts: () => j<PromptT[]>("/api/prompts"),
  createPrompt: (p: Partial<PromptT>) => j<PromptT>("/api/prompts", { method: "POST", body: JSON.stringify(p) }),
  updatePrompt: (id: number, p: Partial<PromptT>) => j<PromptT>(`/api/prompts/${id}`, { method: "PUT", body: JSON.stringify(p) }),
  deletePrompt: (id: number) => j(`/api/prompts/${id}`, { method: "DELETE" }),
  // flows
  flowNodeTypes: () => j<Record<string, NodeTypeDef>>("/api/flows/node-types"),
  flows: () => j<FlowSummary[]>("/api/flows"),
  getFlow: (id: number) => j<FlowT>(`/api/flows/${id}`),
  createFlow: (name: string, nodes: any[] = [], edges: any[] = []) => j<FlowT>("/api/flows", { method: "POST", body: JSON.stringify({ name, nodes, edges }) }),
  updateFlow: (id: number, f: Partial<FlowT>) => j<FlowT>(`/api/flows/${id}`, { method: "PUT", body: JSON.stringify(f) }),
  deleteFlow: (id: number) => j(`/api/flows/${id}`, { method: "DELETE" }),
  async _sseStream(path: string, body: any, onEvent: (e: any) => void, signal?: AbortSignal) {
    const res = await fetch(`${BASE}${path}`, { method: "POST", credentials: "include", signal, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (!res.ok || !res.body) throw new Error(`stream failed (${res.status})`);
    const reader = res.body.getReader(); const dec = new TextDecoder(); let buf = "";
    try {
      while (true) {
        if (signal?.aborted) { try { await reader.cancel(); } catch {} return; }
        const { value, done } = await reader.read(); if (done) break;
        buf += dec.decode(value, { stream: true });
        let nl: number;
        while ((nl = buf.indexOf("\n\n")) >= 0) { const block = buf.slice(0, nl); buf = buf.slice(nl + 2); if (_emitSSE(block, onEvent)) return; }
      }
      if (buf.trim()) _emitSSE(buf, onEvent);  // flush a final frame that had no trailing blank line
    } finally { try { await reader.cancel(); } catch {} }
  },
  runFlowStream(id: number, input: any, opts: { breakpoints?: string[]; step?: boolean }, onEvent: (e: FlowEvent) => void, signal?: AbortSignal) {
    return this._sseStream(`/api/flows/${id}/run/stream`, { input, breakpoints: opts.breakpoints ?? [], step: !!opts.step }, onEvent, signal);
  },
  continueFlowStream(id: number, opts: { run_id: string; node_id: string; breakpoints?: string[]; step?: boolean }, onEvent: (e: FlowEvent) => void, signal?: AbortSignal) {
    return this._sseStream(`/api/flows/${id}/continue/stream`, { run_id: opts.run_id, node_id: opts.node_id, breakpoints: opts.breakpoints ?? [], step: !!opts.step }, onEvent, signal);
  },
  // deployments
  deployments: () => j<any[]>("/api/deployments"),
  createDeployment: (flow_id: number) => j<any>("/api/deployments", { method: "POST", body: JSON.stringify({ flow_id }) }),
  getDeployment: (slug: string) => j<any>(`/api/deployments/${slug}`),
  deploymentRuns: (slug: string) => j<any[]>(`/api/deployments/${slug}/runs`),
  deploymentStats: (slug: string) => j<any>(`/api/deployments/${slug}/stats`),
  deactivateDeployment: (slug: string) => j(`/api/deployments/${slug}/deactivate`, { method: "POST" }),
  rollbackDeployment: (slug: string, version: number) => j<any>(`/api/deployments/${slug}/rollback`, { method: "POST", body: JSON.stringify({ version }) }),
  datasets: () => j<SavedDataset[]>("/api/datasets"),
  createDataset: (name: string, rows: any[]) => j<SavedDataset>("/api/datasets", { method: "POST", body: JSON.stringify({ name, rows }) }),
  deleteDataset: (id: number) => j(`/api/datasets/${id}`, { method: "DELETE" }),

  async runStream(request: any, onEvent: (e: RunEvent) => void, signal?: AbortSignal): Promise<void> {
    const res = await fetch(`${BASE}/api/run/stream`, {
      method: "POST", credentials: "include", signal,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ request }),
    });
    if (!res.ok || !res.body) throw new Error(`Run failed (${res.status})`);
    const reader = res.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    try {
      while (true) {
        if (signal?.aborted) { try { await reader.cancel(); } catch {} return; }
        const { value, done } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        let nl: number;
        while ((nl = buf.indexOf("\n\n")) >= 0) {
          const block = buf.slice(0, nl);
          buf = buf.slice(nl + 2);
          if (_emitSSE(block, onEvent)) return;
        }
      }
      if (buf.trim()) _emitSSE(buf, onEvent);  // flush a final frame with no trailing blank line
    } finally { try { await reader.cancel(); } catch {} }
  },
};
