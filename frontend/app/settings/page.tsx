"use client";

import { useCallback, useEffect, useState } from "react";
import { api, getProjectId, Member, Project, setProjectId } from "@/lib/api";
import TopNav from "@/components/TopNav";

export default function SettingsPage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [sel, setSel] = useState<number | null>(null);
  const [members, setMembers] = useState<Member[]>([]);
  const [newProj, setNewProj] = useState("");
  const [rename, setRename] = useState("");
  const [invite, setInvite] = useState("");
  const [retention, setRetention] = useState(0);
  const [redact, setRedact] = useState(false);
  const [err, setErr] = useState("");

  const load = useCallback(() => {
    api.projects().then((ps) => {
      setProjects(ps);
      setSel((s) => s ?? (ps.find((p) => String(p.id) === getProjectId())?.id ?? ps.find((p) => p.is_default)?.id ?? ps[0]?.id ?? null));
    }).catch(() => {});
  }, []);
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (sel == null) { setMembers([]); return; }
    api.members(sel).then(setMembers).catch(() => setMembers([]));
    const p = projects.find((x) => x.id === sel);
    setRename(p?.name || "");
    setRetention(p?.retention ?? 0);
    setRedact(p?.redact_pii ?? false);
  }, [sel, projects]);

  const current = projects.find((p) => p.id === sel);
  const isOwner = current?.role === "owner";
  const wrap = async (fn: () => Promise<any>) => { setErr(""); try { await fn(); } catch (e: any) { setErr(String(e.message || e)); } };

  const create = () => wrap(async () => {
    if (!newProj.trim()) return;
    const p = await api.createProject(newProj.trim());
    setNewProj(""); load(); setSel(p.id);
    setProjectId(p.id); // switch to the new project immediately
  });
  const doRename = () => wrap(async () => { if (sel) { await api.renameProject(sel, rename.trim()); load(); } });
  const saveSettings = () => wrap(async () => { if (sel) { await api.updateProject(sel, { retention, redact_pii: redact }); load(); } });
  const doDelete = () => wrap(async () => {
    if (sel && confirm("Delete this project and all its traces, datasets, and keys? This cannot be undone.")) {
      await api.deleteProject(sel);
      if (String(sel) === getProjectId()) setProjectId(null);
      setSel(null); load();
    }
  });
  const addMember = () => wrap(async () => { if (sel && invite.trim()) { await api.addMember(sel, invite.trim()); setInvite(""); api.members(sel).then(setMembers); } });
  const removeMember = (uid: number) => wrap(async () => { if (sel) { await api.removeMember(sel, uid); api.members(sel).then(setMembers); } });

  return (
    <>
      <TopNav />
      <main style={{ maxWidth: 900, margin: "0 auto", padding: "24px 20px 80px" }}>
        <h1 style={{ fontSize: 22, margin: "0 0 4px" }}>Projects</h1>
        <p className="muted" style={{ margin: "0 0 20px", fontSize: 13.5 }}>
          Each project is an isolated workspace with its own keys, traces, datasets, and members.
        </p>

        {err && <div style={errBox}>{err}</div>}

        <div style={{ display: "grid", gridTemplateColumns: "260px 1fr", gap: 16 }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <div style={{ display: "flex", gap: 6 }}>
              <input value={newProj} onChange={(e) => setNewProj(e.target.value)} placeholder="New project name…"
                onKeyDown={(e) => e.key === "Enter" && create()} style={input} />
              <button className="btn btn-sm" onClick={create}>Add</button>
            </div>
            <div style={{ ...panel, padding: 0, overflow: "hidden" }}>
              {projects.map((p) => (
                <button key={p.id} onClick={() => setSel(p.id)} style={row(sel === p.id)}>
                  <div style={{ fontWeight: 500, fontSize: 13 }}>{p.name}</div>
                  <div className="muted" style={{ fontSize: 11.5, marginTop: 2 }}>
                    {p.role}{p.is_default ? " · default" : ""} · {p.member_count} member{p.member_count === 1 ? "" : "s"}
                  </div>
                </button>
              ))}
            </div>
          </div>

          <div style={{ ...panel }}>
            {!current ? (
              <div className="muted" style={{ fontSize: 13 }}>Select a project.</div>
            ) : (
              <>
                <div style={label}>Name</div>
                <div style={{ display: "flex", gap: 8, marginBottom: 20 }}>
                  <input value={rename} onChange={(e) => setRename(e.target.value)} disabled={!isOwner} style={{ ...input, flex: 1 }} />
                  <button className="btn btn-sm" onClick={doRename} disabled={!isOwner}>Rename</button>
                </div>

                <div style={label}>Data settings</div>
                <div style={{ display: "flex", gap: 16, alignItems: "flex-end", marginBottom: 22, flexWrap: "wrap" }}>
                  <div>
                    <div className="muted" style={{ fontSize: 11.5, marginBottom: 4 }}>Retention (spans; 0 = default)</div>
                    <input type="number" min={0} value={retention} disabled={!isOwner}
                      onChange={(e) => setRetention(Number(e.target.value))} style={{ ...input, width: 160 }} />
                  </div>
                  <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, cursor: isOwner ? "pointer" : "default" }}>
                    <input type="checkbox" checked={redact} disabled={!isOwner} onChange={(e) => setRedact(e.target.checked)} />
                    Mask PII on ingest
                  </label>
                  <button className="btn btn-sm" onClick={saveSettings} disabled={!isOwner}>Save</button>
                </div>

                <div style={label}>Members</div>
                {isOwner && (
                  <div style={{ display: "flex", gap: 8, marginBottom: 10 }}>
                    <input value={invite} onChange={(e) => setInvite(e.target.value)} placeholder="teammate@company.com"
                      onKeyDown={(e) => e.key === "Enter" && addMember()} style={{ ...input, flex: 1 }} />
                    <button className="btn btn-sm" onClick={addMember}>Invite</button>
                  </div>
                )}
                <div style={{ ...panel, padding: 0, overflow: "hidden", marginBottom: 22 }}>
                  {members.map((m) => (
                    <div key={m.user_id} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "9px 12px", borderBottom: "1px solid var(--border)" }}>
                      <div>
                        <span style={{ fontSize: 13 }}>{m.name || m.email}</span>
                        <span className="muted" style={{ fontSize: 11.5, marginLeft: 8 }}>{m.email} · {m.role}</span>
                      </div>
                      {isOwner && <button className="btn btn-sm btn-ghost" onClick={() => removeMember(m.user_id)}>Remove</button>}
                    </div>
                  ))}
                </div>

                {isOwner && (
                  <>
                    <div style={{ ...label, color: "var(--red)" }}>Danger zone</div>
                    <button className="btn btn-sm" onClick={doDelete}
                      style={{ borderColor: "var(--red)", color: "var(--red)" }}>Delete project</button>
                  </>
                )}
              </>
            )}
          </div>
        </div>
      </main>
    </>
  );
}

const panel: React.CSSProperties = { background: "var(--panel)", border: "1px solid var(--border)", borderRadius: 12, padding: 16 };
const label: React.CSSProperties = { fontSize: 11, textTransform: "uppercase", letterSpacing: 0.4, color: "var(--muted)", marginBottom: 6 };
const input: React.CSSProperties = { background: "var(--panel-2)", color: "var(--text)", border: "1px solid var(--border-strong)", borderRadius: 8, padding: "8px 11px", fontSize: 13 };
const errBox: React.CSSProperties = { background: "color-mix(in srgb, var(--red) 12%, transparent)", border: "1px solid var(--red)", color: "var(--red)", borderRadius: 8, padding: "8px 12px", fontSize: 13, marginBottom: 16 };
function row(active: boolean): React.CSSProperties {
  return { display: "block", width: "100%", textAlign: "left", padding: "10px 13px",
    background: active ? "var(--accent-soft)" : "transparent", color: "var(--text)",
    border: "none", borderBottom: "1px solid var(--border)", cursor: "pointer" };
}
