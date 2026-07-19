"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api, TraceSpan, TraceSummary } from "@/lib/api";
import { Skeleton, SkeletonStyles } from "@/components/Skeleton";
import TopNav from "@/components/TopNav";
import TraceDetail from "@/components/TraceDetail";

function ListSkeleton() {
  return <><Skeleton w="65%" h={12} /><Skeleton w="85%" h={10} mt={5} /><SkeletonStyles /></>;
}

function TraceRow({ t, active, onClick, fmt, indent }: {
  t: TraceSummary; active: boolean; onClick: () => void; fmt: (s?: string) => string; indent?: boolean;
}) {
  return (
    <button onClick={onClick} style={{ ...row(active), paddingLeft: indent ? 26 : 14 }} title={fmt(t.created_at)}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "center" }}>
        <span style={{ fontWeight: 500, fontSize: 13, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {t.label || `run ${t.id}`}
        </span>
        {t.status === "failed"
          ? <span style={failBadge}>failed</span>
          : <span style={{ ...dot, background: "var(--green)" }} />}
      </div>
      <div className="muted" style={{ fontSize: 11.5, marginTop: 3 }}>
        {t.span_count} span{t.span_count === 1 ? "" : "s"} · {t.duration_ms}ms{t.tokens ? ` · ${t.tokens} tok` : ""} · {relTime(t.created_at)}
        {!indent && t.session_id ? <span style={{ color: "var(--purple)" }}> · ◆ {t.session_id}</span> : ""}
      </div>
    </button>
  );
}

// Group traces by session_id (ungrouped last), with per-group token totals.
function sessionGroups(traces: TraceSummary[]) {
  const map = new Map<string, TraceSummary[]>();
  for (const t of traces) {
    const k = t.session_id || "";
    (map.get(k) || map.set(k, []).get(k)!).push(t);
  }
  return Array.from(map.entries())
    .map(([session, items]) => ({ key: session || "__none__", session, items,
      tokens: items.reduce((n, t) => n + (t.tokens || 0), 0) }))
    .sort((a, b) => (a.session ? 0 : 1) - (b.session ? 0 : 1));   // real sessions first
}

// "2m ago" style relative time, with a couple of coarser buckets. Absolute goes on the title.
function relTime(iso?: string): string {
  if (!iso) return "";
  const d = (Date.now() - new Date(iso).getTime()) / 1000;
  if (d < 45) return "just now";
  if (d < 3600) return `${Math.round(d / 60)}m ago`;
  if (d < 86400) return `${Math.round(d / 3600)}h ago`;
  return `${Math.round(d / 86400)}d ago`;
}

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
  const [model, setModel] = useState("");
  const [sort, setSort] = useState<"recent" | "slowest" | "tokens">("recent");
  const [groupBySession, setGroupBySession] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [listOpen, setListOpen] = useState(true);

  const load = useCallback(() => {
    api.traces({ status: failuresOnly ? "failed" : undefined, window_hours: windowHours || undefined })
      .then((t) => { setTraces(t); setLoaded(true); }).catch(() => setLoaded(true));
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
  const modelOptions = Array.from(new Set(traces.map((t) => t.model).filter(Boolean))) as string[];
  const hasSessions = traces.some((t) => t.session_id);
  const shown = traces
    .filter((t) =>
      (!q || (t.label || "").toLowerCase().includes(q.toLowerCase())) &&
      (!model || t.model === model))
    .sort((a, b) =>
      sort === "slowest" ? (b.duration_ms || 0) - (a.duration_ms || 0)
      : sort === "tokens" ? (b.tokens || 0) - (a.tokens || 0)
      : b.id - a.id);   // recent (default) — the API already returns newest-first by id

  return (
    <>
      <TopNav />
      <main style={{ maxWidth: sel ? 1600 : 1180, margin: "0 auto", padding: "24px 20px 80px", transition: "max-width .2s" }}>
        <h1 style={{ fontSize: 22, margin: "0 0 4px" }}>Traces</h1>
        <p className="muted" style={{ margin: "0 0 20px", fontSize: 13.5 }}>
          Every run your agent makes, captured from one decorator — the whole flow of model
          calls, tools, and steps, nested as it actually ran.
        </p>

        {traces.length === 0 && !failuresOnly && !windowHours ? (
          <Onboarding origin={origin} />
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: listOpen ? "300px 1fr" : "0 1fr", gap: listOpen ? 16 : 0, transition: "grid-template-columns .2s, gap .2s", position: "relative" }}>
            {/* collapse the trace list to give the flow studio the whole width */}
            {sel && (
              <button onClick={() => setListOpen((o) => !o)} title={listOpen ? "Hide list" : "Show list"}
                style={{ position: "absolute", top: 6, left: listOpen ? 300 : -4, zIndex: 6, width: 22, height: 22, borderRadius: 6, border: "1px solid var(--border-strong)", background: "var(--panel)", color: "var(--muted)", cursor: "pointer", fontSize: 14, lineHeight: 1, display: "grid", placeItems: "center" }}>
                {listOpen ? "‹" : "›"}
              </button>
            )}
            <div style={{ display: listOpen ? "flex" : "none", flexDirection: "column", gap: 8, maxHeight: "76vh" }}>
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
              <div style={{ display: "flex", gap: 6 }}>
                {modelOptions.length > 1 && (
                  <select value={model} onChange={(e) => setModel(e.target.value)}
                    style={{ ...chip(!!model), flex: 1, appearance: "none" }} title="Filter by model">
                    <option value="">All models</option>
                    {modelOptions.map((m) => <option key={m} value={m}>{m}</option>)}
                  </select>
                )}
                <select value={sort} onChange={(e) => setSort(e.target.value as any)}
                  style={{ ...chip(sort !== "recent"), flex: 1, appearance: "none" }} title="Sort">
                  <option value="recent">↓ Recent</option>
                  <option value="slowest">↓ Slowest</option>
                  <option value="tokens">↓ Most tokens</option>
                </select>
                {hasSessions && (
                  <button onClick={() => setGroupBySession((v) => !v)} style={chip(groupBySession)}
                    title="Group multi-turn runs by session">◆ Sessions</button>
                )}
              </div>
              <div style={{ ...panel, padding: 0, overflowY: "auto" }}>
              {!loaded ? (
                <div style={{ padding: 12 }}>
                  {Array.from({ length: 6 }).map((_, i) => (
                    <div key={i} style={{ padding: "8px 2px" }}>
                      <ListSkeleton />
                    </div>
                  ))}
                </div>
              ) : shown.length === 0 ? (
                <div className="muted" style={{ padding: 14, fontSize: 12.5 }}>No traces match.</div>
              ) : groupBySession ? (
                sessionGroups(shown).map((g) => (
                  <div key={g.key}>
                    <div style={sessionHeader}>
                      <span>{g.session ? `◆ ${g.session}` : "No session"}</span>
                      <span className="muted" style={{ fontWeight: 400 }}>
                        {g.items.length} turn{g.items.length === 1 ? "" : "s"}{g.tokens ? ` · ${g.tokens} tok` : ""}
                      </span>
                    </div>
                    {g.items.map((t) => (
                      <TraceRow key={t.trace_id || t.id} t={t} active={sel === t.trace_id} onClick={() => setSel(t.trace_id)} fmt={fmt} indent />
                    ))}
                  </div>
                ))
              ) : shown.map((t) => (
                <TraceRow key={t.trace_id || t.id} t={t} active={sel === t.trace_id} onClick={() => setSel(t.trace_id)} fmt={fmt} />
              ))}
              </div>
            </div>

            <div style={{ ...panel, minHeight: 220 }}>
              {!sel ? (
                <div className="muted" style={{ fontSize: 13 }}>Select a trace to see its flow.</div>
              ) : !spans ? (
                <DetailSkeleton />
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

function DetailSkeleton() {
  const bar = (w: string, h = 14, mt = 10): React.CSSProperties => ({
    width: w, height: h, marginTop: mt, borderRadius: 6, background: "var(--panel-2)",
    animation: "pk-shimmer 1.2s ease-in-out infinite",
  });
  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 12 }}>
        <div style={bar("40%", 16, 0)} />
        <div style={bar("120px", 26, 0)} />
      </div>
      <div style={{ ...bar("100%", 300, 0), borderRadius: 10 }} />
      <div style={bar("55%")} />
      <div style={bar("80%")} />
      <div style={bar("70%")} />
      <style jsx>{`@keyframes pk-shimmer { 0%,100% { opacity: .55 } 50% { opacity: .85 } }`}</style>
    </div>
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
const failBadge: React.CSSProperties = {
  flexShrink: 0, fontSize: 9.5, fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.3,
  color: "var(--red)", border: "1px solid var(--red)", borderRadius: 5, padding: "1px 6px",
};
const sessionHeader: React.CSSProperties = {
  display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8,
  padding: "7px 14px", fontSize: 11.5, fontWeight: 600, color: "var(--purple)",
  background: "var(--bg-2)", borderBottom: "1px solid var(--border)", position: "sticky", top: 0,
};
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
