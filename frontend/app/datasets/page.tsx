"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { api, Dataset, DatasetDetail, Experiment, ExperimentComparison, ScorerComparison } from "@/lib/api";
import RegressionTriage from "@/components/RegressionTriage";
import { Skeleton, SkeletonStyles } from "@/components/Skeleton";
import ConsoleShell from "@/components/ConsoleShell";
import PageHero from "@/components/PageHero";

const SPLIT_ORDER = ["train", "validation", "val", "test", "holdout"];
const SPLIT_HUE: Record<string, string> = { train: "var(--accent)", validation: "var(--blue)", val: "var(--blue)", test: "var(--green)", holdout: "var(--amber)" };

export default function DatasetsPage() {
  const [list, setList] = useState<Dataset[]>([]);
  const [sel, setSel] = useState<number | null>(null);
  const [detail, setDetail] = useState<DatasetDetail | null>(null);
  const [experiments, setExperiments] = useState<Experiment[]>([]);
  const [cmpPick, setCmpPick] = useState<number[]>([]);
  const [cmp, setCmp] = useState<ExperimentComparison | null>(null);
  const [newName, setNewName] = useState("");

  const toggleCmp = (id: number) => setCmpPick((p) =>
    p.includes(id) ? p.filter((x) => x !== id) : [...p, id].slice(-2));
  useEffect(() => {
    if (cmpPick.length !== 2) { setCmp(null); return; }
    api.compareExperiments(cmpPick[0], cmpPick[1]).then(setCmp).catch(() => setCmp(null));
  }, [cmpPick]);

  const load = useCallback(() => { api.datasets().then(setList).catch(() => {}); }, []);
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (sel == null) { setDetail(null); setExperiments([]); setCmpPick([]); return; }
    api.dataset(sel).then(setDetail).catch(() => {});
    api.experiments(sel).then(setExperiments).catch(() => {});
  }, [sel]);
  useEffect(() => { if (sel == null && list.length) setSel(list[0].id); }, [list, sel]);

  const create = async () => {
    if (!newName.trim()) return;
    const d = await api.createDataset(newName.trim());
    setNewName(""); load(); setSel(d.id);
  };

  // Latest run against this set — its mean is a real, dated quality signal (not a fabricated score).
  const latest = useMemo(() => [...experiments].sort((a, b) => +new Date(b.created_at) - +new Date(a.created_at))[0] || null, [experiments]);
  const splits = useMemo(() => {
    const m = new Map<string, number>();
    for (const it of detail?.items || []) {
      const s = String(it.meta?.split || "unassigned");
      m.set(s, (m.get(s) || 0) + 1);
    }
    return [...m.entries()].sort((a, b) => (SPLIT_ORDER.indexOf(a[0]) + 99) % 999 - (SPLIT_ORDER.indexOf(b[0]) + 99) % 999);
  }, [detail]);
  const hasSplit = splits.length > 1 || (splits.length === 1 && splits[0][0] !== "unassigned");

  return (
    <ConsoleShell>
      <div className="cs-page" style={{ maxWidth: 1180 }}>
        <PageHero eyebrow="Evaluation" title="Datasets"
          sub="Collections of examples your evaluations run against. Seed them from real traces, split them for train/test, and score a version with pk.evaluate()." />

        <div className="dset">
          {/* LEFT — dataset registry */}
          <aside className="dset-reg">
            <div className="dset-reg-head">Dataset registry<span className="au2-count">{list.length}</span></div>
            <div className="set2-add" style={{ padding: "8px 10px" }}>
              <input value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="New dataset…"
                onKeyDown={(e) => e.key === "Enter" && create()} />
              <button className="btn btn-sm" onClick={create}>Add</button>
            </div>
            {list.length === 0 ? <div className="muted au2-empty">No datasets yet.</div>
              : list.map((d) => (
                <button key={d.id} className={`dset-item ${sel === d.id ? "on" : ""}`} onClick={() => setSel(d.id)}>
                  <span className="dset-item-main">
                    <span className="dset-item-name">{d.name}</span>
                    <span className="dset-item-meta">{d.item_count} example{d.item_count === 1 ? "" : "s"}</span>
                  </span>
                  <span className="dset-chev">›</span>
                </button>
              ))}
          </aside>

          {/* RIGHT — detail */}
          <section className="dset-detail">
            {sel == null ? <div className="muted au2-empty" style={{ padding: 40 }}>Select a dataset.</div>
              : !detail ? <div style={{ padding: 8 }}><Skeleton w="35%" h={18} /><Skeleton w="100%" h={120} mt={16} r={10} /><Skeleton w="80%" mt={12} /><SkeletonStyles /></div>
              : (
                <>
                  <div className="dset-detail-head">
                    <div>
                      <h2>{detail.name}</h2>
                      {detail.description && <div className="dset-detail-sub">{detail.description}</div>}
                    </div>
                    <button className="btn btn-sm btn-ghost" onClick={async () => { await api.deleteDataset(detail.id); setSel(null); load(); }}
                      style={{ borderColor: "var(--red)", color: "var(--red)" }}>Delete</button>
                  </div>

                  {/* stat strip — quality donut is the latest experiment's mean, or n/a if never run */}
                  <div className="dset-strip">
                    <QualityDonut value={latest?.mean_score ?? null} />
                    <div className="dset-stats">
                      <Stat label="Examples" value={String(detail.items.length)} />
                      <Stat label="Latest run" value={latest ? `${latest.result_count} scored` : "never run"} />
                      <Stat label="Fingerprint" value={latest?.dataset_fingerprint ? latest.dataset_fingerprint.slice(0, 10) : "—"} mono />
                      <Stat label="Updated" value={new Date(detail.created_at).toLocaleDateString()} />
                    </div>
                  </div>

                  {/* split bar — only when items actually carry a split assignment */}
                  {hasSplit && (
                    <div className="dset-split">
                      <div className="dset-split-label">Split</div>
                      <div className="dset-split-bar">
                        {splits.map(([name, n]) => (
                          <div key={name} className="dset-split-seg" title={`${name}: ${n}`}
                            style={{ flexGrow: n, background: SPLIT_HUE[name] || "var(--border-strong)" }} />
                        ))}
                      </div>
                      <div className="dset-split-legend">
                        {splits.map(([name, n]) => (
                          <span key={name}><i style={{ background: SPLIT_HUE[name] || "var(--border-strong)" }} />{name} {n}</span>
                        ))}
                      </div>
                    </div>
                  )}

                  {experiments.length > 0 && (
                    <div className="dset-exp">
                      <div className="dset-section-label">Experiments</div>
                      <table className="dset-table">
                        <thead><tr><th>Compare</th><th>Name</th><th>Results</th><th style={{ textAlign: "right" }}>Mean score</th></tr></thead>
                        <tbody>
                          {experiments.map((e) => (
                            <tr key={e.id}>
                              <td><input type="checkbox" checked={cmpPick.includes(e.id)} onChange={() => toggleCmp(e.id)} aria-label={`Compare ${e.name}`} /></td>
                              <td>{e.name}</td>
                              <td>{e.result_count}</td>
                              <td style={{ textAlign: "right", fontWeight: 600 }}>
                                {e.mean_score == null ? "—" : e.mean_score.toFixed(3)}<Spread s={e.scorer_stats} />
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                      {cmpPick.length === 1 && <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>Select a second run to test whether the difference is real.</div>}
                      {cmp && <Significance cmp={cmp} />}
                      {cmpPick.length === 2 && <RegressionTriage a={cmpPick[0]} b={cmpPick[1]} />}
                    </div>
                  )}

                  <div className="dset-section-label" style={{ marginTop: 20 }}>Example explorer ({detail.items.length})</div>
                  {detail.items.length === 0 ? (
                    <div className="muted" style={{ fontSize: 12.5, marginTop: 6 }}>No items. Add from a trace on the Traces page, or via the API.</div>
                  ) : (
                    <table className="dset-table dset-examples">
                      <thead><tr><th>Input</th><th>Expected</th>{hasSplit && <th>Split</th>}<th style={{ textAlign: "right" }}>Added</th></tr></thead>
                      <tbody>
                        {detail.items.map((it) => (
                          <tr key={it.id}>
                            <td className="dset-cell-in">{it.input}</td>
                            <td className="dset-cell-ex">{it.expected || <span className="muted">—</span>}</td>
                            {hasSplit && <td>{it.meta?.split ? <span className="dset-split-chip" style={{ color: SPLIT_HUE[it.meta.split] || "var(--muted)" }}>{it.meta.split}</span> : <span className="muted">—</span>}</td>}
                            <td style={{ textAlign: "right", whiteSpace: "nowrap" }} className="muted">{new Date(it.created_at).toLocaleDateString()}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </>
              )}
          </section>
        </div>
      </div>
    </ConsoleShell>
  );
}

function Stat({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return <div className="dset-stat"><div className="dset-stat-label">{label}</div><div className={`dset-stat-value ${mono ? "mono" : ""}`}>{value}</div></div>;
}

function QualityDonut({ value }: { value: number | null }) {
  // value is a 0..1 mean score from the latest run; null when the set was never evaluated.
  const pct = value == null ? 0 : Math.max(0, Math.min(1, value));
  const r = 34, c = 2 * Math.PI * r;
  const hue = value == null ? "var(--border-strong)" : pct >= 0.8 ? "var(--green)" : pct >= 0.6 ? "var(--amber)" : "var(--red)";
  return (
    <div className="dset-donut">
      <svg width="86" height="86" viewBox="0 0 86 86">
        <circle cx="43" cy="43" r={r} fill="none" stroke="var(--panel-2)" strokeWidth="8" />
        <circle cx="43" cy="43" r={r} fill="none" stroke={hue} strokeWidth="8" strokeLinecap="round"
          strokeDasharray={`${c * pct} ${c}`} transform="rotate(-90 43 43)" />
        <text x="43" y="41" textAnchor="middle" fontSize="17" fontWeight="600" fill="var(--text)">{value == null ? "—" : `${Math.round(pct * 100)}`}</text>
        <text x="43" y="55" textAnchor="middle" fontSize="8" fill="var(--muted)">{value == null ? "no run" : "quality"}</text>
      </svg>
    </div>
  );
}

function Spread({ s }: { s?: Record<string, { n: number; ci95_low: number | null; ci95_high: number | null }> }) {
  const first = s && Object.values(s)[0];
  if (!first || first.ci95_low == null || first.ci95_high == null) return null;
  return <span className="muted" style={{ fontWeight: 400, fontSize: 11.5 }}> ±{((first.ci95_high - first.ci95_low) / 2).toFixed(3)} · n={first.n}</span>;
}

function Significance({ cmp }: { cmp: ExperimentComparison }) {
  return (
    <div style={{ marginTop: 12, padding: 12, border: "1px solid var(--border)", borderRadius: 10, background: "var(--panel-2)" }}>
      <div style={{ fontSize: 12.5, marginBottom: 8 }}><strong>{cmp.a.name}</strong> <span className="muted">vs</span> <strong>{cmp.b.name}</strong></div>
      {cmp.warning && <div style={{ fontSize: 12, color: "var(--amber)", marginBottom: 8 }}>{cmp.warning}</div>}
      {(Object.entries(cmp.scorers) as [string, ScorerComparison][]).map(([name, r]) => (
        <div key={name} style={{ marginBottom: 8 }}>
          <div style={{ fontSize: 12.5, display: "flex", gap: 8, alignItems: "baseline", flexWrap: "wrap" }}>
            <span className="mono">{name}</span>
            <span style={{ fontWeight: 600, color: (r.delta ?? 0) >= 0 ? "var(--green)" : "var(--err)" }}>{r.delta == null ? "—" : `${r.delta >= 0 ? "+" : ""}${r.delta.toFixed(3)}`}</span>
            {r.p_value != null && <span className="muted">p = {r.p_value < 0.001 ? "<0.001" : r.p_value.toFixed(3)}</span>}
            <span style={{ fontSize: 11, fontWeight: 700, textTransform: "uppercase", color: r.significant ? "var(--green)" : "var(--muted)" }}>{r.significant ? "significant" : "not significant"}</span>
            {r.paired && <span className="muted" style={{ fontSize: 11 }}>paired · n={r.paired_n}</span>}
          </div>
          {r.caution && <div className="muted" style={{ fontSize: 11.5, marginTop: 2 }}>{r.caution}</div>}
        </div>
      ))}
    </div>
  );
}
