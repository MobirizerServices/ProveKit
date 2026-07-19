"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, TraceSpan, TraceSummary } from "@/lib/api";
import TopNav from "@/components/TopNav";
import TraceGraph from "@/components/TraceGraph";

const TYPE_COLOR: Record<string, string> = {
  agent: "var(--accent)", llm: "var(--blue)", tool: "var(--purple)", step: "var(--muted)",
};

export default function TracesPage() {
  const [traces, setTraces] = useState<TraceSummary[]>([]);
  const [sel, setSel] = useState<string | null>(null);
  const [spans, setSpans] = useState<TraceSpan[] | null>(null);
  const [origin, setOrigin] = useState("https://your-provekit-host");

  const load = () => api.traces().then(setTraces).catch(() => {});
  useEffect(() => {
    setOrigin(window.location.origin);
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
          <Onboarding origin={origin} />
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
                <TraceDetail spans={spans} />
              )}
            </div>
          </div>
        )}
      </main>
    </>
  );
}

function Onboarding({ origin }: { origin: string }) {
  const [copied, setCopied] = useState(false);
  const snippet = `pip install "provekit[trace]"

# .env
PROVEKIT_API_KEY=pk_...          # ← create one in Project keys
PROVEKIT_ENDPOINT=${origin}

import provekit.trace as pk

@pk.trace(name="my-agent")
def run_agent(question: str) -> str:
    ...   # your agent — OpenAI/Anthropic calls capture themselves`;
  const copy = () => { navigator.clipboard?.writeText(snippet); setCopied(true); setTimeout(() => setCopied(false), 1500); };

  return (
    <div style={{ ...panel, maxWidth: 720 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
        <span className="pulse-dot" />
        <span style={{ fontSize: 15, fontWeight: 600 }}>Listening for your first trace…</span>
      </div>
      <p className="muted" style={{ margin: "0 0 16px", fontSize: 13 }}>
        This page updates automatically the moment a trace arrives. Three steps to get there:
      </p>
      <ol style={{ margin: "0 0 14px", paddingLeft: 18, fontSize: 13.5, lineHeight: 1.7 }}>
        <li>Grab a key on the <Link href="/api-keys" style={{ color: "var(--accent)" }}>Project keys</Link> page.</li>
        <li>Drop the snippet below into your agent (fill in the key).</li>
        <li>Run your agent — the run shows up here as a nested flow.</li>
      </ol>
      <div style={{ position: "relative" }}>
        <button className="btn btn-sm" onClick={copy} style={{ position: "absolute", top: 8, right: 8, zIndex: 1 }}>
          {copied ? "Copied" : "Copy"}
        </button>
        <pre style={{ ...pre, maxHeight: "none", padding: 14, fontSize: 12.5 }}>{snippet}</pre>
      </div>
      <style jsx>{`
        .pulse-dot { width: 9px; height: 9px; border-radius: 999px; background: var(--green); box-shadow: 0 0 0 0 var(--green); animation: pk-pulse 1.8s infinite; }
        @keyframes pk-pulse { 0% { box-shadow: 0 0 0 0 rgba(80,200,120,0.5); } 70% { box-shadow: 0 0 0 8px rgba(80,200,120,0); } 100% { box-shadow: 0 0 0 0 rgba(80,200,120,0); } }
      `}</style>
    </div>
  );
}

function TraceDetail({ spans }: { spans: TraceSpan[] }) {
  const [view, setView] = useState<"flow" | "waterfall">("flow");
  const ids = new Set(spans.map((s) => s.span_id));
  const root = spans.find((s) => !s.parent_span_id || !ids.has(s.parent_span_id));
  const [picked, setPicked] = useState<string | null>(root?.span_id ?? null);
  const totalTok = spans.reduce((n, s) => n + (s.result?.meta?.usage?.input_tokens || 0) + (s.result?.meta?.usage?.output_tokens || 0), 0);
  const sel = spans.find((s) => s.span_id === picked) || root;

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10, paddingBottom: 8, borderBottom: "1px solid var(--border)" }}>
        <div style={{ minWidth: 0 }}>
          <span style={{ fontSize: 14, fontWeight: 600 }}>{root?.label || "trace"}</span>
          <span className="muted" style={{ fontSize: 12, marginLeft: 8 }}>
            {spans.length} span{spans.length === 1 ? "" : "s"} · {root?.duration_ms ?? 0}ms{totalTok ? ` · ${totalTok} tokens` : ""}
          </span>
        </div>
        <div style={{ display: "flex", gap: 3, background: "var(--bg-2)", borderRadius: 8, padding: 2, flexShrink: 0 }}>
          {(["flow", "waterfall"] as const).map((v) => (
            <button key={v} onClick={() => setView(v)} style={toggleBtn(view === v)}>
              {v === "flow" ? "Flow" : "Waterfall"}
            </button>
          ))}
        </div>
      </div>

      {view === "flow" ? (
        <>
          <TraceGraph spans={spans} selected={picked} onSelect={setPicked} />
          {sel && (
            <div style={{ marginTop: 12 }}>
              <div className="muted" style={{ fontSize: 11.5, marginBottom: 8 }}>
                <b style={{ color: "var(--text)" }}>{sel.label}</b>
                {sel.request?.model ? ` · ${sel.request.model}` : ""} · {sel.duration_ms}ms
              </div>
              <Field label="Input">{textOf(sel.request?.input)}</Field>
              <Field label="Output">{textOf(sel.result?.text)}</Field>
              {sel.error && <Field label="Error">{sel.error}</Field>}
            </div>
          )}
        </>
      ) : (
        <Tree spans={spans} />
      )}
    </div>
  );
}

function toggleBtn(active: boolean): React.CSSProperties {
  return {
    fontSize: 12, padding: "4px 13px", borderRadius: 6, cursor: "pointer", border: "none",
    background: active ? "var(--panel)" : "transparent",
    color: active ? "var(--text)" : "var(--muted)", fontWeight: active ? 600 : 400,
  };
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
            <span style={{ display: "inline-flex", alignItems: "center", gap: 8, flexShrink: 0 }}>
              {tokens(s) && <span className="muted mono" style={{ fontSize: 10.5 }} title="input → output tokens">{tokens(s)}</span>}
              <span className="muted" style={{ fontSize: 11, width: 54, textAlign: "right" }}>{s.duration_ms}ms</span>
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

function tokens(s: TraceSpan): string | null {
  const u = s.result?.meta?.usage;
  if (!u || u.input_tokens == null) return null;
  return `${u.input_tokens}→${u.output_tokens ?? 0} tok`;
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
