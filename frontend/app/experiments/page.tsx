"use client";

import { useEffect, useMemo, useState } from "react";
import { api, Dataset, Experiment, ExperimentComparison, ScorerComparison } from "@/lib/api";
import TopNav from "@/components/TopNav";

/**
 * Experiment results: what a scored run actually says, and whether the difference from a
 * baseline is real.
 *
 * The comparison view leads with significance rather than the delta. A +4% mean that the
 * backend flags as not significant is noise, and showing it as a win is the specific mistake
 * this page exists to prevent.
 */
export default function ExperimentsPage() {
  const [rows, setRows] = useState<Experiment[] | null>(null);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [sel, setSel] = useState<number | null>(null);
  const [baseline, setBaseline] = useState<number | null>(null);
  const [cmp, setCmp] = useState<ExperimentComparison | null>(null);
  const [cmpErr, setCmpErr] = useState("");
  const [filter, setFilter] = useState<number | "">("");

  useEffect(() => { api.experiments().then(setRows).catch(() => setRows([])); }, []);
  useEffect(() => { api.datasets().then(setDatasets).catch(() => {}); }, []);

  const list = useMemo(
    () => (rows || []).filter((r) => filter === "" || r.dataset_id === filter),
    [rows, filter]);
  // Prefer a run with results — opening on an empty one shows a page of dashes.
  useEffect(() => {
    if (sel != null || !list.length) return;
    setSel((list.find((r) => r.result_count > 0) || list[0]).id);
  }, [list, sel]);

  const current = list.find((r) => r.id === sel) || null;
  // Same dataset only — comparing runs over different data isn't a comparison.
  const candidates = useMemo(
    () => list.filter((r) => r.id !== sel && r.dataset_id === current?.dataset_id),
    [list, sel, current]);

  useEffect(() => {
    setCmp(null); setCmpErr("");
    if (sel == null || baseline == null) return;
    api.compareExperiments(baseline, sel).then(setCmp)
      .catch((e) => setCmpErr(e instanceof Error ? e.message : String(e)));
  }, [sel, baseline]);

  const dsName = (id: number | null) => datasets.find((d) => d.id === id)?.name || (id ? `#${id}` : "—");

  return (
    <>
      <TopNav />
      <div className="page">
        <div className="page-inner" style={{ maxWidth: 1180 }}>
          <div className="page-head">
            <div>
              <div className="page-eyebrow">Quality</div>
              <h1>Experiments</h1>
              <p>
                Scored runs over a dataset. Pick a baseline to see whether a change is a real
                improvement or inside the noise.
              </p>
            </div>
            <div className="spacer" />
            <select className="reg-sel" value={filter}
              onChange={(e) => { setFilter(e.target.value === "" ? "" : Number(e.target.value)); setSel(null); setBaseline(null); }}>
              <option value="">All datasets</option>
              {datasets.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
            </select>
          </div>

          {rows == null ? (
            <div className="muted" style={{ fontSize: 13 }}>Loading…</div>
          ) : list.length === 0 ? (
            <div className="pr-card">
              <span className="muted">
                No experiments yet. Run <code className="mono">pk.evaluate()</code> against a dataset, or
                score an edited prompt from the trace playground.
              </span>
            </div>
          ) : (
            <div className="reg-grid">
              <div className="reg-list">
                {list.map((r) => (
                  <button key={r.id} className={`reg-item ${sel === r.id ? "on" : ""}`}
                    onClick={() => { setSel(r.id); setBaseline(null); }}>
                    <div className="reg-item-name">{r.name || `experiment ${r.id}`}</div>
                    <div className="reg-item-sub">
                      {dsName(r.dataset_id)} · {r.result_count} result{r.result_count === 1 ? "" : "s"}
                      {r.mean_score != null ? ` · ${(r.mean_score * 100).toFixed(1)}` : ""}
                    </div>
                  </button>
                ))}
              </div>

              <div>
                {!current ? (
                  <div className="pr-card"><span className="muted">Select an experiment.</span></div>
                ) : (
                  <>
                    <div className="xp-head">
                      <div>
                        <div className="xp-eyebrow">Overall score</div>
                        <div className="xp-score">
                          {current.mean_score != null ? (current.mean_score * 100).toFixed(1) : "—"}
                        </div>
                        {cmp && <Delta cmp={cmp} />}
                      </div>
                      <ScoreRing value={current.mean_score != null ? current.mean_score * 100 : 0} />
                    </div>

                    <div className="xp-meta">
                      <span><b>{current.result_count}</b> results</span>
                      <span>dataset <b>{dsName(current.dataset_id)}</b></span>
                      <span>{new Date(current.created_at).toLocaleString()}</span>
                    </div>

                    <div className="xp-scorers">
                      {Object.keys(current.scorer_means || {}).length === 0 ? (
                        <span className="muted" style={{ fontSize: 13 }}>
                          This experiment has no scorer results yet.
                        </span>
                      ) : (
                        Object.entries(current.scorer_means).map(([name, mean]) => {
                          const stats = current.scorer_stats?.[name];
                          const c = cmp?.scorers?.[name];
                          return (
                            <div key={name} className="xp-row">
                              <span className="xp-row-name">{name}</span>
                              <span className="xp-track">
                                <span className="xp-fill" style={{ width: `${clamp(mean * 100)}%` }} />
                              </span>
                              <b className="xp-row-val">{(mean * 100).toFixed(0)}</b>
                              {c ? <ScorerVerdict c={c} /> : stats?.n ? (
                                <span className="xp-n muted">n={stats.n}</span>
                              ) : null}
                            </div>
                          );
                        })
                      )}
                    </div>

                    {/* ---------------- baseline comparison ---------------- */}
                    <div className="xp-cmp">
                      <div className="xp-cmp-head">
                        <span className="xp-eyebrow">Compare against a baseline</span>
                        <select className="reg-sel" value={baseline ?? ""}
                          onChange={(e) => setBaseline(e.target.value === "" ? null : Number(e.target.value))}>
                          <option value="">No baseline</option>
                          {candidates.map((r) => (
                            <option key={r.id} value={r.id}>{r.name || `experiment ${r.id}`}</option>
                          ))}
                        </select>
                      </div>
                      {candidates.length === 0 && (
                        <span className="muted" style={{ fontSize: 12.5 }}>
                          No other run over <b>{dsName(current.dataset_id)}</b> to compare with.
                        </span>
                      )}
                      {cmpErr && <div className="auth-err" style={{ marginTop: 10 }}>{cmpErr}</div>}
                      {cmp?.warning && <div className="xp-warn">{cmp.warning}</div>}
                      {cmp && (
                        <p className="muted" style={{ fontSize: 12.5, margin: "10px 0 0" }}>
                          Significance at α={cmp.alpha}. A delta without significance is noise —
                          collect more results before acting on it.
                        </p>
                      )}
                    </div>
                  </>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </>
  );
}

/** Per-scorer verdict: the delta, and whether the backend considers it real. */
function ScorerVerdict({ c }: { c: ScorerComparison }) {
  if (c.delta == null) return <span className="xp-n muted">—</span>;
  const pct = (c.delta * 100).toFixed(1);
  const better = c.delta > 0;
  return (
    <span className={`xp-verdict ${c.significant ? (better ? "up" : "down") : "flat"}`}
      title={c.caution || (c.p_value != null ? `p = ${c.p_value.toFixed(4)}` : "")}>
      {better ? "+" : ""}{pct}
      <em>{c.significant ? "significant" : "noise"}</em>
    </span>
  );
}

function Delta({ cmp }: { cmp: ExperimentComparison }) {
  const deltas = Object.values(cmp.scorers || {}).map((s) => s.delta).filter((d): d is number => d != null);
  if (!deltas.length) return null;
  const mean = deltas.reduce((a, b) => a + b, 0) / deltas.length;
  const anySig = Object.values(cmp.scorers).some((s) => s.significant);
  return (
    <div className={`xp-delta ${anySig ? (mean >= 0 ? "up" : "down") : "flat"}`}>
      {mean >= 0 ? "+" : ""}{(mean * 100).toFixed(1)}%
      <span>{anySig ? "vs baseline" : "not significant"}</span>
    </div>
  );
}

function ScoreRing({ value }: { value: number }) {
  const r = 38, c = 2 * Math.PI * r, v = clamp(value);
  return (
    <div className="xp-ring">
      <svg viewBox="0 0 88 88">
        <circle className="xp-ring-bg" cx="44" cy="44" r={r} />
        <circle className="xp-ring-fg" cx="44" cy="44" r={r}
          strokeDasharray={c} strokeDashoffset={c * (1 - v / 100)} />
      </svg>
      <b>{Math.round(v)}</b>
    </div>
  );
}

const clamp = (n: number) => Math.max(0, Math.min(100, n));
