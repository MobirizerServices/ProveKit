"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api, API_BASE, getProjectId, TraceSpan, TraceSummary } from "@/lib/api";
import { Skeleton, SkeletonStyles } from "@/components/Skeleton";
import ConsoleShell from "@/components/ConsoleShell";
import TraceDetail from "@/components/TraceDetail";
import TraceCompare from "@/components/TraceCompare";
import EmptyState, { SAMPLE_PROJECT_NAME, sampleBadge } from "@/components/EmptyState";
import Tour, { TourStep, useTour } from "@/components/Tour";

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
        {t.incomplete
          ? <span style={partialBadge} title="No root span arrived — the run ended before it could report finishing (crash, OOM, or timeout). What was captured before it stopped is shown below.">partial</span>
          : t.status === "failed"
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
  const [listOpen, setListOpen] = useState(true);
  // True while the selected project is the preloaded sample. Fabricated traces shown without
  // saying so would break the one promise a tracing tool has to keep, so this banner rides
  // above the list for as long as the sample project is open.
  const [inSample, setInSample] = useState(false);

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
    api.projects().then((ps) => {
      const pid = getProjectId();
      const cur = ps.find((p) => String(p.id) === pid) ?? ps.find((p) => p.is_default);
      setInSample(cur?.name === SAMPLE_PROJECT_NAME);
    }).catch(() => {});
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
  // list so it can never teach an empty screen — and on a fresh account the seeded
  // "Sample data (demo)" project means there is something real to teach against on visit one.
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
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
          <h1 style={{ fontSize: 22, margin: "0 0 4px" }}>Traces</h1>
          {/* The tour is one-shot, so dismissing it has to be safe: this is the way back in. */}
          {shown.length > 0 && (
            <button className="btn btn-sm btn-ghost" onClick={tour.start} title="Replay the walkthrough">
              ✦ Tour
            </button>
          )}
        </div>
        <p className="muted" style={{ margin: "0 0 20px", fontSize: 13.5 }}>
          Every run your agent makes, captured from one decorator — the whole flow of model
          calls, tools, and steps, nested as it actually ran.
        </p>

        {inSample && (
          <div style={sampleBanner}>
            <span style={sampleBadge}>sample</span>
            <span>
              These traces are fabricated demo data in <b>{SAMPLE_PROJECT_NAME}</b> — no agent
              of yours produced them. Switch projects in the top bar for your real traces, or
              delete this project in <Link href="/settings" style={{ color: "var(--accent)" }}>Settings</Link> when
              you&apos;re done.
            </span>
          </div>
        )}

        {traces.length === 0 && !failuresOnly && !windowHours ? (
          <EmptyState origin={origin} />
        ) : (
          <div className="traces-grid" style={{ display: "grid", gridTemplateColumns: listOpen ? "300px 1fr" : "0 1fr", gap: listOpen ? 16 : 0, transition: "grid-template-columns .2s, gap .2s", position: "relative" }}>
            {/* collapse the trace list to give the flow studio the whole width */}
            {sel && (
              <button onClick={() => setListOpen((o) => !o)} title={listOpen ? "Hide list" : "Show list"}
                style={{ position: "absolute", top: 6, left: listOpen ? 300 : -4, zIndex: 6, width: 22, height: 22, borderRadius: 6, border: "1px solid var(--border-strong)", background: "var(--panel)", color: "var(--muted)", cursor: "pointer", fontSize: 14, lineHeight: 1, display: "grid", placeItems: "center" }}>
                {listOpen ? "‹" : "›"}
              </button>
            )}
            <div data-tour="trace-list" style={{ display: listOpen ? "flex" : "none", flexDirection: "column", gap: 8, maxHeight: "76vh" }}>
              <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search label or content…"
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
                      <TraceRow key={t.trace_id || t.id} t={t} active={sel === t.trace_id} onClick={() => { setSel(t.trace_id); setVs(null); }} fmt={fmt} indent />
                    ))}
                  </div>
                ))
              ) : shown.map((t) => (
                <TraceRow key={t.trace_id || t.id} t={t} active={sel === t.trace_id} onClick={() => { setSel(t.trace_id); setVs(null); }} fmt={fmt} />
              ))}
              {/* Client-side filters (model, sort) narrow what's loaded, so keep paging offered
                  whenever the server has more — otherwise a model filter can look empty when
                  the matching traces are simply on a later page. */}
              {more && (
                <button className="btn btn-sm" onClick={loadMore} disabled={loadingMore}
                  style={{ width: "100%", marginTop: 8 }}>
                  {loadingMore ? "Loading…" : `Load ${PAGE} more`}
                </button>
              )}
              </div>
            </div>

            <div style={{ ...panel, minHeight: 220 }}>
              {!sel ? (
                <div className="muted" style={{ fontSize: 13 }}>Select a trace to see its flow.</div>
              ) : vs ? (
                <TraceCompare aId={sel} bId={vs} onClose={() => setVs(null)} />
              ) : !spans ? (
                <DetailSkeleton />
              ) : (
                <>
                  <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 8 }}>
                    <select value="" data-tour="compare" onChange={(e) => e.target.value && setVs(e.target.value)}
                      title="Compare this trace against another"
                      style={{ background: "var(--panel-2)", color: "var(--muted)", border: "1px solid var(--border-strong)", borderRadius: 8, padding: "5px 9px", fontSize: 12 }}>
                      <option value="">⇄ Compare with…</option>
                      {shown.filter((t) => t.trace_id && t.trace_id !== sel).slice(0, 30).map((t) => (
                        <option key={t.trace_id} value={t.trace_id}>{t.label} · {t.trace_id.slice(0, 8)} · {fmt(t.created_at).replace(/:\d\d /, " ")}</option>
                      ))}
                    </select>
                  </div>
                  <TraceDetail spans={spans} traceId={sel ?? undefined} />
                </>
              )}
            </div>
          </div>
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

const sampleBanner: React.CSSProperties = {
  display: "flex", alignItems: "center", gap: 10, marginBottom: 16, padding: "10px 14px",
  borderRadius: 10, fontSize: 12.5, lineHeight: 1.6, color: "var(--text-dim)",
  background: "var(--panel)", border: "1px solid var(--purple)",
};

const panel: React.CSSProperties = {
  background: "var(--panel)", border: "1px solid var(--border)", borderRadius: 12, padding: 16,
};
const dot: React.CSSProperties = { width: 8, height: 8, borderRadius: 999, flexShrink: 0, marginTop: 4 };
// Distinct from `failed`: the run didn't report an error, it stopped reporting at all.
const partialBadge: React.CSSProperties = {
  fontSize: 10, fontWeight: 700, letterSpacing: 0.3, textTransform: "uppercase",
  color: "var(--amber)", border: "1px solid var(--amber)", borderRadius: 999,
  padding: "1px 6px", flexShrink: 0,
};
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
