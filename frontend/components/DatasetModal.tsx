"use client";

import { useEffect, useState } from "react";
import { useEscape } from "@/lib/useEscape";
import { api, DatasetResult, SavedDataset } from "@/lib/api";
import { datasetReportHtml, downloadHtml } from "@/lib/report";

type Row = { name: string; vars: string };

export default function DatasetModal({ request, onClose }: { request: any; onClose: () => void }) {
  useEscape(onClose);
  const [rows, setRows] = useState<Row[]>([{ name: "case 1", vars: "{}" }, { name: "case 2", vars: "{}" }]);
  const [result, setResult] = useState<DatasetResult | null>(null);
  const [running, setRunning] = useState(false);
  const [err, setErr] = useState("");
  const [saved, setSaved] = useState<SavedDataset[]>([]);

  const loadSaved = () => api.datasets().then(setSaved).catch(() => {});
  useEffect(() => { loadSaved(); }, []);

  const loadDataset = (id: string) => {
    const d = saved.find((x) => x.id === +id);
    if (d) setRows(d.rows.map((r) => ({ name: r.name, vars: JSON.stringify(r.variables || {}) })));
  };
  const saveDataset = async () => {
    const name = window.prompt("Save this dataset as…");
    if (!name) return;
    await api.createDataset(name, rows.map((r) => ({ name: r.name, variables: safe(r.vars) })));
    loadSaved();
  };

  const run = async () => {
    setRunning(true); setErr(""); setResult(null);
    try {
      const parsed = rows.map((r) => ({ name: r.name, variables: safe(r.vars) }));
      setResult(await api.datasetRun(request, parsed));
    } catch (e: any) { setErr(e.message); }
    finally { setRunning(false); }
  };

  return (
    <div className="overlay" onClick={onClose}>
      <div className="modal" style={{ width: 720 }} onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">Dataset run <span className="hint" style={{ marginLeft: 10, fontWeight: 400 }}>run this request over N input rows</span><button onClick={onClose}>×</button></div>
        <div className="modal-body">
          {!result ? (
            <>
              <div className="field">
                <label>Rows <span className="hint">each row's variables fill {"{{placeholders}}"} + assertions run per row</span></label>
                <div className="dic-modes" style={{ marginBottom: 4 }}>
                  {saved.length > 0 && (
                    <select className="dic-real" defaultValue="" onChange={(e) => { loadDataset(e.target.value); }}>
                      <option value="" disabled>Load saved dataset…</option>
                      {saved.map((d) => <option key={d.id} value={d.id}>{d.name} ({d.rows.length})</option>)}
                    </select>
                  )}
                  <button className="btn btn-ghost btn-sm" onClick={saveDataset}>Save dataset</button>
                </div>
              </div>
              <div className="ds-rows">
                <div className="ds-row ds-head"><span>Name</span><span>Variables (JSON)</span><span></span></div>
                {rows.map((r, i) => (
                  <div className="ds-row" key={i}>
                    <input value={r.name} onChange={(e) => setRows(rows.map((x, j) => j === i ? { ...x, name: e.target.value } : x))} />
                    <input className="mono" value={r.vars} onChange={(e) => setRows(rows.map((x, j) => j === i ? { ...x, vars: e.target.value } : x))} placeholder='{ "sku": "Berge" }' />
                    <button className="btn btn-ghost btn-sm" onClick={() => setRows(rows.filter((_, j) => j !== i))}>×</button>
                  </div>
                ))}
              </div>
              <button className="btn btn-ghost btn-sm" onClick={() => setRows([...rows, { name: `case ${rows.length + 1}`, vars: "{}" }])}>+ add row</button>
              {err && <div className="resp-error" style={{ marginTop: 10 }}>{err}</div>}
            </>
          ) : (
            <>
              <div className="ds-summary">
                <span className={`ds-badge ${result.summary.passed === result.summary.total ? "ok" : "fail"}`}>{result.summary.passed} / {result.summary.total} passed</span>
              </div>
              <div className="ds-result">
                {result.rows.map((row, i) => (
                  <div key={i} className={`ds-res-row ${row.pass ? "ok" : "fail"}`}>
                    <span className="ar-icon">{row.pass ? "✓" : "✕"}</span>
                    <div className="ar-main">
                      <div className="ar-name">{row.name} <span className="ar-type">{row.status}{row.assertions.length ? ` · ${row.assertions.filter((a) => a.ok).length}/${row.assertions.length} asserts` : ""}</span></div>
                      <div className="ar-detail">{typeof row.output === "object" ? JSON.stringify(row.output).slice(0, 120) : (row.text || "").slice(0, 120)}</div>
                    </div>
                    <span className="meta-pill">{row.duration_ms} ms</span>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
        <div className="modal-foot">
          {result && <button className="btn btn-ghost" style={{ marginRight: "auto" }} onClick={() => setResult(null)}>← Edit rows</button>}
          {result && <button className="btn btn-ghost" onClick={() => downloadHtml("agentman-eval-report.html", datasetReportHtml(request, result))}>⬇ Export HTML</button>}
          <button className="btn btn-ghost" onClick={onClose}>Close</button>
          {!result && <button className="btn btn-run" onClick={run} disabled={running}>{running ? "Running…" : `▶ Run ${rows.length} rows`}</button>}
        </div>
      </div>
    </div>
  );
}

function safe(s: string) { try { return JSON.parse(s); } catch { return {}; } }
