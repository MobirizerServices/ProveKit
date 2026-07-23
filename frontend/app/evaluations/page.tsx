"use client";

import { useEffect, useMemo, useState } from "react";
import { api, Dataset, Experiment } from "@/lib/api";
import ConsoleShell from "@/components/ConsoleShell";
import PageHero from "@/components/PageHero";

/**
 * Evaluations — the cross-dataset feed of every scored run, newest first. Experiments is the
 * deep per-run view (baselines, per-scorer significance); this is the "what have we measured
 * lately, and did it pass" overview across all datasets, and the quick-start for a first run.
 */
export default function EvaluationsPage() {
  const [rows, setRows] = useState<Experiment[] | null>(null);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  useEffect(() => { api.experiments().then(setRows).catch(() => setRows([])); }, []);
  useEffect(() => { api.datasets().then(setDatasets).catch(() => {}); }, []);

  const dsName = (id: number | null) => datasets.find((d) => d.id === id)?.name || (id ? `#${id}` : "—");
  const scored = useMemo(() => (rows || []).filter((r) => r.result_count > 0), [rows]);
  const passRate = scored.length
    ? Math.round((scored.filter((r) => (r.mean_score ?? 0) >= 0.7).length / scored.length) * 100) : null;

  return (
    <ConsoleShell>
      <div className="cs-page" style={{ maxWidth: 1100 }}>
        <PageHero eyebrow="Quality" title="Evaluations"
          sub="Every scored run across your datasets. Open one in Experiments for the per-scorer breakdown and baseline comparison." />

        {rows == null ? <div className="muted" style={{ fontSize: 13 }}>Loading…</div>
          : scored.length === 0 ? (
            <div className="pr-card">
              <span className="muted">No evaluation results yet. Run{" "}
                <code className="mono">pk.evaluate(dataset, target)</code> against a dataset, or score an
                edited prompt from a trace. Results land here and in Experiments.</span>
            </div>
          ) : (
            <>
              <div className="ev-stats">
                <div className="ev-stat"><span>Scored runs</span><b>{scored.length}</b></div>
                <div className="ev-stat"><span>Datasets covered</span><b>{new Set(scored.map((r) => r.dataset_id)).size}</b></div>
                <div className="ev-stat"><span>Pass rate</span><b>{passRate}%</b><small>score ≥ 0.70</small></div>
              </div>

              <div className="ev-feed">
                {scored.map((r) => {
                  const score = r.mean_score != null ? r.mean_score * 100 : null;
                  const pass = (r.mean_score ?? 0) >= 0.7;
                  return (
                    <a key={r.id} href="/experiments" className="ev-run">
                      <span className={`ev-run-dot ${pass ? "ok" : "warn"}`} />
                      <span className="ev-run-main">
                        <b>{r.name || `experiment ${r.id}`}</b>
                        <small>{dsName(r.dataset_id)} · {r.result_count} result{r.result_count === 1 ? "" : "s"}</small>
                      </span>
                      <span className="ev-run-scorers">
                        {Object.keys(r.scorer_means || {}).slice(0, 4).map((s) => <em key={s}>{s}</em>)}
                      </span>
                      <span className="ev-run-score">{score != null ? score.toFixed(1) : "—"}</span>
                      <span className="ev-run-time">{new Date(r.created_at).toLocaleDateString()}</span>
                    </a>
                  );
                })}
              </div>
            </>
          )}
      </div>
    </ConsoleShell>
  );
}
