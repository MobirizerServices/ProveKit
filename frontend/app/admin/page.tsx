"use client";

import { useEffect, useState } from "react";
import { AdminProject, AdminStats, AdminUser, api } from "@/lib/api";
import TopNav from "@/components/TopNav";

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

  const load = () => {
    api.adminStats().then(setStats).catch(() => setForbidden(true));
    api.adminUsers({ limit: PAGE, offset: uOff, q: uq })
      .then((r) => { setUsers(r.users); setUTotal(r.total); }).catch(() => {});
    api.adminProjects({ limit: PAGE, offset: pOff, q: pq })
      .then((r) => { setProjects(r.projects); setPTotal(r.total); }).catch(() => {});
  };
  // Re-query on paging; debounce the search so typing doesn't fire a request per keystroke.
  useEffect(() => { const t = setTimeout(load, 200); return () => clearTimeout(t); },
    [uq, uOff, pq, pOff]);

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
          </>
        )}
      </main>
    </>
  );
}

const PAGE = 50;

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

const search: React.CSSProperties = { background: "var(--bg)", border: "1px solid var(--border)", borderRadius: 8, color: "inherit", fontSize: 12.5, padding: "5px 9px", width: 210, marginBottom: 8 };
const panel: React.CSSProperties = { background: "var(--panel)", border: "1px solid var(--border)", borderRadius: 12, padding: 16 };
const label: React.CSSProperties = { fontSize: 11, textTransform: "uppercase", letterSpacing: 0.4, color: "var(--muted)", marginBottom: 8 };
const table: React.CSSProperties = { width: "100%", borderCollapse: "collapse", fontSize: 13 };
const hrow: React.CSSProperties = { textAlign: "left", color: "var(--muted)", fontSize: 11.5 };
const th: React.CSSProperties = { padding: "4px 8px", fontWeight: 500 };
const td: React.CSSProperties = { padding: "7px 8px" };
