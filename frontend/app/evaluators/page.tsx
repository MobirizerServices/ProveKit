"use client";

import { useEffect, useMemo, useState } from "react";
import { api, Calibration, CustomScorer, Evaluator, Experiment, SCORER_KINDS } from "@/lib/api";
import ConsoleShell from "@/components/ConsoleShell";
import PageHero from "@/components/PageHero";

/** The evaluator catalog — every built-in scorer an experiment or automation can run, plus the
 *  real usage each has seen (how many experiments referenced it, and their mean score) and a
 *  judge-vs-human calibration panel driven by /api/experiments/judge-calibration. Nothing here
 *  is fabricated: an unused scorer says "no runs yet", and calibration refuses below min_n. */
const CAT_ICON: Record<string, string> = {
  Correctness: "✓", Trajectory: "↳", RAG: "⌕", Budgets: "$", "Multi-turn": "⇄", Other: "◈",
};

export default function EvaluatorsPage() {
  const [rows, setRows] = useState<Evaluator[] | null>(null);
  const [experiments, setExperiments] = useState<Experiment[]>([]);
  const [cal, setCal] = useState<Calibration | null>(null);
  const [sel, setSel] = useState<string | null>(null);
  // Project-defined rules (#48) — declarative, so online eval can run them server-side.
  const [custom, setCustom] = useState<CustomScorer[]>([]);
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState({ name: "", kind: "contains", value: "", description: "" });
  const [tried, setTried] = useState<Record<number, string>>({});
  const [err, setErr] = useState("");

  useEffect(() => { api.evaluators().then(setRows).catch(() => setRows([])); }, []);
  useEffect(() => { api.experiments().then(setExperiments).catch(() => {}); }, []);
  useEffect(() => { api.judgeCalibration().then(setCal).catch(() => setCal(null)); }, []);
  const loadCustom = () => api.customScorers().then(setCustom).catch(() => setCustom([]));
  useEffect(() => { loadCustom(); }, []);

  const addCustom = async () => {
    setErr("");
    const cfg: Record<string, any> =
      draft.kind === "regex" ? { pattern: draft.value }
      : draft.kind === "json_path" ? { path: draft.value }
      : draft.kind === "length_between" ? { min: 1, max: Number(draft.value) || 500 }
      : { value: draft.value };
    try {
      await api.createCustomScorer({ name: draft.name.trim(), kind: draft.kind, config: cfg,
                                     description: draft.description.trim() });
      setAdding(false); setDraft({ name: "", kind: "contains", value: "", description: "" });
      loadCustom();
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
  };
  const trySample = async (r: CustomScorer) => {
    const out = prompt(`Sample output to score against "${r.name}":`);
    if (out == null) return;
    try {
      const v = await api.tryCustomScorer(r.id, out);
      setTried((t) => ({ ...t, [r.id]: v.applies ? `scored ${v.score}` : "does not apply to that output" }));
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
  };

  // Real per-scorer usage: which experiments referenced this scorer, and its mean across them.
  const usage = useMemo(() => {
    const m = new Map<string, { runs: number; sum: number; n: number }>();
    for (const e of experiments) {
      for (const [name, mean] of Object.entries(e.scorer_means || {})) {
        const u = m.get(name) || { runs: 0, sum: 0, n: 0 };
        u.runs += 1;
        if (mean != null) { u.sum += mean; u.n += 1; }
        m.set(name, u);
      }
    }
    return m;
  }, [experiments]);

  const groups = useMemo(() => {
    const order = ["Correctness", "Trajectory", "RAG", "Budgets", "Multi-turn", "Other"];
    const m = new Map<string, Evaluator[]>();
    for (const e of rows || []) (m.get(e.category) || m.set(e.category, []).get(e.category)!).push(e);
    return order.filter((c) => m.has(c)).map((c) => [c, m.get(c)!] as const);
  }, [rows]);

  return (
    <ConsoleShell>
      <div className="cs-page" style={{ maxWidth: 1220 }}>
        <PageHero eyebrow="Quality" title="Evaluators"
          sub={<>The scorers an experiment or automation can run. Reference one by name in{" "}
            <code className="mono">pk.evaluate(scorers=[…])</code> or attach it to an automation.</>} />

        <div className="evx">
          {/* LEFT — evaluator cards, grouped by what they measure */}
          <div className="evx-cards">
            <div className="ev-group">
              <div className="ev-cat" style={{ display: "flex", alignItems: "center", gap: 10 }}>
                This project&apos;s rules
                <button className="btn btn-sm btn-ghost" onClick={() => setAdding((a) => !a)}>
                  {adding ? "Cancel" : "+ New rule"}</button>
              </div>
              {err && <div className="auth-err" style={{ marginBottom: 10 }}>{err}</div>}
              <p className="muted" style={{ fontSize: 11.5, margin: "0 0 10px", lineHeight: 1.55 }}>
                Rules, not uploaded code — so they run server-side, which is the only way online
                eval can grade a live trace. Python scorers stay client-side in{" "}
                <code className="mono">provekit.scorers</code>.
              </p>

              {adding && (
                <div className="pr-card" style={{ marginBottom: 12 }}>
                  <div className="au-form">
                    <label className="field"><span>Name</span>
                      <input value={draft.name} placeholder="cites_policy"
                        onChange={(e) => setDraft({ ...draft, name: e.target.value })} /></label>
                    <label className="field"><span>Rule</span>
                      <select value={draft.kind} onChange={(e) => setDraft({ ...draft, kind: e.target.value })}>
                        {SCORER_KINDS.map((k) => <option key={k} value={k}>{k}</option>)}
                      </select></label>
                    <label className="field">
                      <span>{draft.kind === "regex" ? "Pattern" : draft.kind === "json_path" ? "Dotted path" : draft.kind === "length_between" ? "Max length" : "Value"}</span>
                      <input value={draft.value}
                        onChange={(e) => setDraft({ ...draft, value: e.target.value })} /></label>
                  </div>
                  <div className="pr-actions">
                    <button className="btn btn-run btn-sm" disabled={!draft.name.trim() || !draft.value.trim()}
                      onClick={addCustom}>Create rule</button>
                  </div>
                </div>
              )}

              {custom.length === 0 ? (
                <p className="muted" style={{ fontSize: 12.5 }}>No project rules yet.</p>
              ) : (
                <div className="evx-grid">
                  {custom.map((r) => (
                    <div key={r.id} className="evx-card" style={{ cursor: "default" }}>
                      <div className="evx-card-top">
                        <span className="evx-icon">◇</span>
                        <span className="evx-cat-badge">{r.kind}</span>
                      </div>
                      <code className="evx-name">{r.name}</code>
                      <p className="evx-desc">{r.description || JSON.stringify(r.config)}</p>
                      {tried[r.id] && <p className="evx-desc" style={{ color: "var(--accent)" }}>{tried[r.id]}</p>}
                      <div style={{ display: "flex", gap: 6 }}>
                        <button className="btn btn-sm btn-ghost" onClick={() => trySample(r)}>Try</button>
                        <button className="btn btn-sm btn-ghost"
                          onClick={async () => { await api.deleteCustomScorer(r.id); loadCustom(); }}>Delete</button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {rows == null ? <div className="muted" style={{ fontSize: 13 }}>Loading…</div>
              : groups.map(([cat, items]) => (
                <div key={cat} className="ev-group">
                  <div className="ev-cat">{cat}</div>
                  <div className="evx-grid">
                    {items.map((e) => {
                      const u = usage.get(e.name);
                      return (
                        <button key={e.name} className={`evx-card ${sel === e.name ? "on" : ""}`} onClick={() => setSel(e.name)}>
                          <div className="evx-card-top">
                            <span className="evx-icon">{CAT_ICON[cat] || "◈"}</span>
                            <span className="evx-cat-badge">{cat}</span>
                          </div>
                          <code className="evx-name">{e.name}</code>
                          <p className="evx-desc">{e.description}</p>
                          <div className="evx-strip">
                            <div><span>Avg score</span><b>{u && u.n ? (u.sum / u.n).toFixed(2) : "—"}</b></div>
                            <div><span>Runs</span><b>{u ? u.runs : 0}</b></div>
                          </div>
                        </button>
                      );
                    })}
                  </div>
                </div>
              ))}
          </div>

          {/* RIGHT — real judge calibration */}
          <aside className="evx-cal">
            <div className="evx-cal-head">Judge calibration</div>
            {cal == null ? <div className="muted au2-empty">Loading…</div>
              : !cal.sufficient ? (
                <div className="evx-cal-body">
                  <AgreementDonut kappa={null} agreement={null} />
                  <div className="evx-cal-verdict warn">Not enough labelled traces</div>
                  <p className="evx-cal-note">{cal.caution || `${cal.n} trace(s) carry both a human label and a judge score — need at least ${cal.min_n}. Add human thumbs on the Traces page to calibrate.`}</p>
                  <Coverage cal={cal} />
                </div>
              ) : (
                <div className="evx-cal-body">
                  <AgreementDonut kappa={cal.kappa} agreement={cal.agreement} />
                  <div className={`evx-cal-verdict ${(cal.kappa ?? 0) >= 0.6 ? "ok" : (cal.kappa ?? 0) >= 0.4 ? "warn" : "bad"}`}>
                    {cal.verdict || "calibrated"}
                  </div>
                  <div className="evx-cal-rates">
                    <div><span>Agreement</span><b>{cal.agreement != null ? `${Math.round(cal.agreement * 100)}%` : "—"}</b></div>
                    <div><span>Cohen's κ</span><b>{cal.kappa != null ? cal.kappa.toFixed(2) : "—"}</b></div>
                    <div><span>False pass</span><b>{cal.false_pass_rate != null ? `${Math.round(cal.false_pass_rate * 100)}%` : "—"}</b></div>
                    <div><span>False fail</span><b>{cal.false_fail_rate != null ? `${Math.round(cal.false_fail_rate * 100)}%` : "—"}</b></div>
                  </div>
                  <div className="evx-cal-label">Confusion (human × judge)</div>
                  <div className="evx-confusion">
                    <div className="evx-cm ok"><span>both pass</span><b>{cal.confusion.both_pass}</b></div>
                    <div className="evx-cm bad"><span>human pass · judge fail</span><b>{cal.confusion.human_pass_judge_fail}</b></div>
                    <div className="evx-cm bad"><span>human fail · judge pass</span><b>{cal.confusion.human_fail_judge_pass}</b></div>
                    <div className="evx-cm ok"><span>both fail</span><b>{cal.confusion.both_fail}</b></div>
                  </div>
                  {cal.disagreement_count > 0 && <p className="evx-cal-note">{cal.disagreement_count} disagreeing trace{cal.disagreement_count === 1 ? "" : "s"} — review them on the Traces page.</p>}
                  <Coverage cal={cal} />
                </div>
              )}
          </aside>
        </div>
      </div>
    </ConsoleShell>
  );
}

function Coverage({ cal }: { cal: Calibration }) {
  return (
    <div className="evx-cov">
      <span>{cal.coverage.human_labelled} human-labelled</span>
      <span>{cal.coverage.judge_scored} judge-scored</span>
      <span>{cal.coverage.both} paired</span>
    </div>
  );
}

function AgreementDonut({ kappa, agreement }: { kappa: number | null; agreement: number | null }) {
  // Kappa is the number that matters; the ring fills to it (clamped 0..1). Agreement sits inside.
  const k = kappa == null ? 0 : Math.max(0, Math.min(1, kappa));
  const r = 40, c = 2 * Math.PI * r;
  const hue = kappa == null ? "var(--border-strong)" : k >= 0.6 ? "var(--green)" : k >= 0.4 ? "var(--amber)" : "var(--red)";
  return (
    <div className="evx-donut">
      <svg width="104" height="104" viewBox="0 0 104 104">
        <circle cx="52" cy="52" r={r} fill="none" stroke="var(--panel-2)" strokeWidth="9" />
        <circle cx="52" cy="52" r={r} fill="none" stroke={hue} strokeWidth="9" strokeLinecap="round"
          strokeDasharray={`${c * k} ${c}`} transform="rotate(-90 52 52)" />
        <text x="52" y="48" textAnchor="middle" fontSize="20" fontWeight="600" fill="var(--text)">{kappa == null ? "—" : kappa.toFixed(2)}</text>
        <text x="52" y="64" textAnchor="middle" fontSize="9" fill="var(--muted)">{agreement != null ? `${Math.round(agreement * 100)}% agree` : "κ"}</text>
      </svg>
    </div>
  );
}
