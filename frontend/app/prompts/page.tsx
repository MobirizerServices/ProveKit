"use client";

import { useEffect, useMemo, useState } from "react";
import { api, PROMPT_LABELS, SavedPrompt } from "@/lib/api";
import TopNav from "@/components/TopNav";
import { DiffText } from "@/components/DiffText";

/**
 * The prompt registry: every saved version of every prompt, with the two controls that make it
 * a registry rather than a history — which version a label points at (what production fetches),
 * and how live traffic is split across versions.
 */
export default function PromptsPage() {
  const [rows, setRows] = useState<SavedPrompt[] | null>(null);
  const [sel, setSel] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [compare, setCompare] = useState<[number, number] | null>(null);
  const [splitDraft, setSplitDraft] = useState<Record<number, string> | null>(null);

  const load = () => api.prompts().then(setRows).catch(() => setRows([]));
  useEffect(() => { load(); }, []);

  const byName = useMemo(() => {
    const m = new Map<string, SavedPrompt[]>();
    for (const p of rows || []) { (m.get(p.name) || m.set(p.name, []).get(p.name)!).push(p); }
    for (const v of m.values()) v.sort((a, b) => b.version - a.version);   // newest first
    return m;
  }, [rows]);

  const names = [...byName.keys()];
  useEffect(() => { if (!sel && names.length) setSel(names[0]); }, [names, sel]);
  const versions = (sel && byName.get(sel)) || null;

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true); setErr("");
    try { await fn(); await load(); }
    catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  };

  const setLabel = (v: SavedPrompt, label: string) =>
    act(() => api.labelPrompt(v.name, v.version, label));
  const del = (id: number) => act(() => api.deletePrompt(id));
  const copy = (v: SavedPrompt) =>
    navigator.clipboard?.writeText(JSON.stringify({ model: v.model, messages: v.messages, params: v.params }, null, 2));

  // ---- traffic split -------------------------------------------------------
  const liveSplit = useMemo(() => {
    const out: Record<number, number> = {};
    for (const v of versions || []) if ((v.traffic || 0) > 0) out[v.version] = v.traffic!;
    return out;
  }, [versions]);
  const splitTotal = Object.values(splitDraft || {}).reduce((s, x) => s + (parseFloat(x) || 0), 0);

  const saveSplit = () => {
    if (!sel || !splitDraft) return;
    const weights: Record<number, number> = {};
    for (const [ver, w] of Object.entries(splitDraft)) {
      const n = parseFloat(w) || 0;
      if (n > 0) weights[Number(ver)] = n;
    }
    return act(async () => { await api.splitPrompt(sel, weights); setSplitDraft(null); });
  };

  const cmp = compare && versions
    ? [versions.find((v) => v.version === compare[0]), versions.find((v) => v.version === compare[1])] as const
    : null;

  return (
    <>
      <TopNav />
      <div className="page">
        <div className="page-inner" style={{ maxWidth: 1180 }}>
          <div className="page-head">
            <div>
              <div className="page-eyebrow">Control</div>
              <h1>Prompt registry</h1>
              <p>
                Version, label, compare and roll back prompts without a deploy. Your app fetches
                by label — <code className="mono">GET /v1/prompts/&#123;name&#125;?label=production</code> —
                so moving the pointer here changes what production runs.
              </p>
            </div>
          </div>

          {err && <div className="auth-err" style={{ marginBottom: 14 }}>{err}</div>}

          {rows == null ? (
            <div className="muted" style={{ fontSize: 13 }}>Loading…</div>
          ) : names.length === 0 ? (
            <div className="pr-card">
              <div className="muted" style={{ fontSize: 13 }}>
                No saved prompts yet. Open a trace → click an <b>LLM</b> node → <b>▶ Edit &amp; re-run</b> →
                edit the prompt → <b>💾 Save version</b>.
              </div>
            </div>
          ) : (
            <div className="reg-grid">
              {/* ---------------- name list ---------------- */}
              <div className="reg-list">
                {names.map((n) => {
                  const vs = byName.get(n)!;
                  const prod = vs.find((v) => v.label === "production");
                  const serving = vs.filter((v) => (v.traffic || 0) > 0).length;
                  return (
                    <button key={n} className={`reg-item ${sel === n ? "on" : ""}`}
                      onClick={() => { setSel(n); setCompare(null); setSplitDraft(null); }}>
                      <div className="reg-item-name">{n}</div>
                      <div className="reg-item-sub">
                        {vs.length} version{vs.length === 1 ? "" : "s"}
                        {prod ? <> · <span className="reg-dot prod" />prod v{prod.version}</> : null}
                        {serving > 1 ? <> · <span className="reg-dot split" />A/B</> : null}
                      </div>
                    </button>
                  );
                })}
              </div>

              {/* ---------------- versions ---------------- */}
              <div>
                {!versions ? (
                  <div className="pr-card"><span className="muted">Select a prompt.</span></div>
                ) : (
                  <>
                    <div className="reg-head">
                      <h2>{sel}</h2>
                      <div className="reg-head-actions">
                        {splitDraft === null ? (
                          <button className="btn btn-sm" onClick={() => setSplitDraft(
                            Object.fromEntries(versions.map((v) => [v.version, String(v.traffic || 0)])))}>
                            {Object.keys(liveSplit).length > 1 ? "Edit traffic split" : "Start an A/B"}
                          </button>
                        ) : (
                          <>
                            <button className="btn btn-sm btn-ghost" onClick={() => setSplitDraft(null)}>Cancel</button>
                            <button className="btn btn-sm btn-run" disabled={busy || splitTotal <= 0} onClick={saveSplit}>
                              Save split
                            </button>
                          </>
                        )}
                      </div>
                    </div>

                    {Object.keys(liveSplit).length > 1 && splitDraft === null && (
                      <div className="reg-split-bar" title="Live traffic split">
                        {Object.entries(liveSplit).map(([ver, w]) => {
                          const total = Object.values(liveSplit).reduce((s, x) => s + x, 0);
                          return (
                            <span key={ver} style={{ width: `${(w / total) * 100}%` }}>
                              v{ver} · {Math.round((w / total) * 100)}%
                            </span>
                          );
                        })}
                      </div>
                    )}

                    {splitDraft !== null && (
                      <div className="reg-split-edit">
                        <p className="muted">
                          Weights are relative. A version at 0 stops serving. Assignment is hashed on the
                          key your app passes, so one user stays on one variant.
                        </p>
                        {versions.map((v) => (
                          <label key={v.version}>
                            <span>v{v.version}</span>
                            <input type="number" min={0} step={1} value={splitDraft[v.version] ?? "0"}
                              onChange={(e) => setSplitDraft({ ...splitDraft, [v.version]: e.target.value })} />
                            <span className="muted">
                              {splitTotal > 0 ? `${Math.round(((parseFloat(splitDraft[v.version]) || 0) / splitTotal) * 100)}%` : "—"}
                            </span>
                          </label>
                        ))}
                      </div>
                    )}

                    <div className="reg-versions">
                      {versions.map((v) => (
                        <div key={v.id} className={`reg-ver ${v.label === "production" ? "is-prod" : ""}`}>
                          <div className="reg-ver-top">
                            <span className="reg-ver-n">v{v.version}</span>
                            {v.label && <span className={`reg-label ${v.label}`}>{v.label}</span>}
                            {(v.traffic || 0) > 0 && <span className="reg-traffic">{v.traffic} traffic</span>}
                            <span className="mono muted" style={{ fontSize: 11.5 }}>
                              {v.model || "—"}{v.params?.temperature != null ? ` · temp ${v.params.temperature}` : ""}
                            </span>
                            <span className="reg-ver-actions">
                              <select className="reg-sel" value={v.label || ""} disabled={busy}
                                onChange={(e) => setLabel(v, e.target.value)} title="Move a label onto this version">
                                <option value="">no label</option>
                                {PROMPT_LABELS.map((l) => <option key={l} value={l}>{l}</option>)}
                              </select>
                              <button className="btn btn-sm btn-ghost" onClick={() => copy(v)}>Copy</button>
                              <button className="btn btn-sm btn-ghost" disabled={busy} onClick={() => del(v.id)}>Delete</button>
                            </span>
                          </div>
                          <div className="reg-ver-body">
                            {(v.messages || []).map((m, i) => (
                              <div key={i} className="reg-msg">
                                <span className="reg-role">{m.role}</span>
                                <div>{m.content}</div>
                              </div>
                            ))}
                          </div>
                          {versions.length > 1 && (
                            <div className="reg-ver-foot">
                              <button className="btn btn-sm btn-ghost"
                                onClick={() => {
                                  const other = versions.find((o) => o.version !== v.version)!;
                                  setCompare([other.version, v.version]);
                                }}>
                                Compare with v{versions.find((o) => o.version !== v.version)!.version}
                              </button>
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  </>
                )}
              </div>
            </div>
          )}

          {/* ---------------- compare drawer ---------------- */}
          {cmp && cmp[0] && cmp[1] && (
            <div className="overlay" onClick={() => setCompare(null)}>
              <div className="modal" style={{ width: 820 }} onClick={(e) => e.stopPropagation()}>
                <div className="modal-head">
                  Compare {sel}: v{cmp[0].version} → v{cmp[1].version}
                  <button onClick={() => setCompare(null)}>✕</button>
                </div>
                <div className="modal-body">
                  <div className="reg-cmp-meta">
                    <span>{cmp[0].model || "—"} → {cmp[1].model || "—"}</span>
                    <select className="reg-sel" value={cmp[0].version}
                      onChange={(e) => setCompare([Number(e.target.value), cmp[1]!.version])}>
                      {versions!.map((v) => <option key={v.version} value={v.version}>v{v.version}</option>)}
                    </select>
                    <span className="muted">vs</span>
                    <select className="reg-sel" value={cmp[1].version}
                      onChange={(e) => setCompare([cmp[0]!.version, Number(e.target.value)])}>
                      {versions!.map((v) => <option key={v.version} value={v.version}>v{v.version}</option>)}
                    </select>
                  </div>
                  {roleUnion(cmp[0], cmp[1]).map((role, i) => (
                    <div key={i} className="reg-cmp-block">
                      <span className="reg-role">{role}</span>
                      <DiffText
                        from={cmp[0]!.messages?.find((m) => m.role === role)?.content || ""}
                        to={cmp[1]!.messages?.find((m) => m.role === role)?.content || ""}
                      />
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </>
  );
}

function roleUnion(a: SavedPrompt, b: SavedPrompt): string[] {
  const seen: string[] = [];
  for (const m of [...(a.messages || []), ...(b.messages || [])]) {
    if (!seen.includes(m.role)) seen.push(m.role);
  }
  return seen;
}
