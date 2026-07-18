"use client";

import { useEffect, useState } from "react";
import { api, Connection, RunSummary } from "@/lib/api";
import TopNav from "@/components/TopNav";

export default function TracesPage() {
  const [traces, setTraces] = useState<RunSummary[]>([]);
  const [sel, setSel] = useState<number | null>(null);
  const [detail, setDetail] = useState<any>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [conns, setConns] = useState<Connection[]>([]);
  const [saveOpen, setSaveOpen] = useState(false);

  const flash = (t: string) => { setToast(t); setTimeout(() => setToast(null), 3500); };
  const load = () => api.runs("trace").then(setTraces).catch(() => {});
  useEffect(() => {
    load();
    // llm connections can serve as both the prompt target and the llm_judge
    api.connections().then((cs) => setConns(cs.filter((c) => c.kind === "llm"))).catch(() => {});
  }, []);
  useEffect(() => {
    if (!sel) { setDetail(null); return; }
    let cancelled = false;
    setDetail(null);
    api.getRun(sel).then((d) => { if (!cancelled) setDetail(d); }).catch(() => {});
    return () => { cancelled = true; };
  }, [sel]);

  const fmt = (s?: string) => (s ? new Date(s).toLocaleString() : "");

  return (
    <>
      <TopNav />
      <main style={{ maxWidth: 1100, margin: "0 auto", padding: "24px 20px 80px" }}>
        <h1 style={{ fontSize: 22, margin: "0 0 4px" }}>Traces</h1>
        <p className="muted" style={{ margin: "0 0 20px", fontSize: 13.5 }}>
          Runs captured from your agents via the tracing decorator or any OpenTelemetry
          exporter. Turn any one into a regression test.
        </p>

        {traces.length === 0 ? (
          <div style={{ ...panel, textAlign: "center", padding: 40 }}>
            <div style={{ fontSize: 14, marginBottom: 6 }}>No traces yet.</div>
            <div className="muted" style={{ fontSize: 13 }}>
              Add <span className="mono">@pk.trace</span> to your agent (see the API Keys page) and run it.
            </div>
          </div>
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "340px 1fr", gap: 16 }}>
            {/* list */}
            <div style={{ ...panel, padding: 0, maxHeight: "70vh", overflowY: "auto" }}>
              {traces.map((t) => (
                <button key={t.id} onClick={() => setSel(t.id)} style={row(sel === t.id)}>
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                    <span style={{ fontWeight: 500, fontSize: 13, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {t.label || `run ${t.id}`}
                    </span>
                    <span style={{ ...dot, background: t.status === "failed" ? "var(--red)" : "var(--green)" }} />
                  </div>
                  <div className="muted" style={{ fontSize: 11.5, marginTop: 3 }}>{fmt(t.created_at)} · {t.duration_ms}ms</div>
                </button>
              ))}
            </div>

            {/* detail */}
            <div style={{ ...panel, minHeight: 200 }}>
              {!detail ? (
                <div className="muted" style={{ fontSize: 13 }}>Select a trace to inspect it.</div>
              ) : (
                <>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
                    <div>
                      <div style={{ fontSize: 15, fontWeight: 600 }}>{detail.label || `run ${detail.id}`}</div>
                      <div className="muted" style={{ fontSize: 12, marginTop: 2 }}>
                        {detail.request?.model && <span className="mono">{detail.request.model}</span>}
                        {detail.request?.provider && ` · ${detail.request.provider}`} · {detail.status}
                      </div>
                    </div>
                    <button className="btn" onClick={() => setSaveOpen(true)}>Save as test</button>
                  </div>

                  <Field label="Input">{textOf(detail.request?.input)}</Field>
                  <Field label="Output">{textOf(detail.result?.text)}</Field>
                  {detail.error && <Field label="Error">{detail.error}</Field>}
                </>
              )}
            </div>
          </div>
        )}
      </main>
      {saveOpen && detail && (
        <SaveTestModal
          run={detail}
          connections={conns}
          onClose={() => setSaveOpen(false)}
          onSaved={(name) => {
            setSaveOpen(false);
            flash(`Saved as test "${name}". Find it in the Console to run or edit.`);
          }}
        />
      )}
      {toast && <div className="toast">{toast}</div>}
    </>
  );
}

function SaveTestModal({ run, connections, onClose, onSaved }: {
  run: any; connections: Connection[];
  onClose: () => void; onSaved: (name: string) => void;
}) {
  const [name, setName] = useState(run.label || "trace test");
  const [connId, setConnId] = useState<string>(connections[0] ? String(connections[0].id) : "");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const save = async () => {
    setBusy(true); setErr(null);
    try {
      const t = await api.runToTest(run.id, {
        name: name.trim() || "trace test",
        connection_id: connId ? Number(connId) : null,
      });
      onSaved(t.name);
    } catch (e: any) { setErr(e.message); setBusy(false); }
  };

  return (
    <div style={overlay} onClick={onClose}>
      <div style={modal} onClick={(e) => e.stopPropagation()}>
        <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 4 }}>Save as test</div>
        <p className="muted" style={{ margin: "0 0 16px", fontSize: 12.5 }}>
          Creates a prompt test with an <span className="mono">llm_judge</span> assertion against
          the captured output. Pick the connection to run and judge it against.
        </p>

        <label style={lbl}>Name</label>
        <input value={name} onChange={(e) => setName(e.target.value)} style={input} autoFocus />

        <label style={lbl}>Connection</label>
        <select value={connId} onChange={(e) => setConnId(e.target.value)} style={input}>
          <option value="">Attach later (test won't run until you set one)</option>
          {connections.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
        {connections.length === 0 && (
          <div className="hint" style={{ marginTop: 6 }}>
            No LLM connections yet — add one in the Console, or save now and attach it later.
          </div>
        )}

        {err && <div style={{ color: "var(--red)", fontSize: 12.5, marginTop: 10 }}>{err}</div>}
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 20 }}>
          <button className="btn btn-ghost" onClick={onClose} disabled={busy}>Cancel</button>
          <button className="btn" onClick={save} disabled={busy}>{busy ? "Saving…" : "Save test"}</button>
        </div>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 12 }}>
      <div className="muted" style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 5 }}>{label}</div>
      <pre style={pre}>{children || <span className="muted">—</span>}</pre>
    </div>
  );
}

function textOf(v: any): string {
  if (v == null) return "";
  return typeof v === "string" ? v : JSON.stringify(v, null, 2);
}

const panel: React.CSSProperties = {
  background: "var(--panel)", border: "1px solid var(--border)", borderRadius: 12, padding: 16,
};
const pre: React.CSSProperties = {
  margin: 0, padding: 12, borderRadius: 8, background: "var(--bg-2)", border: "1px solid var(--border)",
  fontSize: 12.5, lineHeight: 1.55, fontFamily: "var(--font-mono)", whiteSpace: "pre-wrap",
  wordBreak: "break-word", maxHeight: 260, overflowY: "auto",
};
const dot: React.CSSProperties = { width: 8, height: 8, borderRadius: 999, flexShrink: 0, marginTop: 4 };
const overlay: React.CSSProperties = {
  position: "fixed", inset: 0, background: "rgba(0,0,0,0.55)", display: "flex",
  alignItems: "center", justifyContent: "center", zIndex: 50, padding: 20,
};
const modal: React.CSSProperties = {
  width: "min(460px, 100%)", background: "var(--panel)", border: "1px solid var(--border-strong)",
  borderRadius: 14, padding: 22, boxShadow: "var(--sh-2)",
};
const lbl: React.CSSProperties = {
  display: "block", fontSize: 11, textTransform: "uppercase", letterSpacing: 0.4,
  color: "var(--muted)", margin: "12px 0 5px",
};
const input: React.CSSProperties = {
  width: "100%", background: "var(--panel-2)", color: "var(--text)",
  border: "1px solid var(--border-strong)", borderRadius: 8, padding: "9px 11px", fontSize: 13.5,
};
function row(active: boolean): React.CSSProperties {
  return {
    display: "block", width: "100%", textAlign: "left", padding: "11px 14px",
    background: active ? "var(--accent-soft)" : "transparent", color: "var(--text)",
    border: "none", borderBottom: "1px solid var(--border)", cursor: "pointer",
  };
}
