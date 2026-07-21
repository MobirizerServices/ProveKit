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

  const load = () => {
    api.adminStats().then(setStats).catch(() => setForbidden(true));
    api.adminUsers().then(setUsers).catch(() => {});
    api.adminProjects().then(setProjects).catch(() => {});
  };
  useEffect(() => { load(); }, []);

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
              <div style={label}>Users ({users.length})</div>
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
            </div>

            <div style={panel}>
              <div style={label}>Projects ({projects.length})</div>
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
            </div>
          </>
        )}
      </main>
    </>
  );
}

const panel: React.CSSProperties = { background: "var(--panel)", border: "1px solid var(--border)", borderRadius: 12, padding: 16 };
const label: React.CSSProperties = { fontSize: 11, textTransform: "uppercase", letterSpacing: 0.4, color: "var(--muted)", marginBottom: 8 };
const table: React.CSSProperties = { width: "100%", borderCollapse: "collapse", fontSize: 13 };
const hrow: React.CSSProperties = { textAlign: "left", color: "var(--muted)", fontSize: 11.5 };
const th: React.CSSProperties = { padding: "4px 8px", fontWeight: 500 };
const td: React.CSSProperties = { padding: "7px 8px" };
