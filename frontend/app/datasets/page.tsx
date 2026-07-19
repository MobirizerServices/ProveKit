"use client";

import { useCallback, useEffect, useState } from "react";
import { api, Dataset, DatasetDetail, Experiment } from "@/lib/api";
import { Skeleton, SkeletonStyles } from "@/components/Skeleton";
import TopNav from "@/components/TopNav";

export default function DatasetsPage() {
  const [list, setList] = useState<Dataset[]>([]);
  const [sel, setSel] = useState<number | null>(null);
  const [detail, setDetail] = useState<DatasetDetail | null>(null);
  const [experiments, setExperiments] = useState<Experiment[]>([]);
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
                      <thead><tr style={hrow}><th style={th}>Name</th><th style={th}>Results</th><th style={th}>Mean score</th></tr></thead>
                      <tbody>
                        {experiments.map((e) => (
                          <tr key={e.id} style={{ borderTop: "1px solid var(--border)" }}>
                            <td style={td}>{e.name}</td>
                            <td style={td}>{e.result_count}</td>
                            <td style={{ ...td, fontWeight: 600 }}>{e.mean_score == null ? "—" : e.mean_score.toFixed(3)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
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
