"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api, getProjectId, Member, Project, QuotaLine, setProjectId, Usage } from "@/lib/api";
import ConsoleShell from "@/components/ConsoleShell";
import PageHero from "@/components/PageHero";
import ModelConnections from "@/components/ModelConnections";
import ActivityFeed from "@/components/ActivityFeed";

type SectionKey = "general" | "privacy" | "members" | "connections" | "keys" | "usage" | "audit";
const SECTIONS: { key: SectionKey; label: string; hint: string }[] = [
  { key: "general", label: "General", hint: "Name & retention" },
  { key: "privacy", label: "Data & privacy", hint: "PII masking, replay, delete" },
  { key: "members", label: "Members & roles", hint: "Who can access" },
  { key: "connections", label: "Model connections", hint: "Providers & keys" },
  { key: "keys", label: "Project keys", hint: "Ingest & API keys" },
  { key: "usage", label: "Usage & billing", hint: "Quotas this period" },
  { key: "audit", label: "Audit log", hint: "Recent changes" },
];

export default function SettingsPage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [sel, setSel] = useState<number | null>(null);
  const [section, setSection] = useState<SectionKey>("general");
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
    setProjectId(p.id);
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
      <div className="cs-page" style={{ maxWidth: 1080 }}>
        <PageHero eyebrow="Workspace" title="Settings"
          sub="Every project is an isolated workspace with its own keys, traces, datasets, and members. Owners control retention, privacy, and access."
          status={current ? `${current.name} · ${current.role}${current.is_default ? " · default" : ""}` : undefined} />

        {err && <div className="auth-err" style={{ marginBottom: 14 }}>{err}</div>}

        <div className="set2">
          {/* LEFT — project picker + settings nav */}
          <aside className="set2-nav">
            <div className="set2-projects">
              <div className="set2-nav-head">Projects</div>
              {projects.map((p) => (
                <button key={p.id} className={`set2-proj ${sel === p.id ? "on" : ""}`} onClick={() => setSel(p.id)}>
                  <span className="set2-proj-name">{p.name}</span>
                  <span className="set2-proj-meta">{p.role}{p.is_default ? " · default" : ""} · {p.member_count} member{p.member_count === 1 ? "" : "s"}</span>
                </button>
              ))}
              <div className="set2-add">
                <input value={newProj} onChange={(e) => setNewProj(e.target.value)} placeholder="New project…"
                  onKeyDown={(e) => e.key === "Enter" && create()} />
                <button className="btn btn-sm" onClick={create}>Add</button>
              </div>
            </div>
            <div className="set2-nav-head" style={{ marginTop: 6 }}>Settings</div>
            {SECTIONS.map((s) => (
              <button key={s.key} className={`set2-item ${section === s.key ? "on" : ""}`} onClick={() => setSection(s.key)}>
                <span className="set2-item-label">{s.label}</span>
                <span className="set2-item-hint">{s.hint}</span>
              </button>
            ))}
          </aside>

          {/* RIGHT — the selected section */}
          <section className="set2-panel">
            {!current ? <div className="muted" style={{ fontSize: 13 }}>Select a project.</div> : (
              <>
                {section === "general" && (
                  <>
                    <h2 className="set2-h">General</h2>
                    <div className="set2-field">
                      <label>Project name</label>
                      <div className="set2-row">
                        <input value={rename} onChange={(e) => setRename(e.target.value)} disabled={!isOwner} />
                        <button className="btn btn-sm" onClick={doRename} disabled={!isOwner}>Rename</button>
                      </div>
                    </div>
                    <div className="set2-field">
                      <label>Trace retention (spans; 0 = plan default)</label>
                      <div className="set2-row">
                        <input type="number" min={0} value={retention} disabled={!isOwner}
                          onChange={(e) => setRetention(Number(e.target.value))} style={{ maxWidth: 200 }} />
                        <button className="btn btn-sm" onClick={saveSettings} disabled={!isOwner}>Save</button>
                      </div>
                      <p className="set2-help">Older spans are pruned once a project exceeds this many. Leave at 0 to use the plan default.</p>
                    </div>
                  </>
                )}

                {section === "privacy" && (
                  <>
                    <h2 className="set2-h">Data & privacy</h2>
                    <div className="set2-toggle-row">
                      <div>
                        <div className="set2-toggle-label">Mask PII on ingest</div>
                        <p className="set2-help" style={{ margin: 0 }}>Emails, keys, and card-shaped strings are redacted before a span is stored.</p>
                      </div>
                      <button className={`au2-toggle ${redact ? "on" : ""}`} disabled={!isOwner}
                        onClick={() => { setRedact(!redact); }}><span className="au2-toggle-knob" /></button>
                    </div>
                    <div className="set2-row" style={{ marginBottom: 22 }}>
                      <button className="btn btn-sm" onClick={saveSettings} disabled={!isOwner}>Save privacy settings</button>
                    </div>

                    <div className="set2-field">
                      <label>Replay webhook (optional)</label>
                      <p className="set2-help">For exact trace replay: ProveKit POSTs a fork override here and your agent returns OTLP. Leave blank to use reconstructed replay only.</p>
                      <div className="set2-row">
                        <input value={replayUrl} onChange={(e) => setReplayUrl(e.target.value)} disabled={!isOwner}
                          placeholder="https://your-agent.example/replay" />
                        <button className="btn btn-sm" onClick={saveSettings} disabled={!isOwner}>Save</button>
                      </div>
                    </div>

                    {isOwner && (
                      <div className="set2-danger">
                        <div className="set2-danger-head">Danger zone</div>
                        <div className="set2-danger-row">
                          <span>Delete this project and all of its traces, datasets, and keys. This cannot be undone.</span>
                          <button className="btn btn-sm" onClick={doDelete}
                            style={{ borderColor: "var(--red)", color: "var(--red)" }}>Delete project</button>
                        </div>
                      </div>
                    )}
                  </>
                )}

                {section === "members" && (
                  <>
                    <h2 className="set2-h">Members & roles</h2>
                    {isOwner && (
                      <div className="set2-row" style={{ marginBottom: 14 }}>
                        <input value={invite} onChange={(e) => setInvite(e.target.value)} placeholder="teammate@company.com"
                          onKeyDown={(e) => e.key === "Enter" && addMember()} />
                        <button className="btn btn-sm" onClick={addMember}>Invite</button>
                      </div>
                    )}
                    <div className="set2-members">
                      {members.map((m) => (
                        <div key={m.user_id} className="set2-member">
                          <div>
                            <span className="set2-member-name">{m.name || m.email}</span>
                            <span className="set2-member-meta">{m.email} · {m.role}</span>
                          </div>
                          {isOwner && m.role !== "owner" && <button className="btn btn-sm btn-ghost" onClick={() => removeMember(m.user_id)}>Remove</button>}
                        </div>
                      ))}
                      {members.length === 0 && <div className="muted" style={{ fontSize: 13, padding: "8px 2px" }}>No members yet.</div>}
                    </div>
                  </>
                )}

                {section === "connections" && (
                  <>
                    <h2 className="set2-h">Model connections</h2>
                    <ModelConnections />
                  </>
                )}

                {section === "keys" && (
                  <>
                    <h2 className="set2-h">Project keys</h2>
                    <p className="set2-help">Ingest keys and API keys live on their own page, where you can create and revoke them.</p>
                    <Link className="btn btn-sm" href="/api-keys">Manage project keys →</Link>
                  </>
                )}

                {section === "usage" && (
                  <>
                    <h2 className="set2-h">Usage & billing</h2>
                    {usage && (usage.spans.limit || usage.projects.limit) ? (
                      <>
                        <div className="set2-help" style={{ marginBottom: 12 }}>Period: {usage.period}</div>
                        <Meter label="Spans this month" line={usage.spans} />
                        <Meter label="Projects" line={usage.projects} />
                        {usage.approximate && <p className="set2-help">Approximate: counters are per-process without Redis configured.</p>}
                      </>
                    ) : <p className="muted" style={{ fontSize: 13 }}>No quotas configured — this workspace is on an unlimited plan.</p>}
                  </>
                )}

                {section === "audit" && (
                  <>
                    <h2 className="set2-h">Audit log</h2>
                    <ActivityFeed projectId={sel!} />
                  </>
                )}
              </>
            )}
          </section>
        </div>
      </div>
    </ConsoleShell>
  );
}

function Meter({ label: text, line }: { label: string; line: QuotaLine }) {
  if (line.limit == null) return null;
  const pct = Math.min(100, line.pct ?? 0);
  const color = pct >= 100 ? "var(--red)" : pct >= 80 ? "var(--amber)" : "var(--green)";
  return (
    <div style={{ marginBottom: 10 }}>
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
