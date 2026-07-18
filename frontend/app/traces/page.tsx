"use client";

import { useEffect, useState } from "react";
import { api, RunSummary } from "@/lib/api";
import TopNav from "@/components/TopNav";

export default function TracesPage() {
  const [traces, setTraces] = useState<RunSummary[]>([]);
  const [sel, setSel] = useState<number | null>(null);
  const [detail, setDetail] = useState<any>(null);
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

  const flash = (t: string) => { setToast(t); setTimeout(() => setToast(null), 3000); };
  const load = () => api.runs("trace").then(setTraces).catch(() => {});
  useEffect(() => { load(); }, []);
  useEffect(() => {
    if (!sel) { setDetail(null); return; }
    let cancelled = false;
    setDetail(null);
    api.getRun(sel).then((d) => { if (!cancelled) setDetail(d); }).catch(() => {});
    return () => { cancelled = true; };
  }, [sel]);

  const saveAsTest = async () => {
    if (!detail) return;
    setSaving(true);
    try {
      const t = await api.runToTest(detail.id, { name: detail.label || "trace test" });
      flash(`Saved as test "${t.name}" — open the Console to attach a connection and run it.`);
    } catch (e: any) { flash(e.message); }
    finally { setSaving(false); }
  };

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
                    <button className="btn" onClick={saveAsTest} disabled={saving}>
                      {saving ? "Saving…" : "Save as test"}
                    </button>
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
      {toast && <div className="toast">{toast}</div>}
    </>
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
function row(active: boolean): React.CSSProperties {
  return {
    display: "block", width: "100%", textAlign: "left", padding: "11px 14px",
    background: active ? "var(--accent-soft)" : "transparent", color: "var(--text)",
    border: "none", borderBottom: "1px solid var(--border)", cursor: "pointer",
  };
}
