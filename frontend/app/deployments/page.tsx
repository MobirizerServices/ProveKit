"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import TopNav from "@/components/TopNav";

export default function DeploymentsPage() {
  const [deps, setDeps] = useState<any[]>([]);
  const [sel, setSel] = useState<string | null>(null);
  const [stats, setStats] = useState<any>(null);
  const [runs, setRuns] = useState<any[]>([]);
  const [toast, setToast] = useState<string | null>(null);
  const [usage, setUsage] = useState<any>(null);
  const flash = (t: string) => { setToast(t); setTimeout(() => setToast(null), 2000); };
  const load = () => api.deployments().then(setDeps).catch(() => {});
  useEffect(() => { load(); api.usage(30).then(setUsage).catch(() => {}); }, []);
  useEffect(() => {
    if (!sel) { setStats(null); setRuns([]); return; }
    let cancelled = false;  // ignore out-of-order responses when switching between deployments
    setStats(null); setRuns([]);
    api.deploymentStats(sel).then((s) => { if (!cancelled) setStats(s); }).catch(() => {});
    api.deploymentRuns(sel).then((r) => { if (!cancelled) setRuns(r); }).catch(() => {});
    return () => { cancelled = true; };
  }, [sel]);

  const deactivate = async (slug: string) => {
    if (!confirm(`Deactivate "${slug}"? Its endpoint will stop responding.`)) return;
    try { await api.deactivateDeployment(slug); flash("Deactivated"); load(); }
    catch (e: any) { flash(e.message); }
  };
  const rollback = async (slug: string, version: number) => {
    if (version < 2 || !confirm(`Roll "${slug}" back to v${version - 1}?`)) return;
    try { await api.rollbackDeployment(slug, version - 1); flash(`Rolled back to v${version - 1}`); load(); }
    catch (e: any) { flash(e.message); }
  };

  return (
    <div className="app" style={{ gridTemplateRows: "auto 1fr" }}>
      <TopNav />
      <div className="page">
        <div className="page-inner">
          <div className="page-head">
            <div>
              <div className="page-eyebrow">Runtime</div>
              <h1>Deployments</h1>
              <p>Flows you’ve published as hosted API endpoints. Deploy from the Flows canvas.</p>
            </div>
          </div>
          {usage && (
            <div className="dep-metrics" style={{ marginBottom: 18 }}>
              <div className="dep-stat"><b>{usage.runs}</b><span>runs · {usage.window_days}d</span></div>
              <div className="dep-stat"><b>{usage.tokens_in.toLocaleString()}</b><span>tokens in</span></div>
              <div className="dep-stat"><b>{usage.tokens_out.toLocaleString()}</b><span>tokens out</span></div>
              <div className="dep-stat"><b>{usage.by_model.length}</b><span>models used</span></div>
            </div>
          )}
          {deps.length === 0 && <div className="jv-empty" style={{ padding: 40, textAlign: "center" }}>No deployments yet. Open a flow and hit <b>▲ Deploy</b>.</div>}
          {deps.map((d) => (
            <div key={d.slug} className="pr-card">
              <div className="pr-top">
                <span className="pr-key">{d.slug} <span className="hint">v{d.version} · {d.versions} version{d.versions === 1 ? "" : "s"}</span></span>
                <span className={`tag ${d.active ? "completed" : "failed"}`}>{d.active ? "active" : "inactive"}</span>
              </div>
              <div className="pr-name" style={{ fontWeight: 600 }}>{d.name}</div>
              <div className="dep-copy"><code>{d.url}</code></div>
              <div className="pr-actions">
                <button className="btn btn-ghost btn-sm" onClick={() => setSel(sel === d.slug ? null : d.slug)}>{sel === d.slug ? "Hide" : "Metrics"}</button>
                {d.versions > 1 && <button className="btn btn-ghost btn-sm" title={`Roll back to v${d.version - 1}`} onClick={() => rollback(d.slug, d.version)}>↩ Rollback</button>}
                {d.active && <button className="btn btn-ghost btn-sm btn-stop" onClick={() => deactivate(d.slug)}>Deactivate</button>}
              </div>
              {sel === d.slug && stats && (
                <div className="dep-metrics">
                  <div className="dep-stat"><b>{stats.invocations}</b><span>invocations</span></div>
                  <div className="dep-stat"><b>{Math.round(stats.error_rate * 100)}%</b><span>error rate</span></div>
                  <div className="dep-stat"><b>{stats.p50_ms}</b><span>p50 ms</span></div>
                  <div className="dep-stat"><b>{stats.p95_ms}</b><span>p95 ms</span></div>
                </div>
              )}
              {sel === d.slug && runs.length > 0 && (
                <div className="dep-runs">
                  {runs.slice(0, 10).map((r) => (
                    <div key={r.id} className={`ds-res-row ${r.status === "completed" ? "ok" : "fail"}`}>
                      <span className="ar-icon">{r.status === "completed" ? "✓" : "✕"}</span>
                      <div className="ar-main"><div className="ar-name">run #{r.id} <span className="ar-type">{r.status}</span></div></div>
                      <span className="meta-pill">{r.duration_ms} ms</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
      {toast && <div role="status" aria-live="polite" className="toast">{toast}</div>}
    </div>
  );
}
