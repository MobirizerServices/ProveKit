"use client";

import { useEffect, useMemo, useState } from "react";
import {
  api, Dataset, Experiment, ExperimentComparison, ExperimentTriage, ScorerComparison,
} from "@/lib/api";
import ConsoleShell from "@/components/ConsoleShell";
import PageHero from "@/components/PageHero";
import Empty from "@/components/Empty";

/**
 * Experiments — a baseline-vs-candidate scorecard, matching the reference console.
 *
 * The comparison leads with significance, not the raw delta: a +4% mean the backend flags as
 * not significant is noise, and the "Decision evidence" list marks each scorer Improved /
 * Regressed / Passed by whether the move is real, not by its sign. The promote verdict comes
 * from the per-item triage (how many rows got better vs. crossed pass→fail), so "safe to
 * promote" is a fact about the rows, not a guess from the averages.
 */
export default function ExperimentsPage() {
  const [rows, setRows] = useState<Experiment[] | null>(null);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [sel, setSel] = useState<number | null>(null);          // candidate
  const [baseline, setBaseline] = useState<number | null>(null);
  const [cmp, setCmp] = useState<ExperimentComparison | null>(null);
  const [triage, setTriage] = useState<ExperimentTriage | null>(null);
  const [cmpErr, setCmpErr] = useState("");
  const [filter, setFilter] = useState<number | "">("");
  const [copied, setCopied] = useState(false);

  useEffect(() => { api.experiments().then(setRows).catch(() => setRows([])); }, []);
  useEffect(() => { api.datasets().then(setDatasets).catch(() => {}); }, []);

  const list = useMemo(
    () => (rows || []).filter((r) => filter === "" || r.dataset_id === filter),
    [rows, filter]);
  useEffect(() => {
    if (sel != null || !list.length) return;
    setSel((list.find((r) => r.result_count > 0) || list[0]).id);
  }, [list, sel]);

  const candidate = list.find((r) => r.id === sel) || null;
  // Runs over the same dataset are the only valid baselines — comparing across data isn't one.
  const baselineOptions = useMemo(
    () => list.filter((r) => r.id !== sel && r.dataset_id === candidate?.dataset_id && r.result_count > 0),
    [list, sel, candidate]);

  // Auto-pick the most recent other run over this dataset as the baseline, so the scorecard
  // shows a real comparison by default rather than a lonely single score.
  useEffect(() => {
    if (candidate == null) { setBaseline(null); return; }
    setBaseline((prev) => (prev != null && baselineOptions.some((o) => o.id === prev))
      ? prev : (baselineOptions[0]?.id ?? null));
  }, [candidate, baselineOptions]);

  const base = list.find((r) => r.id === baseline) || null;

  useEffect(() => {
    setCmp(null); setTriage(null); setCmpErr(""); setCopied(false);
    if (sel == null || baseline == null) return;
    api.compareExperiments(baseline, sel).then(setCmp)
      .catch((e) => setCmpErr(e instanceof Error ? e.message : String(e)));
    api.triageExperiments(baseline, sel).then(setTriage).catch(() => {});
  }, [sel, baseline]);

  const dsName = (id: number | null) => datasets.find((d) => d.id === id)?.name || (id ? `#${id}` : "—");
  const running = (r: Experiment) => r.result_count === 0;
  const runningCount = list.filter(running).length;

  return (
    <ConsoleShell>
      <div className="cs-page" style={{ maxWidth: 1320 }}>
        <PageHero eyebrow="Controlled comparison" title="Experiments"
          sub="Compare every prompt, model, and retrieval change against trusted evidence."
          actions={
            <select className="reg-sel" value={filter}
              onChange={(e) => { setFilter(e.target.value === "" ? "" : Number(e.target.value)); setSel(null); }}>
              <option value="">All datasets</option>
              {datasets.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
            </select>}
          status={list.length > 0 &&
            <><span className="dot" />{runningCount} running · {list.length - runningCount} result{list.length - runningCount === 1 ? "" : "s"} ready</>} />

        {rows == null ? (
          <div className="muted" style={{ fontSize: 13 }}>Loading…</div>
        ) : list.length === 0 ? (
          <Empty
            what="An experiment is one scored run of your agent over a dataset."
            why="Two of them side by side is how you tell whether a prompt or model change actually helped, instead of guessing from a handful of examples."
            action={{ label: "Create a dataset first", href: "/datasets" }}
            note="Once a dataset exists, pk.evaluate(dataset, target) records an experiment here."
          />
        ) : (
          <div className="xp2">
            {/* ── candidate list ── */}
            <div className="reg-list">
              {list.map((r) => (
                <button key={r.id} className={`reg-item ${sel === r.id ? "on" : ""}`}
                  onClick={() => setSel(r.id)}>
                  <div className="reg-item-name">{r.name || `experiment ${r.id}`}</div>
                  <div className="reg-item-sub">
                    {dsName(r.dataset_id)} · {running(r) ? "running" : `${(r.mean_score! * 100).toFixed(1)}`}
                  </div>
                </button>
              ))}
            </div>

            {/* ── scorecard + decision evidence ── */}
            {!candidate ? (
              <div className="pr-card"><span className="muted">Select a run.</span></div>
            ) : (
              <div className="xp2-body">
                <section className="xp-scorecard">
                  <div className="xp-sc-head">
                    <div>
                      <span className={`xp-sc-tag ${running(candidate) ? "run" : ""}`}>
                        {running(candidate) ? "Running" : "Result ready"}
                      </span>
                      <h2>{candidate.name || `experiment ${candidate.id}`}</h2>
                      <div className="xp-sc-sub">
                        {dsName(candidate.dataset_id)}
                        {candidate.dataset_version ? ` v${candidate.dataset_version}` : ""} ·{" "}
                        {candidate.result_count} example{candidate.result_count === 1 ? "" : "s"} · exp_{candidate.id}
                      </div>
                    </div>
                    {base && (
                      <label className="xp-base-pick">
                        <span>Baseline</span>
                        <select className="reg-sel" value={baseline ?? ""}
                          onChange={(e) => setBaseline(e.target.value === "" ? null : Number(e.target.value))}>
                          {baselineOptions.map((o) => (
                            <option key={o.id} value={o.id}>{o.name || `experiment ${o.id}`}</option>
                          ))}
                        </select>
                      </label>
                    )}
                  </div>

                  {cmpErr && <div className="auth-err">{cmpErr}</div>}

                  {!base ? (
                    <div className="xp-single">
                      <ScoreColumn label="Result" exp={candidate} tone="var(--accent)" />
                      <div className="xp-single-note muted">
                        No prior run over <b>{dsName(candidate.dataset_id)}</b> to compare against.
                        Run another to get a baseline scorecard.
                      </div>
                    </div>
                  ) : (
                    <>
                      <div className="xp-compare2">
                        <ScoreColumn label="Baseline" exp={base} tone="var(--blue)" />
                        <Uplift base={base} cand={candidate} cmp={cmp} />
                        <ScoreColumn label="Candidate" exp={candidate} tone="var(--accent)" />
                      </div>
                      <PromoteBanner triage={triage} cmp={cmp} />
                    </>
                  )}
                </section>

                {base && (
                  <aside className="xp-evidence">
                    <div className="xp-ev-head">
                      <span className="xp-ev-ic">◈</span>
                      <div><b>Decision evidence</b><small>Guardrails and confidence</small></div>
                    </div>
                    {!cmp ? <div className="muted" style={{ fontSize: 12.5, padding: 12 }}>Comparing…</div>
                      : cmp.warning ? <div className="xp-warn">{cmp.warning}</div>
                      : Object.keys(cmp.scorers).length === 0
                        ? <div className="muted" style={{ fontSize: 12.5, padding: 12 }}>No shared scorers to compare.</div>
                        : (
                          <>
                            {Object.entries(cmp.scorers).map(([name, c]) => <EvidenceRow key={name} name={name} c={c} />)}
                            <button className="xp-ev-export" onClick={() => {
                              navigator.clipboard?.writeText(JSON.stringify({ comparison: cmp, triage }, null, 2));
                              setCopied(true);
                            }}>
                              {copied ? "Copied ✓" : "Copy evidence →"}
                            </button>
                          </>
                        )}
                  </aside>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </ConsoleShell>
  );
}

/** One side of the scorecard: big score, per-scorer bars (real means), and the run's provenance. */
function ScoreColumn({ label, exp, tone }: { label: string; exp: Experiment; tone: string }) {
  const bars = Object.entries(exp.scorer_means || {});
  const model = (exp.config?.model as string) || undefined;
  return (
    <div className="xp-col">
      <div className="xp-col-top">
        <span className="xp-col-label">{label}</span>
        {model && <span className="xp-col-model">{model}</span>}
      </div>
      <div className="xp-col-score">{exp.mean_score != null ? (exp.mean_score * 100).toFixed(1) : "—"}</div>
      <div className="xp-col-cap">quality score</div>
      <div className="xp-bars" style={{ ["--bar" as string]: tone }}>
        {bars.length === 0 ? <span className="muted" style={{ fontSize: 11 }}>no scorers</span>
          : bars.map(([n, v]) => (
            <span key={n} className="xp-bar" style={{ height: `${Math.max(6, v * 100)}%` }} title={`${n}: ${(v * 100).toFixed(0)}`} />
          ))}
      </div>
      <div className="xp-col-foot">
        <span><b>{exp.result_count}</b> examples</span>
        <span>{Object.keys(exp.scorer_means || {}).length} scorer{Object.keys(exp.scorer_means || {}).length === 1 ? "" : "s"}</span>
      </div>
    </div>
  );
}

/** The center column: the mean-score uplift and how confident we are it's real. */
function Uplift({ base, cand, cmp }: { base: Experiment; cand: Experiment; cmp: ExperimentComparison | null }) {
  const up = cand.mean_score != null && base.mean_score != null
    ? (cand.mean_score - base.mean_score) * 100 : null;
  // Confidence from the smallest p-value across scorers — the strongest evidence of a real move.
  const ps = cmp ? Object.values(cmp.scorers).map((c) => c.p_value).filter((p): p is number => p != null) : [];
  const conf = ps.length ? (1 - Math.min(...ps)) * 100 : null;
  const anySig = cmp ? Object.values(cmp.scorers).some((c) => c.significant) : false;
  return (
    <div className="xp-mid">
      <div className={`xp-up ${up != null && up >= 0 ? "pos" : "neg"}`}>
        <span className="xp-up-arrow">{up != null && up >= 0 ? "↑" : "↓"}</span>
        {up != null ? `${up >= 0 ? "+" : ""}${up.toFixed(1)}` : "—"}
      </div>
      <div className="xp-up-cap">quality uplift</div>
      {conf != null && (
        <span className={`xp-conf ${anySig ? "ok" : "warn"}`}>
          {anySig ? `${conf.toFixed(1)}% confidence` : "not significant"}
        </span>
      )}
    </div>
  );
}

/** One scorer's verdict in the Decision-evidence list. Status is set by significance, not sign. */
function EvidenceRow({ name, c }: { name: string; c: ScorerComparison }) {
  const d = c.delta;
  let status: "Improved" | "Regressed" | "Passed" | "No change", cls: string;
  if (d == null || Math.abs(d) < 0.005) { status = "No change"; cls = "flat"; }
  else if (c.significant && d > 0) { status = "Improved"; cls = "up"; }
  else if (c.significant && d < 0) { status = "Regressed"; cls = "down"; }
  else { status = "Passed"; cls = "flat"; }
  const pill = d == null ? "—" : status === "No change" ? "NO CHANGE" : `${d >= 0 ? "+" : ""}${(d * 100).toFixed(1)}`;
  return (
    <div className="xp-ev-row">
      <div className="xp-ev-main">
        <b>{prettyScorer(name)}</b>
        <small>{status}</small>
      </div>
      <span className={`xp-ev-pill ${cls}`} title={c.caution || (c.p_value != null ? `p = ${c.p_value.toFixed(4)}` : "")}>{pill}</span>
    </div>
  );
}

/** The promote verdict — from the per-item triage, not the averages. */
function PromoteBanner({ triage, cmp }: { triage: ExperimentTriage | null; cmp: ExperimentComparison | null }) {
  if (!triage || !triage.comparable) return null;
  const agg = Object.values(triage.scorers).reduce(
    (a, s) => ({
      improved: a.improved + s.improved_count,
      regressed: a.regressed + s.regressed_count,
      unchanged: a.unchanged + s.unchanged,
      breaks: a.breaks + s.pass_to_fail,
    }), { improved: 0, regressed: 0, unchanged: 0, breaks: 0 });
  // A significant negative scorer OR any pass→fail row means it isn't a clean promote.
  const sigRegression = cmp ? Object.values(cmp.scorers).some((c) => c.significant && (c.delta ?? 0) < 0) : false;
  const safe = !sigRegression && agg.breaks === 0 && agg.improved >= agg.regressed;
  return (
    <div className={`xp-promote ${safe ? "ok" : "warn"}`}>
      <span className="xp-promote-ic">{safe ? "✓" : "⚠"}</span>
      <div>
        <b>{safe ? "Candidate is safe to promote" : "Candidate needs review before promoting"}</b>
        <small>
          {agg.improved.toLocaleString()} improvement{agg.improved === 1 ? "" : "s"},{" "}
          {agg.unchanged.toLocaleString()} neutral,{" "}
          {agg.regressed.toLocaleString()} regression{agg.regressed === 1 ? "" : "s"}
          {agg.breaks > 0 ? ` · ${agg.breaks} pass→fail` : ""}
        </small>
      </div>
    </div>
  );
}

function prettyScorer(name: string): string {
  return name.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}
