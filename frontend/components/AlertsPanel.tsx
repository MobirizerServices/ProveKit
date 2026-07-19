"use client";

import { useEffect, useState } from "react";
import { Alert, api } from "@/lib/api";

const METRICS: { v: string; label: string }[] = [
  { v: "error_rate", label: "Error rate" },
  { v: "latency_p95_ms", label: "Latency p95 (ms)" },
  { v: "latency_p50_ms", label: "Latency p50 (ms)" },
  { v: "trace_count", label: "Trace count" },
  { v: "error_count", label: "Error count" },
  { v: "total_tokens", label: "Total tokens" },
];
const metricLabel = (v: string) => METRICS.find((m) => m.v === v)?.label ?? v;

export default function AlertsPanel() {
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ name: "", metric: "error_rate", comparator: "gt", threshold: "0.2", window_hours: "24", email: "" });
  const [msg, setMsg] = useState("");

  const load = () => api.alerts().then(setAlerts).catch(() => {});
  useEffect(() => { load(); }, []);

  const create = async () => {
    try {
      await api.createAlert({
        name: form.name || metricLabel(form.metric), metric: form.metric, comparator: form.comparator,
        threshold: Number(form.threshold), window_hours: Number(form.window_hours), email: form.email,
      });
      setForm({ ...form, name: "", email: "" }); setOpen(false); load();
    } catch (e: any) { setMsg(String(e.message || e)); }
  };
  const check = async () => {
    try { const r = await api.checkAlerts(); setMsg(r.fired.length ? `${r.fired.length} alert(s) fired` : "No alerts breached right now"); load(); }
    catch (e: any) { setMsg(String(e.message || e)); }
    setTimeout(() => setMsg(""), 4000);
  };

  return (
    <div style={{ background: "var(--panel)", border: "1px solid var(--border)", borderRadius: 12, padding: 16, marginTop: 20 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
        <div style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: 0.4, color: "var(--muted)" }}>Alerts</div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {msg && <span className="muted" style={{ fontSize: 12 }}>{msg}</span>}
          <button className="btn btn-sm" onClick={check}>Check now</button>
          <button className="btn btn-sm" onClick={() => setOpen((o) => !o)}>{open ? "Cancel" : "+ New alert"}</button>
        </div>
      </div>

      {open && (
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center", padding: "10px 0", borderBottom: "1px solid var(--border)", marginBottom: 10 }}>
          <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="name (optional)" style={inp(140)} />
          <select value={form.metric} onChange={(e) => setForm({ ...form, metric: e.target.value })} style={inp(160)}>
            {METRICS.map((m) => <option key={m.v} value={m.v}>{m.label}</option>)}
          </select>
          <select value={form.comparator} onChange={(e) => setForm({ ...form, comparator: e.target.value })} style={inp(60)}>
            <option value="gt">&gt;</option><option value="lt">&lt;</option>
          </select>
          <input value={form.threshold} onChange={(e) => setForm({ ...form, threshold: e.target.value })} placeholder="threshold" style={inp(90)} />
          <span className="muted" style={{ fontSize: 12.5 }}>over</span>
          <input value={form.window_hours} onChange={(e) => setForm({ ...form, window_hours: e.target.value })} style={inp(50)} />
          <span className="muted" style={{ fontSize: 12.5 }}>h · email</span>
          <input value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} placeholder="alerts@you.com" style={inp(160)} />
          <button className="btn btn-sm" onClick={create}>Create</button>
        </div>
      )}

      {alerts.length === 0 ? (
        <div className="muted" style={{ fontSize: 13, padding: "6px 0" }}>
          No alerts yet. Create one to get emailed when a metric crosses a threshold.
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          {alerts.map((a) => (
            <div key={a.id} style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 0", borderTop: "1px solid var(--border)", fontSize: 13 }}>
              <span style={{ fontWeight: 600, flex: "0 0 130px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{a.name}</span>
              <span className="muted mono" style={{ fontSize: 12, flex: 1 }}>
                {metricLabel(a.metric)} {a.comparator === "gt" ? ">" : "<"} {a.threshold} · {a.window_hours}h
                {a.email ? ` · ${a.email}` : ""}
                {a.last_triggered_at ? ` · last fired ${new Date(a.last_triggered_at).toLocaleDateString()}` : ""}
              </span>
              <button className="btn btn-sm" onClick={() => api.toggleAlert(a.id, !a.enabled).then(load)}
                style={a.enabled ? { borderColor: "var(--green)", color: "var(--green)" } : { color: "var(--muted)" }}>
                {a.enabled ? "On" : "Off"}
              </button>
              <button className="btn btn-sm btn-ghost" onClick={() => api.deleteAlert(a.id).then(load)}>Delete</button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function inp(w: number): React.CSSProperties {
  return { width: w, background: "var(--panel-2)", color: "var(--text)", border: "1px solid var(--border-strong)", borderRadius: 8, padding: "6px 9px", fontSize: 12.5 };
}
