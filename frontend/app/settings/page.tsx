"use client";

import { useCallback, useEffect, useState } from "react";
import { api, getProjectId, Member, Project, QuotaLine, setProjectId, Usage } from "@/lib/api";
import ConsoleShell from "@/components/ConsoleShell";
import ModelConnections from "@/components/ModelConnections";
import ActivityFeed from "@/components/ActivityFeed";

export default function SettingsPage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [sel, setSel] = useState<number | null>(null);
  const [members, setMembers] = useState<Member[]>([]);
  const [newProj, setNewProj] = useState("");
  const [rename, setRename] = useState("");
  const [invite, setInvite] = useState("");
  const [retention, setRetention] = useState(0);
  const [usage, setUsage] = useState<Usage | null>(null);
  const [redact, setRedact] = useState(false);
  const [replayUrl, setReplayUrl] = useState("");
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
    api.usage().then(setUsage).catch(() => {});
    setRedact(p?.redact_pii ?? false);
    setReplayUrl(p?.replay_url ?? "");
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
  const saveSettings = () => wrap(async () => { if (sel) { await api.updateProject(sel, { retention, redact_pii: redact, replay_url: replayUrl.trim() }); load(); } });
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
    <ConsoleShell>
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

                {/* A quota you can't see is indistinguishable from a bug — a throttled
                    project just looks broken. Only rendered when limits actually exist. */}
                {usage && (usage.spans.limit || usage.projects.limit) && (
                  <div style={{ marginBottom: 18 }}>
                    <div style={label}>Usage · {usage.period}</div>
                    <Meter label="Spans this month" line={usage.spans} />
                    <Meter label="Projects" line={usage.projects} />
                    {usage.approximate && (
                      <div className="muted" style={{ fontSize: 11, marginTop: 4 }}>
                        Approximate: counters are per-process without Redis configured.
                      </div>
                    )}
                  </div>
                )}

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

                <div style={label}>Replay webhook (optional)</div>
                <p className="muted" style={{ fontSize: 12, margin: "0 0 8px" }}>
                  For exact trace replay: ProveKit POSTs a fork override here and your agent returns
                  OTLP. Leave blank to use reconstructed replay only.
                </p>
                <div style={{ display: "flex", gap: 8, marginBottom: 22 }}>
                  <input value={replayUrl} onChange={(e) => setReplayUrl(e.target.value)} disabled={!isOwner}
                    placeholder="https://your-agent.example/replay" style={{ ...input, flex: 1 }} />
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

                <div style={{ marginBottom: 22 }}>
                  <ModelConnections />
                </div>

                {/* Lives next to the settings it explains: the row above says retention is
                    5000, this says who set it to that and when. Every member can read it —
                    it is not an owner-only view. */}
                <div style={{ marginBottom: 22 }}>
                  <ActivityFeed projectId={sel} />
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
    </ConsoleShell>
  );
}

const panel: React.CSSProperties = { background: "var(--panel)", border: "1px solid var(--border)", borderRadius: 12, padding: 16 };
function Meter({ label: text, line }: { label: string; line: QuotaLine }) {
  if (line.limit == null) return null;          // unlimited — nothing meaningful to meter
  const pct = Math.min(100, line.pct ?? 0);
  // Amber before the wall, not at it: the useful moment to know is while you can still act.
  const color = pct >= 100 ? "var(--err)" : pct >= 80 ? "var(--amber)" : "var(--green)";
  return (
    <div style={{ marginBottom: 8 }}>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12.5, marginBottom: 3 }}>
        <span>{text}</span>
        <span className="muted">{line.used.toLocaleString()} / {line.limit.toLocaleString()}</span>
      </div>
      <div style={{ height: 6, borderRadius: 999, background: "var(--panel-2)", overflow: "hidden" }}>
        <div style={{ width: `${pct}%`, height: "100%", background: color }} />
      </div>
    </div>
  );
}

const label: React.CSSProperties = { fontSize: 11, textTransform: "uppercase", letterSpacing: 0.4, color: "var(--muted)", marginBottom: 6 };
const input: React.CSSProperties = { background: "var(--panel-2)", color: "var(--text)", border: "1px solid var(--border-strong)", borderRadius: 8, padding: "8px 11px", fontSize: 13 };
const errBox: React.CSSProperties = { background: "color-mix(in srgb, var(--red) 12%, transparent)", border: "1px solid var(--red)", color: "var(--red)", borderRadius: 8, padding: "8px 12px", fontSize: 13, marginBottom: 16 };
function row(active: boolean): React.CSSProperties {
  return { display: "block", width: "100%", textAlign: "left", padding: "10px 13px",
    background: active ? "var(--accent-soft)" : "transparent", color: "var(--text)",
    border: "none", borderBottom: "1px solid var(--border)", cursor: "pointer" };
}
