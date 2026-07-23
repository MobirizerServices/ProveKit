"use client";

import { useEffect, useState } from "react";
import { api, Automation, Dataset, Evaluator } from "@/lib/api";
import ConsoleShell from "@/components/ConsoleShell";
import PageHero from "@/components/PageHero";

/**
 * Automations — standing rules that route production traces into a dataset and (optionally)
 * score them, so real failures become versioned test cases without anyone copy-pasting. Full
 * CRUD against /api/automation; the "Run now" button applies a rule to existing traces.
 */
export default function AutomationsPage() {
  const [rows, setRows] = useState<Automation[] | null>(null);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [evaluators, setEvaluators] = useState<Evaluator[]>([]);
  const [creating, setCreating] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [ran, setRan] = useState<Record<number, string>>({});

  // create-form state
  const [name, setName] = useState("");
  const [status, setStatus] = useState("failed");
  const [target, setTarget] = useState<number | "">("");
  const [scorers, setScorers] = useState<string[]>([]);

  const load = () => api.automations().then(setRows).catch(() => setRows([]));
  useEffect(() => { load(); }, []);
  useEffect(() => { api.datasets().then(setDatasets).catch(() => {}); }, []);
  useEffect(() => { api.evaluators().then(setEvaluators).catch(() => {}); }, []);

  const dsName = (id: number | null) => datasets.find((d) => d.id === id)?.name || (id ? `#${id}` : "—");

  const create = async () => {
    setBusy(true); setErr("");
    try {
      await api.createAutomation({
        name: name.trim() || "promote failures",
        match: status ? { status } : {},
        action: "promote",
        target_dataset_id: target === "" ? null : Number(target),
        scorers, sample: 1, enabled: true,
      });
      setCreating(false); setName(""); setScorers([]); setTarget("");
      await load();
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  };

  const del = async (id: number) => { await api.deleteAutomation(id); load(); };
  const runNow = async (id: number) => {
    setErr("");
    try {
      const r = await api.runAutomation(id);
      setRan((s) => ({ ...s, [id]: `considered ${r.considered}, matched ${r.matched}, acted ${r.acted}` }));
      load();
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
  };

  return (
    <ConsoleShell>
      <div className="cs-page" style={{ maxWidth: 1000 }}>
        <PageHero eyebrow="Control" title="Automations"
          sub="Turn matching production traces into dataset items automatically — so a real failure becomes a regression test without anyone lifting it by hand."
          actions={!creating && <button className="btn-hero solid" onClick={() => setCreating(true)}>+ New rule</button>} />

        {err && <div className="auth-err" style={{ marginBottom: 14 }}>{err}</div>}

        {creating && (
          <div className="pr-card" style={{ marginBottom: 16 }}>
            <div className="au-form">
              <label className="field"><span>Name</span>
                <input value={name} onChange={(e) => setName(e.target.value)} placeholder="promote failures" /></label>
              <label className="field"><span>When a trace is</span>
                <select value={status} onChange={(e) => setStatus(e.target.value)}>
                  <option value="failed">failed</option>
                  <option value="completed">completed</option>
                  <option value="">any status</option>
                </select></label>
              <label className="field"><span>Add it to dataset</span>
                <select value={target} onChange={(e) => setTarget(e.target.value === "" ? "" : Number(e.target.value))}>
                  <option value="">Select a dataset…</option>
                  {datasets.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
                </select></label>
            </div>
            <div className="au-scorers">
              <span className="field-label">Score with</span>
              <div className="au-chips">
                {evaluators.map((e) => (
                  <button key={e.name} className={`au-chip ${scorers.includes(e.name) ? "on" : ""}`}
                    onClick={() => setScorers((s) => s.includes(e.name) ? s.filter((x) => x !== e.name) : [...s, e.name])}
                    title={e.description}>{e.name}</button>
                ))}
              </div>
            </div>
            <div className="pr-actions">
              <button className="btn btn-run btn-sm" disabled={busy || target === ""} onClick={create}>Create rule</button>
              <button className="btn btn-ghost btn-sm" onClick={() => setCreating(false)}>Cancel</button>
            </div>
          </div>
        )}

        {rows == null ? <div className="muted" style={{ fontSize: 13 }}>Loading…</div>
          : rows.length === 0 && !creating ? (
            <div className="pr-card"><span className="muted">No automations yet. Create a rule to
              route matching traces into a dataset.</span></div>
          ) : (
            <div className="au-list">
              {(rows || []).map((r) => (
                <div key={r.id} className="au-card">
                  <div className="au-card-main">
                    <div className="au-card-top">
                      <b>{r.name}</b>
                      <span className={`au-state ${r.enabled ? "on" : ""}`}>{r.enabled ? "enabled" : "off"}</span>
                    </div>
                    <div className="au-rule">
                      when a trace is <em>{r.match?.status || "any"}</em> → add to{" "}
                      <em>{dsName(r.target_dataset_id)}</em>
                      {r.scorers.length > 0 && <> · score with {r.scorers.map((s) => <em key={s}>{s}</em>)}</>}
                    </div>
                    {ran[r.id] && <div className="au-ran">✓ {ran[r.id]}</div>}
                  </div>
                  <div className="au-card-actions">
                    <button className="btn btn-sm" onClick={() => runNow(r.id)}>Run now</button>
                    <button className="btn btn-sm btn-ghost" onClick={() => del(r.id)}>Delete</button>
                  </div>
                </div>
              ))}
            </div>
          )}
      </div>
    </ConsoleShell>
  );
}
