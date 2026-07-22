"use client";

import { useCallback, useEffect, useState } from "react";
import { api, Dataset, DatasetDetail, Experiment, ExperimentComparison, ScorerComparison } from "@/lib/api";
import RegressionTriage from "@/components/RegressionTriage";
import { Skeleton, SkeletonStyles } from "@/components/Skeleton";
import TopNav from "@/components/TopNav";

export default function DatasetsPage() {
  const [list, setList] = useState<Dataset[]>([]);
  const [sel, setSel] = useState<number | null>(null);
  const [detail, setDetail] = useState<DatasetDetail | null>(null);
  const [experiments, setExperiments] = useState<Experiment[]>([]);
  const [cmpPick, setCmpPick] = useState<number[]>([]);
  const [cmp, setCmp] = useState<ExperimentComparison | null>(null);

  // Two runs selected → ask whether the gap between them is real.
  const toggleCmp = (id: number) => setCmpPick((p) =>
    p.includes(id) ? p.filter((x) => x !== id) : [...p, id].slice(-2));
  useEffect(() => {
    if (cmpPick.length !== 2) { setCmp(null); return; }
    api.compareExperiments(cmpPick[0], cmpPick[1]).then(setCmp).catch(() => setCmp(null));
  }, [cmpPick]);
  const [newName, setNewName] = useState("");

  const load = useCallback(() => { api.datasets().then(setList).catch(() => {}); }, []);
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (sel == null) { setDetail(null); setExperiments([]); return; }
    api.dataset(sel).then(setDetail).catch(() => {});
    api.experiments(sel).then(setExperiments).catch(() => {});
  }, [sel]);

  const create = async () => {
    if (!newName.trim()) return;
    const d = await api.createDataset(newName.trim());
    setNewName(""); load(); setSel(d.id);
  };

  return (
    <>
      <TopNav />
      <main style={{ maxWidth: 1100, margin: "0 auto", padding: "24px 20px 80px" }}>
        <h1 style={{ fontSize: 22, margin: "0 0 4px" }}>Datasets</h1>
        <p className="muted" style={{ margin: "0 0 20px", fontSize: 13.5 }}>
          Collections of examples your evaluations run against. Add items by hand, or seed them
          from a trace on the Traces page. Run <span className="mono">pk.evaluate()</span> to score a version against a set.
        </p>

        <div style={{ display: "grid", gridTemplateColumns: "300px 1fr", gap: 16 }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <div style={{ display: "flex", gap: 6 }}>
              <input value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="New dataset name…"
                onKeyDown={(e) => e.key === "Enter" && create()}
                style={{ flex: 1, background: "var(--panel-2)", color: "var(--text)", border: "1px solid var(--border-strong)", borderRadius: 8, padding: "8px 11px", fontSize: 13 }} />
              <button className="btn btn-sm" onClick={create}>Add</button>
            </div>
            <div style={{ ...panel, padding: 0, overflow: "hidden" }}>
              {list.length === 0 ? (
                <div className="muted" style={{ padding: 14, fontSize: 12.5 }}>No datasets yet.</div>
              ) : list.map((d) => (
                <button key={d.id} onClick={() => setSel(d.id)} style={row(sel === d.id)}>
                  <div style={{ fontWeight: 500, fontSize: 13 }}>{d.name}</div>
                  <div className="muted" style={{ fontSize: 11.5, marginTop: 2 }}>{d.item_count} item{d.item_count === 1 ? "" : "s"}</div>
                </button>
              ))}
            </div>
          </div>

          <div style={{ ...panel, minHeight: 220 }}>
            {sel == null ? (
              <div className="muted" style={{ fontSize: 13 }}>Select a dataset.</div>
            ) : !detail ? (
              <><Skeleton w="35%" h={18} /><Skeleton w="100%" h={120} mt={16} r={10} /><Skeleton w="80%" mt={12} /><SkeletonStyles /></>
            ) : (
              <>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
                  <div style={{ fontSize: 15, fontWeight: 600 }}>{detail.name}</div>
                  <button className="btn btn-sm" onClick={async () => { await api.deleteDataset(detail.id); setSel(null); load(); }}>Delete</button>
                </div>

                {experiments.length > 0 && (
                  <div style={{ marginBottom: 16 }}>
                    <div style={label}>Experiments</div>
                    <table style={table}>
                      <thead><tr style={hrow}><th style={th}>Compare</th><th style={th}>Name</th><th style={th}>Results</th><th style={th}>Mean score</th></tr></thead>
                      <tbody>
                        {experiments.map((e) => (
                          <tr key={e.id} style={{ borderTop: "1px solid var(--border)" }}>
                            <td style={td}>
                              <input type="checkbox" checked={cmpPick.includes(e.id)}
                                onChange={() => toggleCmp(e.id)} aria-label={`Compare ${e.name}`} />
                            </td>
                            <td style={td}>{e.name}</td>
                            <td style={td}>{e.result_count}</td>
                            <td style={{ ...td, fontWeight: 600 }}>
                              {e.mean_score == null ? "—" : e.mean_score.toFixed(3)}
                              {/* The interval travels with the mean — a mean shown alone is
                                  what lets a 20-example result read as settled. */}
                              <Spread s={e.scorer_stats} />
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    {cmpPick.length === 1 && (
                      <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>
                        Select a second run to test whether the difference is real.
                      </div>
                    )}
                    {cmp && <Significance cmp={cmp} />}
                    {/* The significance verdict says whether the move is real; triage says which
                        rows moved. Both hang off the same two-run selection. */}
                    {cmpPick.length === 2 && <RegressionTriage a={cmpPick[0]} b={cmpPick[1]} />}
                  </div>
                )}

                <div style={label}>Items ({detail.items.length})</div>
                {detail.items.length === 0 ? (
                  <div className="muted" style={{ fontSize: 12.5, marginTop: 6 }}>No items. Add from a trace on the Traces page, or via the API.</div>
                ) : (
                  <table style={table}>
                    <thead><tr style={hrow}><th style={th}>Input</th><th style={th}>Expected</th></tr></thead>
                    <tbody>
                      {detail.items.map((it) => (
                        <tr key={it.id} style={{ borderTop: "1px solid var(--border)" }}>
                          <td style={{ ...td, maxWidth: 360, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{it.input}</td>
                          <td style={{ ...td, maxWidth: 260, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{it.expected || <span className="muted">—</span>}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </>
            )}
          </div>
        </div>
      </main>
    </>
  );
}

// The spread behind a mean, shown inline so it can't be read past.
function Spread({ s }: { s?: Record<string, { n: number; ci95_low: number | null; ci95_high: number | null }> }) {
  const first = s && Object.values(s)[0];
  if (!first || first.ci95_low == null || first.ci95_high == null) return null;
  return (
    <span className="muted" style={{ fontWeight: 400, fontSize: 11.5 }}>
      {" "}±{((first.ci95_high - first.ci95_low) / 2).toFixed(3)} · n={first.n}
    </span>
  );
}

function Significance({ cmp }: { cmp: ExperimentComparison }) {
  return (
    <div style={{ marginTop: 12, padding: 12, border: "1px solid var(--border)", borderRadius: 10, background: "var(--panel-2)" }}>
      <div style={{ fontSize: 12.5, marginBottom: 8 }}>
        <strong>{cmp.a.name}</strong> <span className="muted">vs</span> <strong>{cmp.b.name}</strong>
      </div>
      {cmp.warning && (
        <div style={{ fontSize: 12, color: "var(--amber)", marginBottom: 8 }}>{cmp.warning}</div>
      )}
      {(Object.entries(cmp.scorers) as [string, ScorerComparison][]).map(([name, r]) => (
        <div key={name} style={{ marginBottom: 8 }}>
          <div style={{ fontSize: 12.5, display: "flex", gap: 8, alignItems: "baseline", flexWrap: "wrap" }}>
            <span className="mono">{name}</span>
            <span style={{ fontWeight: 600, color: (r.delta ?? 0) >= 0 ? "var(--green)" : "var(--err)" }}>
              {r.delta == null ? "—" : `${r.delta >= 0 ? "+" : ""}${r.delta.toFixed(3)}`}
            </span>
            {r.p_value != null && (
              <span className="muted">p = {r.p_value < 0.001 ? "<0.001" : r.p_value.toFixed(3)}</span>
            )}
            {/* The verdict is stated in words: "p = 0.31" is not self-explanatory to most
                readers, and this is the number people act on. */}
            <span style={{ fontSize: 11, fontWeight: 700, textTransform: "uppercase",
                           color: r.significant ? "var(--green)" : "var(--muted)" }}>
              {r.significant ? "significant" : "not significant"}
            </span>
            {r.paired && <span className="muted" style={{ fontSize: 11 }}>paired · n={r.paired_n}</span>}
          </div>
          {r.caution && (
            <div className="muted" style={{ fontSize: 11.5, marginTop: 2 }}>{r.caution}</div>
          )}
        </div>
      ))}
    </div>
  );
}

const panel: React.CSSProperties = { background: "var(--panel)", border: "1px solid var(--border)", borderRadius: 12, padding: 16 };
const label: React.CSSProperties = { fontSize: 11, textTransform: "uppercase", letterSpacing: 0.4, color: "var(--muted)", marginBottom: 6 };
const table: React.CSSProperties = { width: "100%", borderCollapse: "collapse", fontSize: 13 };
const hrow: React.CSSProperties = { textAlign: "left", color: "var(--muted)", fontSize: 11.5 };
const th: React.CSSProperties = { padding: "4px 8px", fontWeight: 500 };
const td: React.CSSProperties = { padding: "6px 8px" };
function row(active: boolean): React.CSSProperties {
  return { display: "block", width: "100%", textAlign: "left", padding: "10px 13px",
    background: active ? "var(--accent-soft)" : "transparent", color: "var(--text)",
    border: "none", borderBottom: "1px solid var(--border)", cursor: "pointer" };
}
