"use client";

// Custom span renderers (#99) — a plugin hook so a team can render *their* domain span
// natively instead of reading a JSON blob out of a <pre>.
//
// WHY THE KEY IS THE LABEL'S LEADING SEGMENT
// ------------------------------------------
// Three candidates existed, and only one is both team-controlled and actually present on a
// stored span today:
//
//   • `span.type` — assigned by ProveKit's classifier (services/otel.py), not by the team.
//     It has four values (agent | llm | tool | step) and every retrieval in the world lands
//     in the same bucket as every other tool call. Far too coarse to key a renderer on.
//   • a custom meta field (`result.meta.pk_renderer`) — the nicest contract, and the one to
//     move to if ingest ever grows an attribute passthrough. It does not work today:
//     `map_span()` builds `result.meta` from a fixed whitelist (provider, model, usage,
//     params, finish_reason, events, tool, session_id, truncation, start_ns, price_version),
//     so an arbitrary `pk.renderer` attribute is dropped at ingest and a registry keyed on it
//     would never fire once. That is the price of shipping this without touching the ingest
//     mapper or the schema.
//   • the span label — what's left, and it turns out to be the right answer anyway: it is
//     literally the string the team passed to `pk.span("retrieval.query")` (or the OTel span
//     name), it survives ingest verbatim (truncated at 200 chars), and namespacing it
//     (`yourteam.thing`) keeps two teams' renderers from colliding.
//
// So: key = the label's leading segment, up to the first `.`/`:`/`/`/space, lowercased.
// `retrieval.query` → "retrieval"; a bare `retrieve` → "retrieve".
//
// A redacted share link can withhold `label` (services/share.py). Then there is no key, and
// the span falls back to the default view — which is correct: a reader who wasn't shown the
// label shouldn't be handed a domain view inferred from it.
//
// FALLBACK IS TOTAL
// -----------------
// A debugging tool that dies on the span you are debugging is worse than a plain one, so
// every path out of a custom renderer ends at the default view:
//   • no renderer registered for the key            → default
//   • `match()` throws                              → default (renderer disabled)
//   • `render()` throws                             → default + a one-line note
//   • `render()` returns null (payload not ours)    → default, silently
//   • a component *inside* the returned tree throws → default + a note (error boundary)
// A renderer that has thrown is marked failed for the rest of the session so it can't blow up
// on every row of a 400-span trace.

import React, { useSyncExternalStore } from "react";
import { TraceSpan } from "@/lib/api";

export interface SpanRendererProps {
  /** The span being inspected. Treat it as read-only. */
  span: TraceSpan;
}

export interface SpanRenderer {
  /** Label namespace this claims, lowercase (`"retrieval"` matches `retrieval.query`). */
  key: string;
  /** Shown in the "rendered by" strip above the custom view. */
  title: string;
  /** Optional extra narrowing once the key matched. Throwing disables the renderer. */
  match?: (span: TraceSpan) => boolean;
  /**
   * Return the custom view, or `null` to decline this span (the default view is used, with no
   * visible sign anything was tried). Called during render, so it must be pure — if you need
   * hooks or state, return `<YourComponent span={span} />` and put them in there, where the
   * error boundary can still catch a throw.
   */
  render: (props: SpanRendererProps) => React.ReactNode;
}

// ---------------------------------------------------------------- registry

const registry = new Map<string, SpanRenderer>();
const failed = new Set<string>();

// Tiny store so a renderer registered from a `useEffect` after mount actually appears without
// a reload — otherwise `registerSpanRenderer` would only work at module scope.
let version = 0;
const listeners = new Set<() => void>();
function bump() { version++; listeners.forEach((l) => l()); }
function subscribe(l: () => void) { listeners.add(l); return () => { listeners.delete(l); }; }

/** Register (or replace) the renderer for a label namespace. Returns an unregister function. */
export function registerSpanRenderer(r: SpanRenderer): () => void {
  const key = r.key.trim().toLowerCase();
  registry.set(key, { ...r, key });
  failed.delete(key);
  bump();
  return () => unregisterSpanRenderer(key);
}

export function unregisterSpanRenderer(key: string): void {
  if (registry.delete(key.trim().toLowerCase())) bump();
}

/** Every registered renderer, for debugging and for the docs page. */
export function listSpanRenderers(): SpanRenderer[] {
  return Array.from(registry.values());
}

/** The registry key for a span: the label's leading segment, lowercased. */
export function spanRendererKey(span: TraceSpan): string | null {
  const label = (span?.label || "").trim();
  if (!label) return null;
  const seg = label.split(/[.:/\s]/)[0];
  return seg ? seg.toLowerCase().slice(0, 64) : null;
}

/** The renderer that claims this span, or null. Never throws. */
export function resolveSpanRenderer(span: TraceSpan): SpanRenderer | null {
  try {
    const key = spanRendererKey(span);
    if (!key || failed.has(key)) return null;
    const r = registry.get(key);
    if (!r) return null;
    if (r.match && !r.match(span)) return null;
    return r;
  } catch (err) {
    // A throwing `match` is a broken renderer, not a broken trace.
    const key = (() => { try { return spanRendererKey(span); } catch { return null; } })();
    if (key) markRendererFailed(key, err);
    return null;
  }
}

function markRendererFailed(key: string, err: unknown): void {
  if (!failed.has(key)) {
    failed.add(key);
    // eslint-disable-next-line no-console
    console.error(`[provekit] custom span renderer "${key}" failed; falling back to the default view`, err);
  }
}

// ---------------------------------------------------------------- rendering

class RendererBoundary extends React.Component<
  { rendererKey: string; fallback: React.ReactNode; children: React.ReactNode },
  { crashed: boolean }
> {
  state = { crashed: false };
  static getDerivedStateFromError() { return { crashed: true }; }
  componentDidCatch(err: unknown) { markRendererFailed(this.props.rendererKey, err); }
  render() {
    if (!this.state.crashed) return this.props.children;
    return <><FailNote /> {this.props.fallback}</>;
  }
}

function FailNote() {
  return (
    <div className="muted" style={{ fontSize: 11.5, marginBottom: 8, display: "flex", gap: 6, alignItems: "flex-start", lineHeight: 1.5 }}>
      <span style={{ color: "var(--amber)", flexShrink: 0 }}>⚠</span>
      <span>This span&apos;s custom renderer threw. Showing the default view — nothing about the span itself is wrong.</span>
    </div>
  );
}

/**
 * The output section of a span: a custom renderer if one claims it, otherwise `fallback`.
 * The caller owns the default view, so this file never has to duplicate it.
 */
export function SpanBody({ span, fallback }: { span: TraceSpan; fallback: React.ReactNode }) {
  useSyncExternalStore(subscribe, () => version, () => version);   // re-resolve on (un)register
  const [showDefault, setShowDefault] = React.useState(false);

  const r = resolveSpanRenderer(span);
  if (!r) return <>{fallback}</>;

  let content: React.ReactNode = null;
  try {
    content = r.render({ span });
  } catch (err) {
    markRendererFailed(r.key, err);
    return <><FailNote /> {fallback}</>;
  }
  // Declined: this renderer owns the namespace but not this payload. Say nothing.
  if (content == null || content === false) return <>{fallback}</>;

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, marginBottom: 6 }}>
        <span className="muted" style={{ fontSize: 10.5, textTransform: "uppercase", letterSpacing: 0.4 }}>
          {r.title}
        </span>
        <button onClick={() => setShowDefault((v) => !v)}
          title="The captured payload, exactly as stored"
          style={{ background: "none", border: "none", color: "var(--accent)", fontSize: 11, cursor: "pointer", padding: 0 }}>
          {showDefault ? "Hide raw" : "Show raw"}
        </button>
      </div>
      {/* Keyed per span so a crash on one node doesn't leave the boundary latched for the next. */}
      <RendererBoundary key={`${r.key}:${span.span_id}`} rendererKey={r.key} fallback={fallback}>
        {content}
      </RendererBoundary>
      {showDefault && <div style={{ marginTop: 10, paddingTop: 10, borderTop: "1px solid var(--border)" }}>{fallback}</div>}
    </div>
  );
}

// ---------------------------------------------------------------- worked example

interface Doc { id?: string; score?: number; text: string; source?: string }

/**
 * Pull a document list out of a retrieval span's captured output. Returns null for anything
 * that isn't document-shaped — which is how the renderer declines a span it can't improve on.
 */
export function parseDocuments(v: unknown): Doc[] | null {
  let data: any = v;
  if (typeof v === "string") {
    const t = v.trim();
    if (!t.startsWith("[") && !t.startsWith("{")) return null;
    try { data = JSON.parse(t); } catch { return null; }
  }
  if (!data) return null;
  const arr = Array.isArray(data) ? data
    : Array.isArray(data.documents) ? data.documents
    : Array.isArray(data.results) ? data.results
    : Array.isArray(data.chunks) ? data.chunks : null;
  if (!arr) return null;
  const docs = arr.map((d: any): Doc | null => {
    if (typeof d === "string") return { text: d };
    if (!d || typeof d !== "object") return null;
    const text = d.text ?? d.content ?? d.page_content ?? d.chunk;
    if (typeof text !== "string") return null;
    const score = typeof d.score === "number" ? d.score
      : typeof d.distance === "number" ? d.distance : undefined;
    return { text, score, id: d.id != null ? String(d.id) : undefined, source: d.source ?? d.metadata?.source };
  }).filter(Boolean) as Doc[];
  return docs.length ? docs : null;
}

function RetrievalView({ span }: SpanRendererProps) {
  const docs = parseDocuments(span.result?.text ?? span.result?.output);
  if (!docs) return null;   // unreachable via the registry (match() already checked), but cheap
  const top = Math.max(...docs.map((d) => d.score ?? 0), 1);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <div className="muted" style={{ fontSize: 11.5 }}>
        {docs.length} document{docs.length === 1 ? "" : "s"} retrieved
        {span.request?.input ? <> for <span className="mono">{String(span.request.input).slice(0, 80)}</span></> : null}
      </div>
      {docs.map((d, i) => (
        <div key={i} style={{ border: "1px solid var(--border)", borderRadius: 8, overflow: "hidden" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "4px 8px", background: "var(--bg-2)", fontSize: 11 }}>
            <span className="mono" style={{ color: "var(--muted)" }}>#{i + 1}</span>
            <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {d.source || d.id || "document"}
            </span>
            {d.score != null && (
              <>
                {/* Relative bar: retrieval scores are only comparable within one query. */}
                <span style={{ width: 44, height: 5, borderRadius: 3, background: "var(--panel-2)", flexShrink: 0 }}>
                  <span style={{ display: "block", height: 5, borderRadius: 3, background: "var(--blue)",
                    width: `${Math.max(4, Math.min(100, ((d.score ?? 0) / top) * 100))}%` }} />
                </span>
                <span className="mono" style={{ color: "var(--muted)", width: 42, textAlign: "right" }}>{d.score.toFixed(3)}</span>
              </>
            )}
          </div>
          <pre style={{ margin: 0, padding: 8, fontSize: 12, lineHeight: 1.5, fontFamily: "var(--font-mono)",
            whiteSpace: "pre-wrap", wordBreak: "break-word", maxHeight: 140, overflowY: "auto" }}>{d.text}</pre>
        </div>
      ))}
    </div>
  );
}

/**
 * The worked example, registered by default: any span whose label starts with `retrieval`
 * (`retrieval.query`, `retrieval:kb`, …) whose output is a document list renders as a ranked
 * result list instead of a JSON blob. Drop it with
 * `unregisterSpanRenderer("retrieval")` if you'd rather see the raw payload.
 */
export const retrievalRenderer: SpanRenderer = {
  key: "retrieval",
  title: "Retrieval",
  match: (s) => parseDocuments(s.result?.text ?? s.result?.output) != null,
  render: (p) => <RetrievalView {...p} />,
};

registerSpanRenderer(retrievalRenderer);
