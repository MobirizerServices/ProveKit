"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api, TraceSpan, TraceSummary } from "@/lib/api";
import TopNav from "@/components/TopNav";
import TraceDetail from "@/components/TraceDetail";

const WINDOWS: { label: string; hours: number }[] = [
  { label: "All time", hours: 0 }, { label: "Last hour", hours: 1 },
  { label: "Last 24h", hours: 24 }, { label: "Last 7 days", hours: 168 },
];

export default function TracesPage() {
  const [traces, setTraces] = useState<TraceSummary[]>([]);
  const [sel, setSel] = useState<string | null>(null);
  const [spans, setSpans] = useState<TraceSpan[] | null>(null);
  const [origin, setOrigin] = useState("https://your-provekit-host");
  const [q, setQ] = useState("");
  const [failuresOnly, setFailuresOnly] = useState(false);
  const [windowHours, setWindowHours] = useState(0);

  const load = useCallback(() => {
    api.traces({ status: failuresOnly ? "failed" : undefined, window_hours: windowHours || undefined })
      .then(setTraces).catch(() => {});
  }, [failuresOnly, windowHours]);

  useEffect(() => {
    setOrigin(window.location.origin);
    load();
    const t = setInterval(load, 5000);   // live-ish: new traces stream in
    return () => clearInterval(t);
  }, [load]);
  useEffect(() => {
    if (!sel) { setSpans(null); return; }
    let cancelled = false;
    setSpans(null);
    api.trace(sel).then((s) => { if (!cancelled) setSpans(s); }).catch(() => {});
    return () => { cancelled = true; };
  }, [sel]);

  const fmt = (s?: string) => (s ? new Date(s).toLocaleString() : "");
  const shown = traces.filter((t) => !q || (t.label || "").toLowerCase().includes(q.toLowerCase()));

  return (
    <>
      <TopNav />
      <main style={{ maxWidth: 1180, margin: "0 auto", padding: "24px 20px 80px" }}>
        <h1 style={{ fontSize: 22, margin: "0 0 4px" }}>Traces</h1>
        <p className="muted" style={{ margin: "0 0 20px", fontSize: 13.5 }}>
          Every run your agent makes, captured from one decorator — the whole flow of model
          calls, tools, and steps, nested as it actually ran.
        </p>

        {traces.length === 0 && !failuresOnly && !windowHours ? (
          <Onboarding origin={origin} />
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "320px 1fr", gap: 16 }}>
            <div style={{ display: "flex", flexDirection: "column", gap: 8, maxHeight: "76vh" }}>
              <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Filter traces…"
                style={{ background: "var(--panel-2)", color: "var(--text)", border: "1px solid var(--border-strong)", borderRadius: 8, padding: "8px 11px", fontSize: 13 }} />
              <div style={{ display: "flex", gap: 6 }}>
                <button onClick={() => setFailuresOnly((v) => !v)} style={chip(failuresOnly)}
                  title="Show only failed traces">Failures only</button>
                <select value={windowHours} onChange={(e) => setWindowHours(Number(e.target.value))}
                  style={{ ...chip(windowHours > 0), flex: 1, appearance: "none" }}>
                  {WINDOWS.map((w) => <option key={w.hours} value={w.hours}>{w.label}</option>)}
                </select>
              </div>
              <div style={{ ...panel, padding: 0, overflowY: "auto" }}>
              {shown.length === 0 ? (
                <div className="muted" style={{ padding: 14, fontSize: 12.5 }}>No traces match.</div>
              ) : shown.map((t) => (
                <button key={t.trace_id || t.id} onClick={() => setSel(t.trace_id)} style={row(sel === t.trace_id)}>
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                    <span style={{ fontWeight: 500, fontSize: 13, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {t.label || `run ${t.id}`}
                    </span>
                    <span style={{ ...dot, background: t.status === "failed" ? "var(--red)" : "var(--green)" }} />
                  </div>
                  <div className="muted" style={{ fontSize: 11.5, marginTop: 3 }}>
                    {t.span_count} span{t.span_count === 1 ? "" : "s"} · {t.duration_ms}ms{t.tokens ? ` · ${t.tokens} tok` : ""} · {fmt(t.created_at)}
                    {t.session_id ? <span style={{ color: "var(--purple)" }}> · ◆ {t.session_id}</span> : ""}
                  </div>
                </button>
              ))}
              </div>
            </div>

            <div style={{ ...panel, minHeight: 220 }}>
              {!sel ? (
                <div className="muted" style={{ fontSize: 13 }}>Select a trace to see its flow.</div>
              ) : !spans ? (
                <div className="muted" style={{ fontSize: 13 }}>Loading…</div>
              ) : (
                <TraceDetail spans={spans} traceId={sel ?? undefined} />
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

import provekit.auto              # one import — captures everything below it

# (optional) group a run under a named root:
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
function chip(active: boolean): React.CSSProperties {
  return {
    fontSize: 12, padding: "6px 11px", borderRadius: 8, cursor: "pointer",
    background: active ? "var(--accent-soft)" : "var(--panel-2)",
    color: active ? "var(--accent)" : "var(--muted)",
    border: `1px solid ${active ? "var(--accent)" : "var(--border-strong)"}`,
  };
}
