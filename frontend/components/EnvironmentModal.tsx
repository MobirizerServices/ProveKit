"use client";

import { useState } from "react";
import { useEscape } from "@/lib/useEscape";
import { api, EnvironmentT } from "@/lib/api";

type Row = { k: string; v: string };

export default function EnvironmentModal({ environments, onChanged, onClose }: {
  environments: EnvironmentT[]; onChanged: () => void; onClose: () => void;
}) {
  useEscape(onClose);
  const [sel, setSel] = useState<number | "new">(environments[0]?.id ?? "new");
  const current = sel === "new" ? null : environments.find((e) => e.id === sel) || null;
  const [name, setName] = useState(current?.name || "");
  const [rows, setRows] = useState<Row[]>(
    current ? Object.entries(current.variables).map(([k, v]) => ({ k, v: String(v) })) : [{ k: "", v: "" }]);
  const [active, setActive] = useState(current?.is_active ?? false);

  const pick = (id: number | "new") => {
    setSel(id);
    const e = id === "new" ? null : environments.find((x) => x.id === id) || null;
    setName(e?.name || "");
    setRows(e ? Object.entries(e.variables).map(([k, v]) => ({ k, v: String(v) })) : [{ k: "", v: "" }]);
    setActive(e?.is_active ?? false);
  };

  const save = async () => {
    const variables: Record<string, string> = {};
    rows.forEach((r) => { if (r.k.trim()) variables[r.k.trim()] = r.v; });
    const body = { name: name || "env", variables, is_active: active };
    if (sel === "new") await api.createEnvironment(body);
    else await api.updateEnvironment(sel, body);
    onChanged();
    onClose();
  };
  const del = async () => {
    if (sel !== "new") await api.deleteEnvironment(sel);
    onChanged(); onClose();
  };

  return (
    <div className="overlay" onClick={onClose}>
      <div className="modal" style={{ width: 560 }} onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">Environments<button onClick={onClose}>×</button></div>
        <div className="modal-body" style={{ display: "grid", gridTemplateColumns: "150px 1fr", gap: 16 }}>
          <div>
            {environments.map((e) => (
              <div key={e.id} className={`req-item ${sel === e.id ? "on" : ""}`} onClick={() => pick(e.id)}>
                <div className="ri-main"><div className="ri-name">{e.name}{e.is_active ? " ·" : ""}</div></div>
              </div>
            ))}
            <div className={`req-item ${sel === "new" ? "on" : ""}`} onClick={() => pick("new")}>
              <div className="ri-main"><div className="ri-name" style={{ color: "var(--accent-2)" }}>+ New</div></div>
            </div>
          </div>
          <div>
            <div className="field"><label>Name</label><input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. local" /></div>
            <div className="field">
              <label>Variables <span className="hint">used as {"{{key}}"} in any field</span></label>
              <div className="vars">
                {rows.map((r, i) => (
                  <div className="var-row" key={i}>
                    <input value={r.k} placeholder="key" onChange={(e) => setRows(rows.map((x, j) => j === i ? { ...x, k: e.target.value } : x))} />
                    <input value={r.v} placeholder="value" onChange={(e) => setRows(rows.map((x, j) => j === i ? { ...x, v: e.target.value } : x))} />
                    <button onClick={() => setRows(rows.filter((_, j) => j !== i))}>×</button>
                  </div>
                ))}
                <button className="btn btn-ghost btn-sm" onClick={() => setRows([...rows, { k: "", v: "" }])}>+ add variable</button>
              </div>
            </div>
            <label style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 13 }}>
              <input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} /> Active (apply these variables to runs)
            </label>
          </div>
        </div>
        <div className="modal-foot">
          {sel !== "new" && <button className="btn btn-ghost btn-stop" style={{ marginRight: "auto" }} onClick={del}>Delete</button>}
          <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn btn-run" onClick={save}>Save</button>
        </div>
      </div>
    </div>
  );
}
