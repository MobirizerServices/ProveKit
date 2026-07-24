"use client";

import { useEffect, useState } from "react";
import { api, Automation, Dataset, Evaluator } from "@/lib/api";
import ConsoleShell from "@/components/ConsoleShell";
import PageHero from "@/components/PageHero";

/**
 * Automations — standing rules that route production traces into a dataset and (optionally)
 * score them, so real failures become versioned test cases without anyone copy-pasting. Full
 * CRUD against /api/automation. The layout mirrors the reference console: a rule registry on
 * the left, a WHEN / IF / THEN breakdown of the selected rule on the right. "Run now" applies
 * a rule to existing traces and reports how many were considered, matched, and acted on.
 */
export default function AutomationsPage() {
  const [rows, setRows] = useState<Automation[] | null>(null);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [evaluators, setEvaluators] = useState<Evaluator[]>([]);
  const [sel, setSel] = useState<number | null>(null);
  const [creating, setCreating] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [ran, setRan] = useState<Record<number, string>>({});

  // create-form state
  const [name, setName] = useState("");
  const [status, setStatus] = useState("failed");
  const [target, setTarget] = useState<number | "">("");
  const [scorers, setScorers] = useState<string[]>([]);

  const load = () => api.automations().then((r) => {
    setRows(r);
    setSel((s) => (s != null && r.some((x) => x.id === s)) ? s : (r[0]?.id ?? null));
  }).catch(() => setRows([]));
  useEffect(() => { load(); }, []);
  useEffect(() => { api.datasets().then(setDatasets).catch(() => {}); }, []);
  useEffect(() => { api.evaluators().then(setEvaluators).catch(() => {}); }, []);

  const dsName = (id: number | null) => datasets.find((d) => d.id === id)?.name || (id ? `#${id}` : "—");

  const startCreate = () => { setCreating(true); setSel(null); setName(""); setStatus("failed"); setTarget(""); setScorers([]); };

  const create = async () => {
    setBusy(true); setErr("");
    try {
      const created = await api.createAutomation({
        name: name.trim() || "promote failures",
        match: status ? { status } : {},
        action: "promote",
        target_dataset_id: target === "" ? null : Number(target),
        scorers, sample: 1, enabled: true,
      });
      setCreating(false); setName(""); setScorers([]); setTarget("");
      await load();
      if (created?.id) setSel(created.id);
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  };

  const del = async (id: number) => { await api.deleteAutomation(id); setSel(null); load(); };
  const toggle = async (r: Automation) => {
    setErr("");
    try { await api.updateAutomation(r.id, { enabled: !r.enabled }); load(); }
    catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
  };
  const runNow = async (id: number) => {
    setErr("");
    try {
      const r = await api.runAutomation(id);
      setRan((s) => ({ ...s, [id]: `considered ${r.considered} · matched ${r.matched} · acted ${r.acted}` }));
      load();
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
  };

  const current = (rows || []).find((r) => r.id === sel) || null;

  return (
    <ConsoleShell>
      <div className="cs-page" style={{ maxWidth: 1120 }}>
        <PageHero eyebrow="Control" title="Automations"
          sub="Turn matching production traces into dataset items automatically — so a real failure becomes a regression test without anyone lifting it by hand."
          actions={<button className="btn-hero solid" onClick={startCreate}>+ New rule</button>} />

        {err && <div className="auth-err" style={{ marginBottom: 14 }}>{err}</div>}

        <div className="au2">
          {/* LEFT — rule registry */}
          <aside className="au2-list">
            <div className="au2-list-head">Rules<span className="au2-count">{rows?.length ?? 0}</span></div>
            {rows == null ? <div className="muted au2-empty">Loading…</div>
              : rows.length === 0 ? <div className="muted au2-empty">No rules yet.</div>
              : rows.map((r) => (
                <button key={r.id} className={`au2-rule ${sel === r.id && !creating ? "on" : ""}`}
                  onClick={() => { setSel(r.id); setCreating(false); }}>
                  <span className="au2-bell">◆</span>
                  <span className="au2-rule-main">
                    <span className="au2-rule-name">{r.name}</span>
                    <span className="au2-rule-cond">trace is {r.match?.status || "any"} → {dsName(r.target_dataset_id)}</span>
                  </span>
                  <span className={`au2-state ${r.enabled ? "on" : ""}`}>{r.enabled ? "ACTIVE" : "PAUSED"}</span>
                </button>
              ))}
          </aside>

          {/* RIGHT — create form OR rule detail */}
          <section className="au2-detail">
            {creating ? (
              <>
                <div className="au2-detail-head"><h2>New rule</h2></div>
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
                  <button className="btn btn-ghost btn-sm" onClick={() => { setCreating(false); setSel(rows?.[0]?.id ?? null); }}>Cancel</button>
                </div>
              </>
            ) : !current ? (
              <div className="muted au2-empty" style={{ padding: 40 }}>Select a rule, or create one to route traces into a dataset.</div>
            ) : (
              <>
                <div className="au2-detail-head">
                  <h2>{current.name}</h2>
                  <div className="au2-detail-actions">
                    <button className={`au2-toggle ${current.enabled ? "on" : ""}`} onClick={() => toggle(current)}
                      title={current.enabled ? "Pause rule" : "Activate rule"}>
                      <span className="au2-toggle-knob" /></button>
                    <span className="muted" style={{ fontSize: 12 }}>{current.enabled ? "Active" : "Paused"}</span>
                  </div>
                </div>

                {/* WHEN / IF / THEN — the shape of the rule */}
                <div className="au2-flow">
                  <div className="au2-step">
                    <div className="au2-step-tag when">WHEN</div>
                    <div className="au2-step-body">
                      <div className="au2-step-title">A production trace is captured</div>
                      <div className="au2-step-sub">Every trace ingested into this project is evaluated against the rule.</div>
                    </div>
                  </div>
                  <div className="au2-arrow">↓</div>
                  <div className="au2-step">
                    <div className="au2-step-tag iff">IF</div>
                    <div className="au2-step-body">
                      <div className="au2-step-title">Status is <b>{current.match?.status || "any status"}</b></div>
                      <div className="au2-step-sub">
                        {current.sample >= 1 ? "Every matching trace" : `Sampled at ${Math.round((current.sample || 1) * 100)}%`}
                      </div>
                    </div>
                  </div>
                  <div className="au2-arrow">↓</div>
                  <div className="au2-step">
                    <div className="au2-step-tag then">THEN</div>
                    <div className="au2-step-body">
                      <div className="au2-step-title">Add to <b>{dsName(current.target_dataset_id)}</b></div>
                      <div className="au2-step-sub">
                        {current.scorers.length > 0
                          ? <>Score with {current.scorers.map((s) => <span key={s} className="au2-scorer">{s}</span>)}</>
                          : "No scorers — promote the item unscored."}
                      </div>
                    </div>
                  </div>
                </div>

                <div className="au2-detail-foot">
                  <button className="btn btn-sm" onClick={() => runNow(current.id)}>Test rule (run now)</button>
                  <button className="btn btn-sm btn-ghost" onClick={() => del(current.id)}
                    style={{ borderColor: "var(--red)", color: "var(--red)" }}>Delete</button>
                </div>

                {/* Execution history — persisted lifetime counters from the backend, plus the
                    most recent run this session if the rule was tested here. */}
                <div className="au2-hist">
                  <div className="au2-hist-head">Execution history</div>
                  <div className="au2-hist-row">
                    <span className={`au2-hist-dot ${current.last_status === "ok" || (current.acted ?? 0) > 0 ? "ok" : ""}`} />
                    Lifetime: matched <b>{current.matched ?? 0}</b> · acted <b>{current.acted ?? 0}</b>
                    {current.last_status ? <> · last status <em>{current.last_status}</em></> : null}
                  </div>
                  {ran[current.id]
                    ? <div className="au2-hist-row"><span className="au2-hist-dot ok" />This session: {ran[current.id]}</div>
                    : <div className="au2-hist-row muted"><span className="au2-hist-dot" />Test rule to apply it to existing traces now.</div>}
                </div>
              </>
            )}
          </section>
        </div>
      </div>
    </ConsoleShell>
  );
}
