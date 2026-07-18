"use client";

import { useEffect, useState } from "react";
import { api, TraceSpan, TraceSummary } from "@/lib/api";
import TopNav from "@/components/TopNav";

const TYPE_COLOR: Record<string, string> = {
  agent: "var(--accent)", llm: "var(--blue)", tool: "var(--purple)", step: "var(--muted)",
};

export default function TracesPage() {
  const [traces, setTraces] = useState<TraceSummary[]>([]);
  const [sel, setSel] = useState<string | null>(null);
  const [spans, setSpans] = useState<TraceSpan[] | null>(null);

  const load = () => api.traces().then(setTraces).catch(() => {});
  useEffect(() => {
    load();
    const t = setInterval(load, 5000);   // live-ish: new traces stream in
    return () => clearInterval(t);
  }, []);
  useEffect(() => {
    if (!sel) { setSpans(null); return; }
    let cancelled = false;
    setSpans(null);
    api.trace(sel).then((s) => { if (!cancelled) setSpans(s); }).catch(() => {});
    return () => { cancelled = true; };
  }, [sel]);

  const fmt = (s?: string) => (s ? new Date(s).toLocaleString() : "");

  return (
    <>
      <TopNav />
      <main style={{ maxWidth: 1180, margin: "0 auto", padding: "24px 20px 80px" }}>
        <h1 style={{ fontSize: 22, margin: "0 0 4px" }}>Traces</h1>
        <p className="muted" style={{ margin: "0 0 20px", fontSize: 13.5 }}>
          Every run your agent makes, captured from one decorator — the whole flow of model
          calls, tools, and steps, nested as it actually ran.
        </p>

        {traces.length === 0 ? (
          <div style={{ ...panel, textAlign: "center", padding: 40 }}>
            <div style={{ fontSize: 14, marginBottom: 6 }}>No traces yet.</div>
            <div className="muted" style={{ fontSize: 13 }}>
              Add <span className="mono">@pk.trace</span> to your agent (see Project keys) and run it.
            </div>
          </div>
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "320px 1fr", gap: 16 }}>
            <div style={{ ...panel, padding: 0, maxHeight: "74vh", overflowY: "auto" }}>
              {traces.map((t) => (
                <button key={t.trace_id || t.id} onClick={() => setSel(t.trace_id)} style={row(sel === t.trace_id)}>
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                    <span style={{ fontWeight: 500, fontSize: 13, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {t.label || `run ${t.id}`}
                    </span>
                    <span style={{ ...dot, background: t.status === "failed" ? "var(--red)" : "var(--green)" }} />
                  </div>
                  <div className="muted" style={{ fontSize: 11.5, marginTop: 3 }}>
                    {t.span_count} span{t.span_count === 1 ? "" : "s"} · {t.duration_ms}ms · {fmt(t.created_at)}
                  </div>
                </button>
              ))}
            </div>

            <div style={{ ...panel, minHeight: 220 }}>
              {!sel ? (
                <div className="muted" style={{ fontSize: 13 }}>Select a trace to see its flow.</div>
              ) : !spans ? (
                <div className="muted" style={{ fontSize: 13 }}>Loading…</div>
              ) : (
                <Tree spans={spans} />
              )}
            </div>
          </div>
        )}
      </main>
    </>
  );
}

function Tree({ spans }: { spans: TraceSpan[] }) {
  const [open, setOpen] = useState<string | null>(spans[0]?.span_id ?? null);
  const kids: Record<string, TraceSpan[]> = {};
  const ids = new Set(spans.map((s) => s.span_id));
  for (const s of spans) {
    const p = s.parent_span_id && ids.has(s.parent_span_id) ? s.parent_span_id : "__root__";
    (kids[p] ||= []).push(s);
  }

  // Time-proportional waterfall: epoch-ns overflow JS floats, so anchor at the trace start
  // and work in BigInt deltas (a trace spans at most seconds, well within Number range).
  const startNs = (s: TraceSpan): bigint | null => {
    const v = s.result?.meta?.start_ns;
    return v ? BigInt(v) : null;
  };
  const starts = spans.map(startNs).filter((x): x is bigint => x !== null);
  const t0 = starts.length ? starts.reduce((a, b) => (b < a ? b : a)) : 0n;
  let totalNs = 1;
  for (const s of spans) {
    const st = startNs(s);
    if (st === null) continue;
    const end = Number(st - t0) + (s.duration_ms || 0) * 1e6;
    if (end > totalNs) totalNs = end;
  }
  const bar = (s: TraceSpan) => {
    const st = startNs(s);
    if (st === null) return null;
    const left = (Number(st - t0) / totalNs) * 100;
    const width = Math.max(((s.duration_ms || 0) * 1e6 / totalNs) * 100, 1.2);
    return { left: Math.min(left, 99), width: Math.min(width, 100 - Math.min(left, 99)) };
  };

  const render = (parent: string, depth: number): React.ReactNode =>
    (kids[parent] || []).map((s) => {
      const b = bar(s);
      return (
        <div key={s.span_id}>
          <button onClick={() => setOpen(open === s.span_id ? null : s.span_id)} style={spanRow(open === s.span_id)}>
            <span style={{ paddingLeft: depth * 16, display: "inline-flex", alignItems: "center", gap: 8, minWidth: 0, flex: "0 0 46%" }}>
              <span style={badge(s.type)}>{s.type}</span>
              <span style={{ fontSize: 12.5, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.label}</span>
            </span>
            <span style={{ position: "relative", flex: 1, height: 16, background: "var(--bg-2)", borderRadius: 4 }}>
              {b && <span style={{ position: "absolute", top: 3, height: 10, borderRadius: 3,
                left: `${b.left}%`, width: `${b.width}%`, minWidth: 3,
                background: s.status === "failed" ? "var(--red)" : (TYPE_COLOR[s.type] || "var(--muted)"), opacity: 0.85 }} />}
            </span>
            <span className="muted" style={{ fontSize: 11, flexShrink: 0, width: 58, textAlign: "right" }}>
              {s.duration_ms}ms
            </span>
          </button>
          {open === s.span_id && (
            <div style={{ padding: `4px 0 10px ${depth * 16 + 14}px` }}>
              {s.request?.model && <div className="muted mono" style={{ fontSize: 11.5, marginBottom: 6 }}>{s.request.model}</div>}
              <Field label="Input">{textOf(s.request?.input)}</Field>
              <Field label="Output">{textOf(s.result?.text)}</Field>
              {s.error && <Field label="Error">{s.error}</Field>}
            </div>
          )}
          {render(s.span_id, depth + 1)}
        </div>
      );
    });
  return <div>{render("__root__", 0)}</div>;
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  const empty = !children || (typeof children === "string" && !children.trim());
  return (
    <div style={{ marginBottom: 8 }}>
      <div className="muted" style={{ fontSize: 10.5, textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 4 }}>{label}</div>
      <pre style={pre}>{empty ? <span className="muted">—</span> : children}</pre>
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
  margin: 0, padding: 10, borderRadius: 8, background: "var(--bg-2)", border: "1px solid var(--border)",
  fontSize: 12, lineHeight: 1.5, fontFamily: "var(--font-mono)", whiteSpace: "pre-wrap",
  wordBreak: "break-word", maxHeight: 240, overflowY: "auto",
};
const dot: React.CSSProperties = { width: 8, height: 8, borderRadius: 999, flexShrink: 0, marginTop: 4 };
function row(active: boolean): React.CSSProperties {
  return {
    display: "block", width: "100%", textAlign: "left", padding: "11px 14px",
    background: active ? "var(--accent-soft)" : "transparent", color: "var(--text)",
    border: "none", borderBottom: "1px solid var(--border)", cursor: "pointer",
  };
}
function spanRow(active: boolean): React.CSSProperties {
  return {
    display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10, width: "100%",
    textAlign: "left", padding: "7px 8px", borderRadius: 7, cursor: "pointer", color: "var(--text)",
    background: active ? "var(--panel-2)" : "transparent", border: "1px solid transparent",
  };
}
function badge(type: string): React.CSSProperties {
  return {
    fontSize: 10, fontWeight: 600, textTransform: "uppercase", letterSpacing: 0.3,
    padding: "2px 6px", borderRadius: 5, flexShrink: 0,
    color: TYPE_COLOR[type] || "var(--muted)", border: `1px solid ${TYPE_COLOR[type] || "var(--border-strong)"}`,
  };
}
