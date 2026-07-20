"use client";

import { useEffect, useMemo, useState } from "react";
import { api, SavedPrompt } from "@/lib/api";
import TopNav from "@/components/TopNav";

// The saved-prompt registry: every version you saved from the trace playground, grouped by name.
export default function PromptsPage() {
  const [rows, setRows] = useState<SavedPrompt[] | null>(null);
  const [sel, setSel] = useState<string | null>(null);

  const load = () => api.prompts().then(setRows).catch(() => setRows([]));
  useEffect(() => { load(); }, []);

  const byName = useMemo(() => {
    const m = new Map<string, SavedPrompt[]>();
    for (const p of rows || []) { (m.get(p.name) || m.set(p.name, []).get(p.name)!).push(p); }
    for (const v of m.values()) v.sort((a, b) => b.version - a.version);   // newest first
    return m;
  }, [rows]);

  const names = [...byName.keys()];
  const current = sel && byName.get(sel);
  const del = async (id: number) => { await api.deletePrompt(id); load(); };
  const copy = (v: SavedPrompt) => navigator.clipboard?.writeText(JSON.stringify({ model: v.model, messages: v.messages, params: v.params }, null, 2));

  return (
    <>
      <TopNav />
      <main style={{ maxWidth: 1100, margin: "0 auto", padding: "24px 20px 80px" }}>
        <h1 style={{ fontSize: 22, margin: "0 0 4px" }}>Prompts</h1>
        <p className="muted" style={{ margin: "0 0 20px", fontSize: 13.5 }}>
          Prompt versions you saved from the trace <b>playground</b> (▶ Edit &amp; re-run → 💾 Save
          version). Restore one in the playground, or copy it into your code.
        </p>

        {rows == null ? (
          <div className="muted" style={{ fontSize: 13 }}>Loading…</div>
        ) : names.length === 0 ? (
          <div style={{ ...panel }}>
            <div className="muted" style={{ fontSize: 13 }}>
              No saved prompts yet. Open a trace → click an <b>LLM</b> node → <b>▶ Edit &amp; re-run</b> →
              edit the prompt → <b>💾 Save version</b>.
            </div>
          </div>
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "260px 1fr", gap: 16 }}>
            <div style={{ ...panel, padding: 0, overflow: "hidden" }}>
              {names.map((n) => {
                const vs = byName.get(n)!;
                return (
                  <button key={n} onClick={() => setSel(n)} style={row(sel === n)}>
                    <div style={{ fontWeight: 500, fontSize: 13 }}>{n}</div>
                    <div className="muted" style={{ fontSize: 11.5, marginTop: 2 }}>
                      v{vs[0].version} · {vs.length} version{vs.length === 1 ? "" : "s"} · {vs[0].model || "—"}
                    </div>
                  </button>
                );
              })}
            </div>

            <div style={{ ...panel, minHeight: 220 }}>
              {!current ? (
                <div className="muted" style={{ fontSize: 13 }}>Select a prompt.</div>
              ) : (
                <>
                  <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 12 }}>{sel}</div>
                  <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                    {current.map((v) => (
                      <div key={v.id} style={{ border: "1px solid var(--border)", borderRadius: 10, overflow: "hidden" }}>
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "7px 11px", background: "var(--bg-2)" }}>
                          <span style={{ fontSize: 12.5 }}>
                            <b>v{v.version}</b> <span className="muted mono" style={{ fontSize: 11.5 }}>· {v.model || "—"}
                              {v.params?.temperature != null ? ` · temp ${v.params.temperature}` : ""}</span>
                          </span>
                          <span style={{ display: "flex", gap: 6 }}>
                            <button className="btn btn-sm btn-ghost" onClick={() => copy(v)}>Copy JSON</button>
                            <button className="btn btn-sm btn-ghost" onClick={() => del(v.id)}>Delete</button>
                          </span>
                        </div>
                        <div style={{ padding: "8px 11px", display: "flex", flexDirection: "column", gap: 6 }}>
                          {(v.messages || []).map((m, i) => (
                            <div key={i} style={{ fontSize: 12.5 }}>
                              <span className="mono" style={{ fontSize: 10.5, color: "var(--muted)", textTransform: "uppercase" }}>{m.role}</span>
                              <div style={{ whiteSpace: "pre-wrap", marginTop: 2 }}>{m.content}</div>
                            </div>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                </>
              )}
            </div>
          </div>
        )}
      </main>
    </>
  );
}

const panel: React.CSSProperties = { background: "var(--panel)", border: "1px solid var(--border)", borderRadius: 12, padding: 16 };
function row(active: boolean): React.CSSProperties {
  return { display: "block", width: "100%", textAlign: "left", padding: "10px 13px",
    background: active ? "var(--accent-soft)" : "transparent", color: "var(--text)",
    border: "none", borderBottom: "1px solid var(--border)", cursor: "pointer" };
}
