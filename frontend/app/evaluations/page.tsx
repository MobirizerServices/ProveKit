"use client";

import { useEffect, useMemo, useState } from "react";
import { api, Dataset, Experiment } from "@/lib/api";
import ConsoleShell from "@/components/ConsoleShell";
import PageHero from "@/components/PageHero";
import Empty from "@/components/Empty";

/**
 * Evaluations — the cross-dataset overview of every scored run. Four headline numbers, a quality
 * signal over time (each run's mean, dated), a review inbox of the runs that came in under the
 * pass bar, and per-scorer coverage. Everything is derived from real experiment results; there
 * is no separate "quality" store, so an empty project shows the quick-start instead of zeros.
 */
const PASS = 0.7;

export default function EvaluationsPage() {
  const [rows, setRows] = useState<Experiment[] | null>(null);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  useEffect(() => { api.experiments().then(setRows).catch(() => setRows([])); }, []);
  useEffect(() => { api.datasets().then(setDatasets).catch(() => {}); }, []);

  const dsName = (id: number | null) => datasets.find((d) => d.id === id)?.name || (id ? `#${id}` : "—");
  const scored = useMemo(() => (rows || []).filter((r) => r.result_count > 0), [rows]);

  const stat = useMemo(() => {
    const withScore = scored.filter((r) => r.mean_score != null);
    const avg = withScore.length ? withScore.reduce((a, r) => a + (r.mean_score || 0), 0) / withScore.length : null;
    const passRate = withScore.length ? Math.round((withScore.filter((r) => (r.mean_score ?? 0) >= PASS).length / withScore.length) * 100) : null;
    return { runs: scored.length, avg, passRate, datasets: new Set(scored.map((r) => r.dataset_id)).size };
  }, [scored]);

  // Quality signal — each scored run's mean, oldest→newest, for the area chart.
  const series = useMemo(() =>
    [...scored].filter((r) => r.mean_score != null)
      .sort((a, b) => +new Date(a.created_at) - +new Date(b.created_at))
      .map((r) => ({ v: r.mean_score as number, at: r.created_at, name: r.name })), [scored]);

  // Review inbox — runs that came in under the pass bar, worst first.
  const inbox = useMemo(() =>
    scored.filter((r) => r.mean_score != null && (r.mean_score as number) < PASS)
      .sort((a, b) => (a.mean_score ?? 0) - (b.mean_score ?? 0)), [scored]);

  // Coverage — how many runs each scorer appeared in, and its mean across them.
  const coverage = useMemo(() => {
    const m = new Map<string, { runs: number; sum: number; n: number }>();
    for (const r of scored) for (const [name, mean] of Object.entries(r.scorer_means || {})) {
      const u = m.get(name) || { runs: 0, sum: 0, n: 0 };
      u.runs += 1; if (mean != null) { u.sum += mean; u.n += 1; } m.set(name, u);
    }
    return [...m.entries()].map(([name, u]) => ({ name, runs: u.runs, avg: u.n ? u.sum / u.n : null }))
      .sort((a, b) => b.runs - a.runs);
  }, [scored]);

  return (
    <ConsoleShell>
      <div className="cs-page" style={{ maxWidth: 1160 }}>
        <PageHero eyebrow="Quality" title="Evaluations"
          sub="Every scored run across your datasets — the quality signal over time, the runs that need a look, and which scorers cover your evals." />

        {rows == null ? <div className="muted" style={{ fontSize: 13 }}>Loading…</div>
          : scored.length === 0 ? (
            <Empty
              what="Evaluations are the scores your experiments produced, over time."
              why="Experiments compare two runs. This page is the longer view: is quality drifting, which runs need a look, and which scorers are actually covering your evals."
              action={{ label: "See your experiments", href: "/experiments" }}
              note="Nothing scores automatically — a result lands here when an experiment runs."
            />
          ) : (
            <>
              <div className="evl-stats">
                <Tile label="Scored runs" value={String(stat.runs)} sub="across all datasets" />
                <Tile label="Quality score" value={stat.avg != null ? Math.round(stat.avg * 100) + "" : "—"}
                  sub="mean of run means" tone={stat.avg == null ? undefined : stat.avg >= 0.8 ? "ok" : stat.avg >= 0.6 ? "warn" : "bad"} />
                <Tile label="Review queue" value={String(inbox.length)} sub={`below ${Math.round(PASS * 100)}`} tone={inbox.length ? "warn" : "ok"} />
                <Tile label="Datasets covered" value={String(stat.datasets)} sub="with a scored run" />
              </div>

              <div className="evl">
                {/* LEFT — quality signal chart */}
                <section className="evl-chart-card">
                  <div className="evl-card-head">Quality signal<span className="muted">{series.length} run{series.length === 1 ? "" : "s"}</span></div>
                  {series.length < 2 ? (
                    <div className="muted" style={{ fontSize: 12.5, padding: "28px 4px" }}>Two or more scored runs are needed to draw a trend. {series.length === 1 && `Latest: ${Math.round(series[0].v * 100)}.`}</div>
                  ) : <AreaChart series={series} />}
                </section>

                {/* RIGHT — review inbox */}
                <aside className="evl-inbox-card">
                  <div className="evl-card-head">Quality inbox{inbox.length > 0 && <span className="evl-urgent">{inbox.length} to review</span>}</div>
                  {inbox.length === 0 ? (
                    <div className="evl-inbox-empty"><span className="evl-check">✓</span>Every scored run is at or above {Math.round(PASS * 100)}.</div>
                  ) : (
                    <div className="evl-inbox">
                      {inbox.map((r) => (
                        <a key={r.id} href="/experiments" className="evl-inbox-row">
                          <span className="evl-inbox-score" style={{ color: (r.mean_score ?? 0) < 0.5 ? "var(--red)" : "var(--amber)" }}>{Math.round((r.mean_score ?? 0) * 100)}</span>
                          <span className="evl-inbox-main">
                            <b>{r.name || `experiment ${r.id}`}</b>
                            <small>{dsName(r.dataset_id)} · {r.result_count} result{r.result_count === 1 ? "" : "s"}</small>
                          </span>
                          <span className="evl-inbox-arrow">→</span>
                        </a>
                      ))}
                    </div>
                  )}
                </aside>
              </div>

              {/* Coverage table */}
              <section className="evl-cov-card">
                <div className="evl-card-head">Evaluation coverage</div>
                <table className="dset-table">
                  <thead><tr><th>Scorer</th><th>Runs</th><th style={{ width: "45%" }}>Mean score</th></tr></thead>
                  <tbody>
                    {coverage.map((c) => (
                      <tr key={c.name}>
                        <td><code className="mono" style={{ fontSize: 12 }}>{c.name}</code></td>
                        <td>{c.runs}</td>
                        <td>
                          <div className="evl-cov-bar">
                            <div className="evl-cov-fill" style={{ width: `${(c.avg ?? 0) * 100}%`, background: (c.avg ?? 0) >= 0.8 ? "var(--green)" : (c.avg ?? 0) >= 0.6 ? "var(--amber)" : "var(--red)" }} />
                            <span>{c.avg != null ? (c.avg * 100).toFixed(0) : "—"}</span>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </section>
            </>
          )}
      </div>
    </ConsoleShell>
  );
}

function Tile({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: "ok" | "warn" | "bad" }) {
  return (
    <div className="ses-tile">
      <div className="ses-tile-label">{label}</div>
      <div className={`ses-tile-value ${tone === "ok" ? "ok" : tone === "warn" ? "warn" : ""}`}
        style={tone === "bad" ? { color: "var(--red)" } : undefined}>{value}</div>
      {sub && <div className="ses-tile-sub">{sub}</div>}
    </div>
  );
}

function AreaChart({ series }: { series: { v: number; at: string; name: string }[] }) {
  const W = 640, H = 180, padX = 8, padY = 14;
  const n = series.length;
  const x = (i: number) => padX + (i / (n - 1)) * (W - padX * 2);
  const y = (v: number) => padY + (1 - Math.max(0, Math.min(1, v))) * (H - padY * 2);
  const line = series.map((p, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(p.v).toFixed(1)}`).join(" ");
  const area = `${line} L${x(n - 1).toFixed(1)},${(H - padY).toFixed(1)} L${x(0).toFixed(1)},${(H - padY).toFixed(1)} Z`;
  const passY = y(PASS);
  return (
    <div className="evl-chart">
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} preserveAspectRatio="none">
        <defs><linearGradient id="evlFill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="var(--accent)" stopOpacity="0.28" />
          <stop offset="100%" stopColor="var(--accent)" stopOpacity="0" />
        </linearGradient></defs>
        <line x1={padX} y1={passY} x2={W - padX} y2={passY} stroke="var(--border-strong)" strokeDasharray="4 4" strokeWidth="1" />
        <path d={area} fill="url(#evlFill)" />
        <path d={line} fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinejoin="round" />
        {series.map((p, i) => (
          <circle key={i} cx={x(i)} cy={y(p.v)} r="3" fill="var(--accent)"><title>{`${p.name}: ${Math.round(p.v * 100)} · ${new Date(p.at).toLocaleDateString()}`}</title></circle>
        ))}
      </svg>
      <div className="evl-chart-ax">
        <span>{new Date(series[0].at).toLocaleDateString()}</span>
        <span className="muted">dashed line = pass bar ({Math.round(PASS * 100)})</span>
        <span>{new Date(series[n - 1].at).toLocaleDateString()}</span>
      </div>
    </div>
  );
}
