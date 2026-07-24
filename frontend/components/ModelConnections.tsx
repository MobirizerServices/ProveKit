"use client";

import { useEffect, useState } from "react";
import { api, ProviderConnection } from "@/lib/api";

const PROVIDERS = [
  { id: "openai", label: "OpenAI", needsKey: true, needsUrl: false },
  { id: "anthropic", label: "Anthropic", needsKey: true, needsUrl: false },
  { id: "openai_compatible", label: "OpenAI-compatible", needsKey: true, needsUrl: true },
];

// Per-project model-provider credentials used to re-run captured calls in the playground /
// replay harness. Keys are sent once and stored sealed server-side; only a masked hint returns.
export default function ModelConnections() {
  const [rows, setRows] = useState<ProviderConnection[] | null>(null);
  const [provider, setProvider] = useState("openai");
  const [label, setLabel] = useState("");
  const [key, setKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const load = () => api.connections().then(setRows).catch(() => setRows([]));
  useEffect(() => { load(); }, []);

  const meta = PROVIDERS.find((p) => p.id === provider)!;
  const add = async () => {
    setErr(""); setBusy(true);
    try {
      await api.createConnection({ provider, label: label.trim(), key: key.trim(), base_url: baseUrl.trim() });
      setLabel(""); setKey(""); setBaseUrl(""); load();
    } catch (e: any) { setErr(String(e.message || e)); } finally { setBusy(false); }
  };
  const del = async (id: number) => { await api.deleteConnection(id); load(); };

  return (
    <div>
      <div style={label_}>Model connections</div>
      <p className="muted" style={{ fontSize: 12.5, margin: "0 0 10px" }}>
        Provider keys used to re-run captured calls in the trace playground. Stored encrypted;
        the key is shown only once, here. Every run uses your own key — add a connection before
        using the playground, replay, or flow tests.
      </p>

      {err && <div style={errBox}>{err}</div>}

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "flex-end", marginBottom: 12 }}>
        <div>
          <div className="muted" style={fieldLbl}>Provider</div>
          <select value={provider} onChange={(e) => setProvider(e.target.value)} style={{ ...input, width: 180 }}>
            {PROVIDERS.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
          </select>
        </div>
        <div>
          <div className="muted" style={fieldLbl}>Label</div>
          <input value={label} onChange={(e) => setLabel(e.target.value)} placeholder={meta.label} style={{ ...input, width: 140 }} />
        </div>
        {meta.needsKey && (
          <div>
            <div className="muted" style={fieldLbl}>API key</div>
            <input value={key} onChange={(e) => setKey(e.target.value)} placeholder="sk-…" type="password" style={{ ...input, width: 200 }} />
          </div>
        )}
        {meta.needsUrl && (
          <div>
            <div className="muted" style={fieldLbl}>Base URL</div>
            <input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://…/v1" style={{ ...input, width: 220 }} />
          </div>
        )}
        <button className="btn btn-sm" onClick={add} disabled={busy}>{busy ? "Adding…" : "Add"}</button>
      </div>

      <div style={{ background: "var(--panel)", border: "1px solid var(--border)", borderRadius: 10, overflow: "hidden" }}>
        {rows == null ? (
          <div className="muted" style={{ fontSize: 12.5, padding: 12 }}>Loading…</div>
        ) : rows.length === 0 ? (
          <div className="muted" style={{ fontSize: 12.5, padding: 12 }}>No connections yet.</div>
        ) : rows.map((c) => (
          <div key={c.id} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "9px 12px", borderBottom: "1px solid var(--border)" }}>
            <div style={{ minWidth: 0 }}>
              <span style={{ fontSize: 13 }}>{c.label}</span>
              <span className="muted mono" style={{ fontSize: 11.5, marginLeft: 8 }}>
                {c.provider}{c.key_hint ? ` · ${c.key_hint}` : ""}{c.base_url ? ` · ${c.base_url}` : ""}
              </span>
            </div>
            <button className="btn btn-sm btn-ghost" onClick={() => del(c.id)}>Remove</button>
          </div>
        ))}
      </div>
    </div>
  );
}

const label_: React.CSSProperties = { fontSize: 11, textTransform: "uppercase", letterSpacing: 0.4, color: "var(--muted)", marginBottom: 6 };
const fieldLbl: React.CSSProperties = { fontSize: 11, marginBottom: 4 };
const input: React.CSSProperties = { background: "var(--panel-2)", color: "var(--text)", border: "1px solid var(--border-strong)", borderRadius: 8, padding: "8px 11px", fontSize: 13 };
const errBox: React.CSSProperties = { background: "color-mix(in srgb, var(--red) 12%, transparent)", border: "1px solid var(--red)", color: "var(--red)", borderRadius: 8, padding: "8px 12px", fontSize: 13, marginBottom: 12 };
