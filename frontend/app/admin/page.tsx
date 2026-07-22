"use client";

import { useEffect, useState } from "react";
import { API_BASE, AdminProject, AdminStats, AdminUser, AuditEntry, api } from "@/lib/api";
import TopNav from "@/components/TopNav";

// Fleet health (roadmap #84). Typed here rather than in lib/api because it is only ever read
// by this page — the operator console is the one surface that looks across tenants.
interface FleetTenant {
  workspace_id: number; name: string; owner: string;
  traces: number; errors: number; error_rate: number;
  error_share: number; volume_share: number; blame: number;
  recent_traces: number; prior_traces: number; trend_pct: number | null;
  spans_per_trace: number; bytes_per_span: number;
  ingest_bytes: number; storage_bytes: number; retention_spans: number;
  sampled_spans: number; last_ingest_at: string | null; ingest_age_seconds: number | null;
}
interface FleetSnapshot {
  window_hours: number; generated_at: string; partial_open_hour: boolean; approximate: boolean;
  limit: number; total: number;
  instance: {
    tenants_active: number; traces: number; errors: number; error_rate: number;
    ingest: { spool: boolean; queue_depth?: number; lag_seconds?: number };
  };
  tenants: FleetTenant[];
}

export default function AdminPage() {
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [projects, setProjects] = useState<AdminProject[]>([]);
  const [forbidden, setForbidden] = useState(false);
  const [err, setErr] = useState("");
  // Server-side paging + search: the tables used to fetch every row, which is fine on a small
  // deployment and unusable on a large one.
  const [uq, setUq] = useState(""); const [uOff, setUOff] = useState(0); const [uTotal, setUTotal] = useState(0);
  const [pq, setPq] = useState(""); const [pOff, setPOff] = useState(0); const [pTotal, setPTotal] = useState(0);
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [aq, setAq] = useState(""); const [aOff, setAOff] = useState(0); const [aTotal, setATotal] = useState(0);
  const [fleet, setFleet] = useState<FleetSnapshot | null>(null);
  const [fWindow, setFWindow] = useState(24);

  const load = () => {
    // Not in lib/api: this endpoint is read by this page only. `credentials` matches the
    // shared wrapper so the operator session cookie travels with it.
    fetch(`${API_BASE}/api/admin/fleet?window_hours=${fWindow}&limit=${PAGE / 2}`, { credentials: "include" })
      .then((r) => (r.ok ? r.json() : null)).then(setFleet).catch(() => {});
    api.adminStats().then(setStats).catch(() => setForbidden(true));
    api.adminUsers({ limit: PAGE, offset: uOff, q: uq })
      .then((r) => { setUsers(r.users); setUTotal(r.total); }).catch(() => {});
    api.adminProjects({ limit: PAGE, offset: pOff, q: pq })
      .then((r) => { setProjects(r.projects); setPTotal(r.total); }).catch(() => {});
    api.adminAudit({ limit: PAGE, offset: aOff, q: aq })
      .then((r) => { setAudit(r.entries); setATotal(r.total); }).catch(() => {});
  };
  // Re-query on paging; debounce the search so typing doesn't fire a request per keystroke.
  useEffect(() => { const t = setTimeout(load, 200); return () => clearTimeout(t); },
    [uq, uOff, pq, pOff, aq, aOff, fWindow]);

  const toggleSuper = async (u: AdminUser) => {
    setErr("");
    // Surface the refusal (e.g. revoking a SUPERUSER_EMAILS account) — swallowing it makes a
    // rejected revoke look like it succeeded.
    try { await api.setSuperuser(u.id, !u.is_superuser); load(); }
    catch (e) { setErr(e instanceof Error ? e.message : "Could not change superuser access."); }
  };

  return (
    <>
      <TopNav />
      <main style={{ maxWidth: 1080, margin: "0 auto", padding: "24px 20px 80px" }}>
        <h1 style={{ fontSize: 22, margin: "0 0 4px" }}>Admin</h1>
        <p className="muted" style={{ margin: "0 0 20px", fontSize: 13.5 }}>
          Platform operator console — every user and project across this deployment.
        </p>

        {forbidden ? (
          <div className="muted" style={{ fontSize: 13 }}>You don’t have access to the admin console.</div>
        ) : !stats ? (
          <div className="muted" style={{ fontSize: 13 }}>Loading…</div>
        ) : (
          <>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))", gap: 12, marginBottom: 24 }}>
              {([["Users", stats.users], ["Projects", stats.projects], ["Members", stats.members],
                 ["Traces", stats.traces], ["Spans", stats.spans], ["Datasets", stats.datasets],
                 ["Experiments", stats.experiments]] as [string, number][]).map(([k, v]) => (
                <div key={k} style={panel}>
                  <div className="muted" style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: 0.4 }}>{k}</div>
                  <div style={{ fontSize: 22, fontWeight: 700, marginTop: 4 }}>{v.toLocaleString()}</div>
                </div>
              ))}
            </div>

            <FleetPanel snap={fleet} windowHours={fWindow} onWindow={setFWindow} />

            <div style={{ ...panel, marginBottom: 20 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <div style={label}>Users ({uTotal.toLocaleString()})</div>
                <input value={uq} onChange={(e) => { setUq(e.target.value); setUOff(0); }}
                  placeholder="Search email or name" style={search} />
              </div>
              {err && (
                <div style={{ fontSize: 12.5, color: "var(--err)", margin: "0 0 10px" }}>{err}</div>
              )}
              <div style={{ overflowX: "auto" }}>
                <table style={table}>
                  <thead><tr style={hrow}><th style={th}>Email</th><th style={th}>Auth</th><th style={th}>Projects</th><th style={th}>Superuser</th></tr></thead>
                  <tbody>
                    {users.map((u) => (
                      <tr key={u.id} style={{ borderTop: "1px solid var(--border)" }}>
                        <td style={td}>{u.email}{u.name ? <span className="muted"> · {u.name}</span> : ""}</td>
                        <td style={{ ...td, color: "var(--muted)" }}>{u.auth_provider}</td>
                        <td style={td}>{u.project_count}</td>
                        <td style={td}>
                          {u.is_bootstrap ? (
                            <span className="muted" style={{ fontSize: 12 }}
                              title="Granted by the SUPERUSER_EMAILS config, which overrides the database flag. Remove the address there and restart the backend to revoke.">
                              ✓ Superuser · config
                            </span>
                          ) : (
                            <button className="btn btn-sm" onClick={() => toggleSuper(u)}
                              style={u.is_superuser ? { borderColor: "var(--accent)", color: "var(--accent)" } : undefined}>
                              {u.is_superuser ? "✓ Superuser" : "Grant"}
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <Pager offset={uOff} total={uTotal} onPage={setUOff} />
            </div>

            <div style={panel}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <div style={label}>Projects ({pTotal.toLocaleString()})</div>
                <input value={pq} onChange={(e) => { setPq(e.target.value); setPOff(0); }}
                  placeholder="Search name or owner" style={search} />
              </div>
              <div style={{ overflowX: "auto" }}>
                <table style={table}>
                  <thead><tr style={hrow}><th style={th}>Name</th><th style={th}>Owner</th><th style={th}>Members</th><th style={th}>Spans</th><th style={th}>Retention</th><th style={th}>PII</th></tr></thead>
                  <tbody>
                    {projects.map((p) => (
                      <tr key={p.id} style={{ borderTop: "1px solid var(--border)" }}>
                        <td style={td}>{p.name}</td>
                        <td style={{ ...td, color: "var(--muted)" }}>{p.owner}</td>
                        <td style={td}>{p.member_count}</td>
                        <td style={td}>{p.span_count.toLocaleString()}</td>
                        <td style={td}>{p.retention || "default"}</td>
                        <td style={td}>{p.redact_pii ? "on" : "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <Pager offset={pOff} total={pTotal} onPage={setPOff} />
            </div>

            <div style={{ ...panel, marginTop: 20 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <div style={label}>Audit log ({aTotal.toLocaleString()})</div>
                <input value={aq} onChange={(e) => { setAq(e.target.value); setAOff(0); }}
                  placeholder="Search actor or target" style={search} />
              </div>
              {audit.length === 0 ? (
                <div className="muted" style={{ fontSize: 13, padding: "6px 0" }}>
                  No privileged changes recorded yet. Grants, revocations, project deletions
                  and key lifecycle appear here.
                </div>
              ) : (
                <div style={{ overflowX: "auto" }}>
                  <table style={table}>
                    <thead><tr style={hrow}><th style={th}>When</th><th style={th}>Actor</th><th style={th}>Action</th><th style={th}>Target</th><th style={th}>IP</th></tr></thead>
                    <tbody>
                      {audit.map((e) => (
                        <tr key={e.id} style={{ borderTop: "1px solid var(--border)" }}>
                          <td style={{ ...td, whiteSpace: "nowrap", color: "var(--muted)" }}>
                            {new Date(e.created_at).toLocaleString()}
                          </td>
                          <td style={td}>{e.actor_email || <span className="muted">system</span>}</td>
                          <td style={td}><span style={actionTag(e.action)}>{e.action}</span></td>
                          <td style={td}>
                            {e.target_label || e.target_id}
                            {e.target_type ? <span className="muted"> · {e.target_type}</span> : ""}
                          </td>
                          <td style={{ ...td, color: "var(--muted)", fontSize: 12 }}>{e.ip || "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              <Pager offset={aOff} total={aTotal} onPage={setAOff} />
            </div>
          </>
        )}
      </main>
    </>
  );
}

const PAGE = 50;
const WINDOWS: [string, number][] = [["6h", 6], ["24h", 24], ["7d", 168]];

// "Who is filling the database?" — the tenants are already ranked by their share of the
// instance's traces and failures, so this renders the server's order and never re-sorts.
// Re-sorting client-side would only ever reorder the page, which is not the instance.
function FleetPanel({ snap, windowHours, onWindow }:
  { snap: FleetSnapshot | null; windowHours: number; onWindow: (n: number) => void }) {
  const inst = snap?.instance;
  return (
    <div style={{ ...panel, marginBottom: 20 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12 }}>
        <div>
          <div style={label}>Fleet health</div>
          <div className="muted" style={{ fontSize: 12.5, marginTop: -4, marginBottom: 8 }}>
            Who is responsible for what the instance dashboard is showing — worst first.
          </div>
        </div>
        <div style={{ display: "flex", gap: 6 }}>
          {WINDOWS.map(([lbl, h]) => (
            <button key={h} className="btn btn-sm" onClick={() => onWindow(h)}
              style={h === windowHours ? { borderColor: "var(--accent)", color: "var(--accent)" } : undefined}>
              {lbl}
            </button>
          ))}
        </div>
      </div>

      {inst && (
        <div className="muted" style={{ fontSize: 12.5, marginBottom: 10 }}>
          {inst.tenants_active.toLocaleString()} active {inst.tenants_active === 1 ? "project" : "projects"} ·{" "}
          {inst.traces.toLocaleString()} traces ·{" "}
          <span style={{ color: inst.errors ? "var(--err)" : undefined }}>
            {pct(inst.error_rate)} errors
          </span>
          {inst.ingest.spool && (inst.ingest.queue_depth ?? 0) > 0 ? (
            <span style={{ color: "var(--amber)" }}>
              {" "}· ingest backlog {inst.ingest.queue_depth} batches, {Math.round(inst.ingest.lag_seconds ?? 0)}s behind
            </span>
          ) : null}
        </div>
      )}

      {/* Never let a bounded read look like a complete one — the whole point of reading
          rollups is that the numbers stay honest about what they cover. */}
      {snap?.partial_open_hour && (
        <div style={{ fontSize: 12, color: "var(--amber)", marginBottom: 8 }}>
          This hour is ingesting faster than the bounded scan covers — live figures are a floor.
        </div>
      )}

      {!snap ? (
        <div className="muted" style={{ fontSize: 13, padding: "6px 0" }}>Loading…</div>
      ) : snap.tenants.length === 0 ? (
        <div className="muted" style={{ fontSize: 13, padding: "6px 0" }}>
          No project has ingested anything in this window.
        </div>
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table style={table}>
            <thead><tr style={hrow}>
              <th style={th}>Project</th><th style={th}>Traces</th><th style={th}>Trend</th>
              <th style={th}>Errors</th><th style={th}>Share of errors</th>
              <th style={th}>Est. size</th><th style={th}>Last ingest</th>
            </tr></thead>
            <tbody>
              {snap.tenants.map((t) => (
                <tr key={t.workspace_id} style={{ borderTop: "1px solid var(--border)" }}>
                  <td style={td}>
                    {t.name}
                    {t.owner ? <span className="muted" style={{ fontSize: 12 }}> · {t.owner}</span> : ""}
                  </td>
                  <td style={td}>{t.traces.toLocaleString()}</td>
                  <td style={{ ...td, ...trendStyle(t.trend_pct) }}>{trendText(t.trend_pct)}</td>
                  <td style={{ ...td, color: t.errors ? "var(--err)" : "var(--muted)" }}>
                    {pct(t.error_rate)}
                  </td>
                  <td style={td}><ShareBar share={t.error_share} /></td>
                  <td style={td} title={`~${t.bytes_per_span.toLocaleString()} bytes/span from a ${t.sampled_spans}-span sample; capped at retention (${t.retention_spans.toLocaleString()} spans)`}>
                    {bytes(t.storage_bytes)}
                    <span className="muted" style={{ fontSize: 11.5 }}> · +{bytes(t.ingest_bytes)}</span>
                  </td>
                  <td style={{ ...td, color: "var(--muted)", whiteSpace: "nowrap" }}>{age(t.ingest_age_seconds)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="muted" style={{ fontSize: 11.5, marginTop: 8 }}>
        Volume and errors come from hourly rollups plus the current hour; sizes are estimated
        from a bounded sample, so read them as magnitudes, not as disk accounting.
      </div>
    </div>
  );
}

// The share of the instance's failures this tenant owns — the column that answers the
// question, so it gets a bar rather than another number to compare by eye.
function ShareBar({ share }: { share: number }) {
  const w = Math.max(0, Math.min(1, share));
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
      <span style={{ width: 56, height: 5, borderRadius: 3, background: "var(--border)", overflow: "hidden" }}>
        <span style={{ display: "block", width: `${w * 100}%`, height: "100%", background: w >= 0.34 ? "var(--err)" : "var(--muted)" }} />
      </span>
      <span className="muted" style={{ fontSize: 11.5 }}>{pct(share)}</span>
    </span>
  );
}

const pct = (v: number) => `${(v * 100).toFixed(v > 0 && v < 0.01 ? 2 : 1)}%`;

function trendText(v: number | null): string {
  if (v === null) return "new";                 // no baseline half — not "+∞%"
  return `${v > 0 ? "+" : ""}${v.toFixed(0)}%`;
}
function trendStyle(v: number | null): React.CSSProperties {
  if (v === null) return { color: "var(--muted)" };
  return { color: v >= 50 ? "var(--amber)" : v <= -50 ? "var(--muted)" : "inherit" };
}

function bytes(n: number): string {
  const units = ["B", "KB", "MB", "GB", "TB"];
  let v = n, i = 0;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i += 1; }
  return `${v < 10 && i > 0 ? v.toFixed(1) : Math.round(v)} ${units[i]}`;
}

function age(seconds: number | null): string {
  if (seconds === null) return "—";
  if (seconds < 90) return `${Math.round(seconds)}s ago`;
  if (seconds < 5400) return `${Math.round(seconds / 60)}m ago`;
  if (seconds < 172800) return `${Math.round(seconds / 3600)}h ago`;
  return `${Math.round(seconds / 86400)}d ago`;
}

// Hidden entirely when everything fits on one page, so a small deployment sees no chrome.
function Pager({ offset, total, onPage }: { offset: number; total: number; onPage: (n: number) => void }) {
  if (total <= PAGE) return null;
  const from = total === 0 ? 0 : offset + 1;
  const to = Math.min(offset + PAGE, total);
  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "flex-end", gap: 10, marginTop: 10, fontSize: 12.5 }}>
      <span className="muted">{from.toLocaleString()}–{to.toLocaleString()} of {total.toLocaleString()}</span>
      <button className="btn btn-sm" disabled={offset === 0} onClick={() => onPage(Math.max(0, offset - PAGE))}>Prev</button>
      <button className="btn btn-sm" disabled={to >= total} onClick={() => onPage(offset + PAGE)}>Next</button>
    </div>
  );
}

// Grants and deletions are the entries an operator scans for, so they get the weight.
function actionTag(action: string): React.CSSProperties {
  const color = action.endsWith(".grant") ? "var(--amber)"
    : action.endsWith(".delete") || action.endsWith(".revoke") ? "var(--err)"
      : "var(--muted)";
  return { fontFamily: "var(--font-mono)", fontSize: 11.5, color, whiteSpace: "nowrap" };
}

const search: React.CSSProperties = { background: "var(--bg)", border: "1px solid var(--border)", borderRadius: 8, color: "inherit", fontSize: 12.5, padding: "5px 9px", width: 210, marginBottom: 8 };
const panel: React.CSSProperties = { background: "var(--panel)", border: "1px solid var(--border)", borderRadius: 12, padding: 16 };
const label: React.CSSProperties = { fontSize: 11, textTransform: "uppercase", letterSpacing: 0.4, color: "var(--muted)", marginBottom: 8 };
const table: React.CSSProperties = { width: "100%", borderCollapse: "collapse", fontSize: 13 };
const hrow: React.CSSProperties = { textAlign: "left", color: "var(--muted)", fontSize: 11.5 };
const th: React.CSSProperties = { padding: "4px 8px", fontWeight: 500 };
const td: React.CSSProperties = { padding: "7px 8px" };
