"use client";

import { Connection } from "@/lib/api";

const TYPES = ["contains", "equals", "regex", "json_path", "json_schema", "tool_called", "latency_lt", "llm_judge"];

export default function AssertionsEditor({ assertions, onChange, connections }: {
  assertions: any[]; onChange: (a: any[]) => void; connections: Connection[];
}) {
  const list = assertions || [];
  const upd = (i: number, patch: any) => onChange(list.map((a, j) => (j === i ? { ...a, ...patch } : a)));
  const add = () => onChange([...list, { type: "contains", value: "" }]);
  const del = (i: number) => onChange(list.filter((_, j) => j !== i));
  const llms = connections.filter((c) => c.kind === "llm");

  return (
    <div className="field" style={{ marginTop: 8 }}>
      <label>Assertions <span className="hint">checked after the run — the evals layer</span>
        <button className="btn btn-ghost btn-sm" style={{ marginLeft: "auto" }} onClick={add}>+ add</button>
      </label>
      {list.length === 0 && <div className="jv-empty">No assertions. Add one to turn this into a test.</div>}
      <div className="vars">
        {list.map((a, i) => (
          <div key={i} className="assert-row">
            <div className="assert-head">
              <select value={a.type} onChange={(e) => upd(i, { type: e.target.value })}>
                {TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
              <button onClick={() => del(i)}>×</button>
            </div>
            <div className="assert-fields">
              {(a.type === "equals" || a.type === "json_path") &&
                <input value={a.path || ""} placeholder="path e.g. status" onChange={(e) => upd(i, { path: e.target.value })} />}
              {(a.type === "contains" || a.type === "equals" || a.type === "regex" || a.type === "tool_called" || a.type === "json_path" || a.type === "latency_lt") &&
                <input value={a.value ?? ""} placeholder={a.type === "latency_lt" ? "ms e.g. 2000" : a.type === "tool_called" ? "tool name" : a.type === "json_path" ? "expected (optional)" : "expected value"} onChange={(e) => upd(i, { value: e.target.value })} />}
              {a.type === "json_schema" &&
                <textarea className="mono" rows={3} value={typeof a.schema === "string" ? a.schema : JSON.stringify(a.schema || {}, null, 2)} placeholder='{ "type": "object", "required": ["status"] }' onChange={(e) => upd(i, { schema: e.target.value })} />}
              {a.type === "llm_judge" && (
                <>
                  <textarea rows={2} value={a.criteria || ""} placeholder="e.g. The reply is polite and cites a source" onChange={(e) => upd(i, { criteria: e.target.value })} />
                  <select value={a.connection_id || ""} onChange={(e) => upd(i, { connection_id: e.target.value ? +e.target.value : null })}>
                    <option value="">judge model…</option>
                    {llms.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                  </select>
                </>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
