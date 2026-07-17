"use client";

import { useState } from "react";
import { useEscape } from "@/lib/useEscape";
import { api, Connection } from "@/lib/api";
import JsonView from "./JsonView";

export default function CompareModal({ request, connections, onClose }: {
  request: any; connections: Connection[]; onClose: () => void;
}) {
  useEscape(onClose);
  const conn = connections.find((c) => c.id === request.connection_id);
  const models: string[] = conn?.config?.models || [];
  const [a, setA] = useState(request.model || models[0] || "");
  const [b, setB] = useState(models[1] || models[0] || "");
  const [res, setRes] = useState<{ a?: any; b?: any } | null>(null);
  const [running, setRunning] = useState(false);

  const run = async () => {
    setRunning(true); setRes(null);
    try {
      const [ra, rb] = await Promise.all([
        api.runOnce({ ...request, model: a }),
        api.runOnce({ ...request, model: b }),
      ]);
      setRes({ a: ra, b: rb });
    } finally { setRunning(false); }
  };

  const Col = ({ label, r }: { label: string; r: any }) => (
    <div className="cmp-col">
      <div className="cmp-col-head">{label} <span className="meta-pill">{r?.duration_ms} ms</span></div>
      <div className="cmp-col-body">
        {r?.result?.text ? <div className="stream-text" style={{ fontSize: 13 }}>{r.result.text}</div>
          : r?.result?.output != null ? <JsonView data={r.result.output} />
          : <div className="jv-empty">no output</div>}
      </div>
    </div>
  );

  return (
    <div className="overlay" onClick={onClose}>
      <div className="modal" role="dialog" aria-modal="true" aria-label="Compare models" style={{ width: 860 }} onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">Compare <span className="hint" style={{ marginLeft: 10, fontWeight: 400 }}>same input, two models</span><button onClick={onClose} aria-label="Close">×</button></div>
        <div className="modal-body">
          <div className="row2" style={{ marginBottom: 14 }}>
            <div className="field"><label>Model A</label>{models.length ? <select value={a} onChange={(e) => setA(e.target.value)}>{models.map((m) => <option key={m}>{m}</option>)}</select> : <input value={a} onChange={(e) => setA(e.target.value)} />}</div>
            <div className="field"><label>Model B</label>{models.length ? <select value={b} onChange={(e) => setB(e.target.value)}>{models.map((m) => <option key={m}>{m}</option>)}</select> : <input value={b} onChange={(e) => setB(e.target.value)} />}</div>
          </div>
          {res && <div className="cmp-grid"><Col label={a} r={res.a} /><Col label={b} r={res.b} /></div>}
        </div>
        <div className="modal-foot">
          <button className="btn btn-ghost" onClick={onClose}>Close</button>
          <button className="btn btn-run" onClick={run} disabled={running}>{running ? "Running…" : "▶ Run both"}</button>
        </div>
      </div>
    </div>
  );
}
