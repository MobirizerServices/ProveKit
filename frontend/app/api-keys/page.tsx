"use client";

import { useEffect, useState } from "react";
import { api, ApiKey } from "@/lib/api";
import TopNav from "@/components/TopNav";

export default function ApiKeysPage() {
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [fresh, setFresh] = useState<string | null>(null); // plaintext, shown exactly once
  const [toast, setToast] = useState<string | null>(null);
  const [origin, setOrigin] = useState("https://your-provekit-host");

  const flash = (t: string) => { setToast(t); setTimeout(() => setToast(null), 2000); };
  const load = () => api.apiKeys().then(setKeys).catch(() => {});
  useEffect(() => { load(); setOrigin(window.location.origin); }, []);

  const create = async () => {
    setBusy(true);
    try {
      const k = await api.createApiKey(name.trim());
      setFresh(k.key);           // reveal once; it is never retrievable again
      setName("");
      load();
    } catch (e: any) { flash(e.message); }
    finally { setBusy(false); }
  };

  const revoke = async (id: number, label: string) => {
    if (!confirm(`Revoke "${label || "this key"}"? Anything using it stops working immediately.`)) return;
    try { await api.revokeApiKey(id); flash("Revoked"); load(); }
    catch (e: any) { flash(e.message); }
  };

  const copy = (t: string) => { navigator.clipboard?.writeText(t); flash("Copied"); };

  const fmt = (s: string | null | undefined) => (s ? new Date(s).toLocaleString() : "—");

  return (
    <>
      <TopNav />
      <main style={{ maxWidth: 860, margin: "0 auto", padding: "28px 20px 80px" }}>
        <h1 style={{ fontSize: 22, margin: "0 0 4px" }}>API keys</h1>
        <p className="muted" style={{ margin: "0 0 24px", fontSize: 13.5 }}>
          Bearer keys for machine access — the tracing decorator, CI, and the CLI. Drop one in
          your <span className="mono">.env</span> as <span className="mono">PROVEKIT_API_KEY</span>.
          The key is shown once at creation and stored only as a hash.
        </p>

        {/* create */}
        <div style={panel}>
          <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && !busy && create()}
              placeholder="Key name (e.g. ci, prod-agent)"
              style={input}
            />
            <button className="btn" onClick={create} disabled={busy}>
              {busy ? "Creating…" : "Create key"}
            </button>
          </div>

          {fresh && (
            <div style={reveal}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                <b style={{ fontSize: 13 }}>Copy your key now — it won't be shown again.</b>
                <button className="btn btn-ghost btn-sm" onClick={() => setFresh(null)}>Dismiss</button>
              </div>
              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <code className="mono" style={keyBox}>{fresh}</code>
                <button className="btn btn-sm" onClick={() => copy(fresh)}>Copy</button>
              </div>
              <div className="hint" style={{ marginTop: 10 }}>Add to your <span className="mono">.env</span>:</div>
              <code className="mono" style={{ ...keyBox, display: "block", marginTop: 4 }}>
                PROVEKIT_API_KEY={fresh}
              </code>
            </div>
          )}
        </div>

        {/* usage */}
        <div style={{ ...panel, marginTop: 18 }}>
          <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>Use your key</div>
          <p className="muted" style={{ margin: "0 0 10px", fontSize: 13 }}>
            Wrap your agent's entrypoint — each call is captured as a run you can turn into a
            regression test. Any OpenAI/Anthropic calls inside are captured automatically.
          </p>
          <pre style={code}>{`pip install "provekit[trace]"

# .env
PROVEKIT_API_KEY=pk_...
PROVEKIT_ENDPOINT=${origin}

import provekit.trace as pk

@pk.trace(name="support-agent")
def run_agent(question: str) -> str:
    ...  # your agent; the input + output land in the portal`}</pre>
        </div>

        {/* list */}
        <div style={{ ...panel, marginTop: 18, padding: 0 }}>
          {keys.length === 0 ? (
            <div className="muted" style={{ padding: 20, fontSize: 13.5 }}>No API keys yet.</div>
          ) : (
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13.5 }}>
              <thead>
                <tr style={{ textAlign: "left", color: "var(--muted)" }}>
                  <th style={th}>Name</th><th style={th}>Key</th><th style={th}>Last used</th>
                  <th style={th}>Created</th><th style={{ ...th, textAlign: "right" }}></th>
                </tr>
              </thead>
              <tbody>
                {keys.map((k) => (
                  <tr key={k.id} style={{ borderTop: "1px solid var(--border)", opacity: k.revoked ? 0.5 : 1 }}>
                    <td style={td}>{k.name || <span className="muted">unnamed</span>}</td>
                    <td style={td}><span className="mono">{k.prefix}…</span></td>
                    <td style={td}>{fmt(k.last_used_at)}</td>
                    <td style={td}>{fmt(k.created_at)}</td>
                    <td style={{ ...td, textAlign: "right" }}>
                      {k.revoked
                        ? <span className="tag">revoked</span>
                        : <button className="btn btn-ghost btn-sm" onClick={() => revoke(k.id, k.name)}>Revoke</button>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </main>
      {toast && <div className="toast">{toast}</div>}
    </>
  );
}

const panel: React.CSSProperties = {
  background: "var(--panel)", border: "1px solid var(--border)", borderRadius: 12, padding: 16,
};
const input: React.CSSProperties = {
  flex: 1, background: "var(--panel-2)", color: "var(--text)", border: "1px solid var(--border-strong)",
  borderRadius: 8, padding: "9px 12px", fontSize: 13.5,
};
const reveal: React.CSSProperties = {
  marginTop: 14, padding: 14, borderRadius: 10, background: "var(--accent-soft)",
  border: "1px solid var(--accent-ring)",
};
const keyBox: React.CSSProperties = {
  flex: 1, background: "var(--bg-2)", border: "1px solid var(--border-strong)", borderRadius: 8,
  padding: "8px 10px", fontSize: 12.5, overflowX: "auto", whiteSpace: "nowrap",
};
const th: React.CSSProperties = { padding: "10px 14px", fontWeight: 500, fontSize: 12 };
const td: React.CSSProperties = { padding: "11px 14px" };
const code: React.CSSProperties = {
  margin: 0, padding: 14, borderRadius: 8, background: "var(--bg-2)",
  border: "1px solid var(--border-strong)", fontSize: 12.5, lineHeight: 1.6,
  fontFamily: "var(--font-mono)", overflowX: "auto", whiteSpace: "pre",
};
