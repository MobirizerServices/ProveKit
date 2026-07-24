"use client";

import React from "react";
import { useCallback, useEffect, useState } from "react";
import { api, API_BASE, TraceSpan, TraceSummary } from "@/lib/api";
import { fmtCost } from "@/lib/cost";
import { Skeleton, SkeletonStyles } from "@/components/Skeleton";
import ConsoleShell from "@/components/ConsoleShell";
import PageHero from "@/components/PageHero";
import TraceDetail from "@/components/TraceDetail";
import TraceCompare from "@/components/TraceCompare";
import EmptyState from "@/components/EmptyState";
import Tour, { TourStep, useTour } from "@/components/Tour";

function ListSkeleton() {
  return <><Skeleton w="65%" h={12} /><Skeleton w="85%" h={10} mt={5} /><SkeletonStyles /></>;
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

const PAGE = 50;

// Versioned: bumping the suffix is the one deliberate way to show the tour again to everyone
// (e.g. after the layout it points at changes). Never bump it for a copy tweak.
const TOUR_KEY = "pk_tour_traces_v1";

const WINDOWS: { label: string; hours: number }[] = [
  { label: "All time", hours: 0 }, { label: "Last hour", hours: 1 },
  { label: "Last 24h", hours: 24 }, { label: "Last 7 days", hours: 168 },
];

export default function TracesPage() {
  const [traces, setTraces] = useState<TraceSummary[]>([]);
  const [sel, setSel] = useState<string | null>(null);
  const [vs, setVs] = useState<string | null>(null);   // second trace for side-by-side compare
  const [spans, setSpans] = useState<TraceSpan[] | null>(null);
  const [origin, setOrigin] = useState("https://your-provekit-host");
  const [q, setQ] = useState("");
  const [dq, setDq] = useState("");   // debounced query sent to the server
  const [failuresOnly, setFailuresOnly] = useState(false);
  const [windowHours, setWindowHours] = useState(0);
  const [model, setModel] = useState("");
  const [sort, setSort] = useState<"recent" | "slowest" | "tokens">("recent");
  const [groupBySession, setGroupBySession] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [more, setMore] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const filters = { status: failuresOnly ? "failed" : undefined, window_hours: windowHours || undefined, q: dq || undefined };
  const filterKey = JSON.stringify(filters);

  // The 5s poll refreshes the newest page. Merge rather than replace, or every refresh would
  // throw away the older pages the user paged in.
  const load = useCallback(() => {
    api.traces({ ...JSON.parse(filterKey), limit: PAGE })
      .then((t) => {
        setTraces((prev) => {
          const oldest = t.length ? t[t.length - 1].id : Infinity;
          const fresh = new Set(t.map((x) => x.id));
          return [...t, ...prev.filter((x) => x.id < oldest && !fresh.has(x.id))];
        });
        setMore(t.length >= PAGE);
        setLoaded(true);
      }).catch(() => setLoaded(true));
  }, [filterKey]);

  const loadMore = useCallback(() => {
    const last = traces[traces.length - 1];
    if (!last || loadingMore) return;
    setLoadingMore(true);
    api.traces({ ...JSON.parse(filterKey), limit: PAGE, cursor: last.id })
      .then((t) => {
        setTraces((prev) => {
          const have = new Set(prev.map((x) => x.id));
          return [...prev, ...t.filter((x) => !have.has(x.id))];
        });
        setMore(t.length >= PAGE);
      }).catch(() => {}).finally(() => setLoadingMore(false));
  }, [traces, filterKey, loadingMore]);

  // A filter change is a different result set — drop the pages loaded under the old one.
  useEffect(() => { setTraces([]); setMore(false); }, [filterKey]);

  // Debounce the search box → server (searches span content, not just the loaded labels).
  useEffect(() => { const t = setTimeout(() => setDq(q.trim()), 300); return () => clearTimeout(t); }, [q]);

  useEffect(() => {
    setOrigin(window.location.origin);
    // Deep-link: /traces?trace=<id> opens that trace directly (e.g. from a dashboard failure).
    const deep = new URLSearchParams(window.location.search).get("trace");
    if (deep) setSel(deep);
  }, []);

  // Live updates. The server announces new traces over SSE and we refetch through the normal
  // path, so paging and merging stay in one place. The interval is a fallback, not the primary
  // channel: it's slow (30s) because SSE covers the common case, but it keeps the page live if
  // EventSource is unavailable or a proxy eats the stream.
  useEffect(() => {
    load();
    let stream: EventSource | null = null;
    try {
      stream = new EventSource(`${API_BASE}/api/traces/stream`, { withCredentials: true });
      stream.onmessage = (ev) => {
        try { if (JSON.parse(ev.data)?.type === "traces") load(); } catch { /* keepalive */ }
      };
      // Don't tear down on error: EventSource reconnects on its own, and the poll below
      // covers the gap. Closing here would turn one blip into a permanently stale page.
    } catch { /* no EventSource (very old browser) — the interval still covers it */ }
    const t = setInterval(load, 30000);
    return () => { stream?.close(); clearInterval(t); };
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
    .filter((t) => (!model || t.model === model))   // text search is server-side now (content, not just label)
    .sort((a, b) =>
      sort === "slowest" ? (b.duration_ms || 0) - (a.duration_ms || 0)
      : sort === "tokens" ? (b.tokens || 0) - (a.tokens || 0)
      : b.id - a.id);   // recent (default) — the API already returns newest-first by id

  // First visit to a *populated* portal gets the tour, once (#37). Gated on a loaded, non-empty
  // list so it can never teach an empty screen — a fresh account has no traces until its own
  // agent reports, so the tour simply waits until there is something real to point at.
  const tour = useTour(TOUR_KEY, loaded && shown.length > 0);
  // Every step after the first needs a trace open, or there is no flow graph to point at.
  // Idempotent: `before` can fire again on a re-measure.
  const openFirst = () => setSel((cur) => cur ?? shown[0]?.trace_id ?? null);
  const tourSteps: TourStep[] = [
    {
      target: '[data-tour="trace-list"]',
      title: "Every run lands here",
      body: <>One decorator on your agent and each run shows up in this list, newest first, live.
        Search hits span <em>content</em>, not just labels, and the chips narrow to failures or a
        time window.</>,
    },
    {
      target: '[data-tour="flow-canvas"]', before: openFirst,
      title: "The run, as it actually ran",
      body: <>Model calls, tools and steps nested exactly as they nested at runtime — not a flat
        log. Click any node to select it.</>,
    },
    {
      target: '[data-tour="inspector"]', before: openFirst,
      title: "What that node saw",
      body: <>Input, output, parameters, tokens and cost for the selected node. On an LLM node,
        <b> ▶ Edit &amp; re-run</b> replays it with its real data.</>,
    },
    {
      target: '[data-tour="view-toggle"]', before: openFirst,
      title: "Flow or waterfall",
      body: <>Same run, two questions. Flow answers &ldquo;what did it do?&rdquo;; waterfall
        answers &ldquo;where did the time go?&rdquo;</>,
    },
    {
      target: '[data-tour="compare"]', before: openFirst,
      title: "One that worked, one that didn't",
      body: <>Put two runs side by side to see what actually differed. That&apos;s the tour — the
        <b> Tour</b> button up top replays it any time.</>,
    },
  ];

  return (
    <ConsoleShell>
      <main style={{ maxWidth: sel ? 1600 : 1180, margin: "0 auto", padding: "24px 20px 80px", transition: "max-width .2s" }}>
        <PageHero eyebrow="Observability" title="Trace explorer"
          sub="Every run your agent makes, captured from one decorator — the whole flow of model calls, tools, and steps, nested as it actually ran."
          actions={shown.length > 0 &&
            <button className="btn-hero" onClick={tour.start} title="Replay the walkthrough">✦ Tour</button>} />


        {traces.length === 0 && !failuresOnly && !windowHours && !dq ? (
          <EmptyState origin={origin} />
        ) : sel ? (
          /* ── detail view: the selected trace's flow, full width ── */
          <div>
            <div className="tx-detail-bar">
              <button className="btn btn-sm btn-ghost" onClick={() => { setSel(null); setVs(null); }}>← All traces</button>
              {!vs && spans && (
                <select value="" data-tour="compare" className="reg-sel" style={{ marginLeft: "auto" }}
                  onChange={(e) => e.target.value && setVs(e.target.value)} title="Compare this trace against another">
                  <option value="">⇄ Compare with…</option>
                  {shown.filter((t) => t.trace_id && t.trace_id !== sel).slice(0, 30).map((t) => (
                    <option key={t.trace_id} value={t.trace_id}>{t.label} · {t.trace_id.slice(0, 8)}</option>
                  ))}
                </select>
              )}
            </div>
            <div style={{ ...panel, minHeight: 300 }}>
              {vs ? <TraceCompare aId={sel} bId={vs} onClose={() => setVs(null)} />
                : !spans ? <DetailSkeleton />
                : <TraceDetail spans={spans} traceId={sel ?? undefined} />}
            </div>
          </div>
        ) : (
          /* ── table view: the reference trace explorer ── */
          <>
            <div className="tx-filters">
              <div className="tx-search">
                <span aria-hidden>⌕</span>
                <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search by trace name or content…" />
              </div>
              <select className="tx-sel" value={failuresOnly ? "failed" : "all"}
                onChange={(e) => setFailuresOnly(e.target.value === "failed")}>
                <option value="all">All</option>
                <option value="failed">Failures</option>
              </select>
              {modelOptions.length > 1 && (
                <select className="tx-sel" value={model} onChange={(e) => setModel(e.target.value)}>
                  <option value="">Model: All</option>
                  {modelOptions.map((m) => <option key={m} value={m}>{m}</option>)}
                </select>
              )}
              <select className="tx-sel" value={windowHours} onChange={(e) => setWindowHours(Number(e.target.value))}>
                {WINDOWS.map((w) => <option key={w.hours} value={w.hours}>{w.label}</option>)}
              </select>
              <select className="tx-sel" value={sort} onChange={(e) => setSort(e.target.value as any)}>
                <option value="recent">↓ Recent</option>
                <option value="slowest">↓ Slowest</option>
                <option value="tokens">↓ Most tokens</option>
              </select>
              {hasSessions && (
                <button className={`tx-sel ${groupBySession ? "on" : ""}`} onClick={() => setGroupBySession((v) => !v)}
                  title="Group multi-turn runs by session">◆ Sessions</button>
              )}
              <span className="tx-count">{shown.length}{more ? "+" : ""} trace{shown.length === 1 ? "" : "s"}</span>
            </div>

            <div data-tour="trace-list" style={{ ...panel, padding: 0, overflowX: "auto" }}>
              {!loaded ? (
                <div style={{ padding: 16 }}>{Array.from({ length: 6 }).map((_, i) => <div key={i} style={{ padding: "10px 2px" }}><ListSkeleton /></div>)}</div>
              ) : shown.length === 0 ? (
                <div className="muted" style={{ padding: 20, fontSize: 13, textAlign: "center" }}>No traces match.</div>
              ) : (
                <table className="tx-table">
                  <thead>
                    <tr><th>Trace</th><th>Type</th><th>Status</th><th>Duration</th><th>Tokens</th><th>Cost</th><th>Created</th></tr>
                  </thead>
                  <tbody>
                    {(groupBySession ? sessionGroups(shown) : [{ key: "_", session: "", items: shown, tokens: 0 }]).map((g) => (
                      <React.Fragment key={g.key}>
                        {groupBySession && (
                          <tr className="tx-group"><td colSpan={7}>
                            {g.session ? `◆ ${g.session}` : "No session"} · {g.items.length} turn{g.items.length === 1 ? "" : "s"}
                          </td></tr>
                        )}
                        {g.items.map((t) => (
                          <tr key={t.trace_id || t.id} className="tx-row" onClick={() => { setSel(t.trace_id); setVs(null); }} title={fmt(t.created_at)}>
                            <td className="tx-name">
                              <b>{t.label || `run ${t.id}`}</b>
                              <span className="tx-id">{t.trace_id ? t.trace_id.slice(0, 10) : `#${t.id}`}</span>
                            </td>
                            <td><span className={`tx-type ${t.type}`}>{t.type}</span></td>
                            <td><TxStatus t={t} /></td>
                            <td className="tx-num">{fmtDur(t.duration_ms)}</td>
                            <td className="tx-num">{t.tokens ? t.tokens.toLocaleString() : "—"}</td>
                            <td className="tx-num">{t.cost != null ? fmtCost(t.cost) : "—"}</td>
                            <td className="tx-when">{relTime(t.created_at)}</td>
                          </tr>
                        ))}
                      </React.Fragment>
                    ))}
                  </tbody>
                </table>
              )}
              {more && (
                <div className="tx-foot">
                  <span className="muted">{shown.length} loaded</span>
                  <button className="btn btn-sm" onClick={loadMore} disabled={loadingMore}>
                    {loadingMore ? "Loading…" : `Load ${PAGE} more`}
                  </button>
                </div>
              )}
            </div>
          </>
        )}
      </main>
      <Tour steps={tourSteps} open={tour.open} onClose={tour.close} />
    </ConsoleShell>
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

function fmtDur(ms: number): string {
  return ms >= 1000 ? `${(ms / 1000).toFixed(2)}s` : `${ms}ms`;
}

// ● Success / ● Error / ⚠ partial — the reference's status pill.
function TxStatus({ t }: { t: TraceSummary }) {
  if (t.incomplete) return <span className="tx-status partial" title="Ended before it could report finishing">⚠ Partial</span>;
  if (t.status === "failed") return <span className="tx-status err">● Error</span>;
  return <span className="tx-status ok">● Success</span>;
}

const panel: React.CSSProperties = {
  background: "var(--panel)", border: "1px solid var(--border)", borderRadius: 12, padding: 16,
};
