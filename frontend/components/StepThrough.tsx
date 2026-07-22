"use client";

// Step-through / time-travel (#56) — walk a captured trace one span at a time.
//
// WHAT THIS IS, AND WHAT IT DELIBERATELY IS NOT
// --------------------------------------------
// This is a REPLAY of what was recorded, not a live debugger. ProveKit holds a finished trace;
// nothing is paused, nothing is suspended, no process is waiting on you. "Stepping" means
// walking the spans in the order they actually started and showing the state that was captured
// at each one. A debugger that claims to pause a running agent and doesn't is worse than no
// debugger at all, so the header says "replay" and never "paused".
//
// "State" therefore means the span's captured input / output / error plus what ProveKit can
// derive from the trace (elapsed time, tokens and cost so far, what changed against the
// previous step). It is not a stack frame — local variables were never captured, and this view
// will not pretend otherwise.
//
// ORDERING IS FROM CAPTURED START TIME, NOT ARRAY POSITION
// -------------------------------------------------------
// Spans arrive out of order in this codebase: children finish (and export) before their parent,
// and `GET /api/traces/{id}` returns rows in arrival order (`Run.id.asc()`), which is not
// execution order. Stepping through arrival order would show you the trace in the order the
// exporter's batches happened to flush. So the order here comes from `result.meta.start_ns`
// (epoch nanoseconds, stored as a *string* because it overflows a JS number — compared as
// BigInt), with tree order as the tiebreak and the fallback.
//
// It also has to survive a trace whose root never arrived (#3/#4) — a run that died before it
// could report finishing is exactly the trace someone steps through. Any span whose parent is
// missing is treated as a root, and any span the tree walk cannot reach at all (a parent cycle)
// is appended rather than dropped: silently omitting the span you opened this for is the one
// failure mode that makes the tool useless.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { TraceSpan } from "@/lib/api";
import { estimateCost, fmtCost } from "@/lib/cost";
import { useVirtualRows } from "@/lib/useVirtualRows";

const TYPE_COLOR: Record<string, string> = {
  agent: "var(--accent)", llm: "var(--blue)", tool: "var(--purple)", step: "var(--muted)",
};

export interface Step {
  span: TraceSpan;
  /** Tree depth — used only to indent the rail. It is *not* what orders the steps. */
  depth: number;
  /** ms from the trace's first captured start, or null when this span carried no timestamp. */
  offsetMs: number | null;
}

export interface ExecutionOrder {
  steps: Step[];
  /** How many spans carried a real `start_ns`. Below `steps.length`, order is partly inferred. */
  timed: number;
}

function startNs(s: TraceSpan): bigint | null {
  const v = s.result?.meta?.start_ns;
  if (v == null || v === "") return null;
  // A malformed value is a bad span, not a reason to blank the whole debugger.
  try { return BigInt(v); } catch { return null; }
}

/**
 * The spans of one trace in execution order: sorted by captured start time, ties broken by tree
 * order (a parent before its children). Exported so the ordering rule is testable and greppable
 * on its own, rather than buried in a render.
 */
export function executionOrder(spans: TraceSpan[]): ExecutionOrder {
  const ids = new Set(spans.map((s) => s.span_id));
  const kids: Record<string, TraceSpan[]> = {};
  for (const s of spans) {
    // A span parented to something not in this trace — or to itself — is a root here. That is
    // the rootless-trace case (#3/#4): the run died before the root span was exported.
    const p = s.parent_span_id && s.parent_span_id !== s.span_id && ids.has(s.parent_span_id)
      ? s.parent_span_id : "__root__";
    (kids[p] ||= []).push(s);
  }

  // Iterative depth-first walk (a deep tool chain shouldn't be able to blow the call stack).
  // Visited-tracking is by ROW, not by span_id. Two spans can legitimately share an id here:
  // ingest only dedupes when span_id is non-empty (routers/traces.py) and the unique index is
  // partial (`span_id != ''`), so a batch with missing spanIds lands several rows carrying "".
  // Keying `seen` on the id dropped every one of them after the first — and the waterfall
  // renders them, so the debugger showed fewer spans than the view beside it, with the missing
  // spans' tokens and cost silently absent from the running totals.
  const seen = new Set<TraceSpan>();
  const expanded = new Set<string>();
  const dfs: { span: TraceSpan; depth: number }[] = [];
  const stack: { span: TraceSpan; depth: number }[] = [];
  for (let i = (kids["__root__"] || []).length - 1; i >= 0; i--) {
    stack.push({ span: kids["__root__"][i], depth: 0 });
  }
  while (stack.length) {
    const n = stack.pop()!;
    if (seen.has(n.span)) continue;
    seen.add(n.span);
    dfs.push(n);
    // Guard the *expansion* by id so a parent cycle still terminates, while rows sharing an id
    // are each emitted exactly once.
    if (n.span.span_id && !expanded.has(n.span.span_id)) {
      expanded.add(n.span.span_id);
      const cs = kids[n.span.span_id] || [];
      for (let i = cs.length - 1; i >= 0; i--) stack.push({ span: cs[i], depth: n.depth + 1 });
    }
  }
  // Anything the walk couldn't reach (a parent cycle, an orphan) goes on the end. Never dropped
  // — silently omitting the span you opened the debugger for is the one failure that makes the
  // tool useless.
  for (const s of spans) if (!seen.has(s)) { seen.add(s); dfs.push({ span: s, depth: 0 }); }

  const starts = spans.map(startNs).filter((x): x is bigint => x !== null);
  const t0 = starts.length ? starts.reduce((a, b) => (b < a ? b : a)) : 0n;

  // Sort key per row. A span with no timestamp inherits the last real start seen before it in
  // tree order, so it stays where the tree put it — right after the span it ran under — instead
  // of every untimed span piling up at position zero.
  let last = t0;
  const keys = dfs.map((n) => {
    const st = startNs(n.span);
    if (st !== null) last = st;
    return st ?? last;
  });
  const order = dfs.map((_, i) => i);
  // The `a - b` tiebreak makes tree order the explicit fallback rather than relying on the
  // engine's sort being stable.
  order.sort((a, b) => (keys[a] < keys[b] ? -1 : keys[a] > keys[b] ? 1 : a - b));

  const steps = order.map((i) => {
    const st = startNs(dfs[i].span);
    return { span: dfs[i].span, depth: dfs[i].depth, offsetMs: st === null ? null : Number(st - t0) / 1e6 };
  });
  return { steps, timed: starts.length };
}

// ---------------------------------------------------------------- what changed

export interface Change { field: string; from: string; to: string }

function textOf(v: any): string {
  if (v == null) return "";
  return typeof v === "string" ? v : JSON.stringify(v);
}

function clip(s: string, n = 64): string {
  const one = s.replace(/\s+/g, " ").trim();
  return one.length > n ? one.slice(0, n) + "…" : one;
}

// The captured facts about a span that are worth diffing against the previous one. Deliberately
// excludes input/output: those differ at every step by definition, so listing them as "changed"
// would bury the fields that only change when something interesting happened.
function factsOf(s: TraceSpan): Record<string, string> {
  const meta: any = s.result?.meta || {};
  const f: Record<string, string> = { type: s.type, status: s.status };
  if (s.request?.provider) f.provider = s.request.provider;
  if (s.request?.model) f.model = s.request.model;
  if (s.request?.operation) f.operation = s.request.operation;
  if (meta.tool) f.tool = String(meta.tool);
  if (meta.finish_reason != null) f["finish reason"] = String(meta.finish_reason);
  // A forked branch changes replay_state mid-trace (services/replay.py) — the step where a
  // reproduction turns into a hypothesis is exactly the step you want flagged.
  if (meta.replay_state) f["replay state"] = String(meta.replay_state);
  if (s.session_id) f.session = s.session_id;
  const e = (s.error || "").trim();
  if (e) f.error = clip(e, 80);
  return f;
}

export function changesBetween(prev: TraceSpan, cur: TraceSpan): Change[] {
  const a = factsOf(prev), b = factsOf(cur);
  const out: Change[] = [];
  for (const k of Array.from(new Set([...Object.keys(a), ...Object.keys(b)]))) {
    if (a[k] !== b[k]) out.push({ field: k, from: a[k] ?? "—", to: b[k] ?? "—" });
  }
  return out;
}

/**
 * Whether this step's captured input contains the previous step's captured output verbatim.
 *
 * This is the same substring test `services/replay.py` threads a re-run's new output forward
 * with, and it is a *heuristic*: a step that summarises or reformats the previous output shows
 * no carry-over even though it consumed it, and two steps can share a string by coincidence. It
 * is labelled as a heuristic in the UI rather than stated as data flow.
 */
export function carriesForward(prev: TraceSpan, cur: TraceSpan): boolean {
  const out = textOf(prev.result?.text ?? prev.result?.output).trim();
  if (out.length < 12) return false;   // short strings collide by accident
  const input = textOf(cur.request?.input);
  return input.length > 0 && input.includes(out);
}

// ---------------------------------------------------------------- deep links

/** The hash that points at one step: `#step-<span id>`. */
export function stepHash(spanId: string): string {
  return `#step-${encodeURIComponent(spanId)}`;
}

/** The span id in `#step-…`, or null. Exported so TraceDetail reads it the same way. */
export function readStepHash(hash: string): string | null {
  const m = /^#step-(.+)$/.exec(hash || "");
  return m ? decodeURIComponent(m[1]) : null;
}

// ---------------------------------------------------------------- component

const ROW_H = 34;
const VIRTUALIZE_FROM = 120;   // same threshold as the waterfall: below it, just render the list

const railId = (n: number) => `pk-step-${n}`;

function fmtDur(ms: number): string {
  if (ms >= 1000) return `${(ms / 1000).toFixed(ms >= 10000 ? 0 : 1)}s`;
  return `${Math.round(ms)}ms`;
}

export default function StepThrough({
  spans, startAt, onStep, onClose, renderBody,
}: {
  spans: TraceSpan[];
  /** Span id to open on — from a `#step-…` deep link. */
  startAt?: string | null;
  /** Fires on every step so the host can keep its own selection in sync. */
  onStep?: (spanId: string) => void;
  /** Receives the span the reader stopped on, so the host can leave a `#span-…` link behind. */
  onClose: (spanId: string | null) => void;
  /** The span's input/output/error view. Passed in so this module doesn't import TraceDetail. */
  renderBody: (span: TraceSpan) => React.ReactNode;
}) {
  const { steps, timed } = useMemo(() => executionOrder(spans), [spans]);
  const [i, setI] = useState(0);
  const panelRef = useRef<HTMLDivElement | null>(null);
  // Clamped rather than trusted: `spans` can be replaced under this panel (a refetch, a switch
  // to a shorter trace) and a cursor past the end would render an empty debugger.
  const idx = steps.length ? Math.min(i, steps.length - 1) : -1;
  // Lets the key handler read the live cursor without re-binding a window listener per step.
  const iRef = useRef(0);
  iRef.current = idx;

  // Open on the deep-linked step. Only when it resolves — a stale link shouldn't silently drop
  // you at step 1 of a trace you didn't ask about, it should just do nothing.
  useEffect(() => {
    if (!startAt) return;
    const at = steps.findIndex((s) => s.span.span_id === startAt);
    if (at >= 0) setI(at);
  }, [startAt, steps]);

  const cur = idx >= 0 ? steps[idx] : undefined;
  const prev = idx > 0 ? steps[idx - 1] : null;

  const go = useCallback((to: number) => {
    const n = Math.max(0, Math.min(to, steps.length - 1));
    const id = steps[n]?.span.span_id;
    if (n === iRef.current || !id) return;
    setI(n);
    onStep?.(id);
    // replaceState, not push: stepping shouldn't bury the back button under 400 entries.
    try { window.history.replaceState(null, "", stepHash(id)); } catch { /* no history */ }
  }, [steps, onStep]);

  // Keyboard driver. Bound to the window because the panel is a full-screen overlay, but it
  // steps aside for anything the reader might be typing into (a note, the share form).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      const tag = (t?.tagName || "").toLowerCase();
      if (tag === "input" || tag === "textarea" || tag === "select" || t?.isContentEditable) return;
      switch (e.key) {
        case "ArrowRight": case "ArrowDown": case "n": case "j": case " ":
          e.preventDefault(); go(iRef.current + 1); return;
        case "ArrowLeft": case "ArrowUp": case "p": case "k":
          e.preventDefault(); go(iRef.current - 1); return;
        case "Home": e.preventDefault(); go(0); return;
        case "End": e.preventDefault(); go(steps.length - 1); return;
        case "Escape": e.preventDefault(); onClose(steps[iRef.current]?.span.span_id ?? null); return;
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [go, steps, onClose]);

  useEffect(() => { panelRef.current?.focus(); }, []);

  // Running totals — the part of "state" a trace can actually answer: what this run had spent
  // by the time it reached this step.
  const totals = useMemo(() => {
    const out: { tok: number; usd: number }[] = [];
    let tok = 0, usd = 0;
    for (const s of steps) {
      const u = s.span.result?.meta?.usage;
      tok += (u?.input_tokens || 0) + (u?.output_tokens || 0);
      usd += estimateCost(s.span.request?.model, u?.input_tokens, u?.output_tokens) || 0;
      out.push({ tok, usd });
    }
    return out;
  }, [steps]);

  const virtual = steps.length >= VIRTUALIZE_FROM;
  const v = useVirtualRows(steps.length, { estimate: ROW_H, overscan: 8, enabled: virtual });
  const { scrollToIndex } = v;
  // Keep the active step visible in the rail. scrollToIndex mounts it when the list is
  // windowed (it may be 400 rows away); the row itself then does the fine alignment, which is
  // also the only thing that happens when the list is short enough not to be windowed.
  useEffect(() => {
    if (idx < 0) return;
    scrollToIndex(idx, "center");
    const align = () => document.getElementById(railId(idx))?.scrollIntoView({ block: "nearest" });
    if (typeof requestAnimationFrame === "function") requestAnimationFrame(align); else align();
  }, [idx, scrollToIndex]);

  if (!cur) {
    return (
      <div style={overlay} role="dialog" aria-modal="true" aria-label="Step through">
        <div style={{ padding: 20, fontSize: 13 }}>
          <span className="muted">This trace has no spans to step through.</span>{" "}
          <button className="btn btn-sm" onClick={() => onClose(null)}>Close</button>
        </div>
      </div>
    );
  }

  const changes = prev ? changesBetween(prev.span, cur.span) : [];
  const carried = prev ? carriesForward(prev.span, cur.span) : false;
  // Negative gap = this step started before the previous one finished, i.e. they overlapped.
  // Worth naming: a reader stepping a linear list will otherwise read concurrency as sequence.
  const gapMs = prev && prev.offsetMs != null && cur.offsetMs != null
    ? cur.offsetMs - (prev.offsetMs + (prev.span.duration_ms || 0)) : null;
  const meta: any = cur.span.result?.meta || {};

  const railRow = (s: Step, n: number) => {
    const active = n === idx;
    const failed = s.span.status === "failed";
    return (
      <div key={`${s.span.span_id}-${n}`} role="none" ref={virtual ? v.rowRef(n) : undefined}>
        <button id={railId(n)} onClick={() => go(n)} style={railBtn(active)} aria-current={active ? "step" : undefined}>
          <span className="mono" style={{ fontSize: 10.5, color: "var(--muted)", width: 30, flexShrink: 0, textAlign: "right" }}>
            {n + 1}
          </span>
          <span style={{ paddingLeft: Math.min(s.depth, 6) * 9, display: "inline-flex", alignItems: "center", gap: 6, minWidth: 0 }}>
            <span style={dot(failed ? "var(--red)" : TYPE_COLOR[s.span.type] || "var(--muted)")} />
            <span style={{ fontSize: 12, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {s.span.label || s.span.type}
            </span>
          </span>
          <span className="mono" style={{ marginLeft: "auto", fontSize: 10.5, color: "var(--muted)", flexShrink: 0 }}>
            {s.offsetMs == null ? "—" : `+${fmtDur(s.offsetMs)}`}
          </span>
        </button>
      </div>
    );
  };

  return (
    <div style={overlay} role="dialog" aria-modal="true" aria-label="Step through this trace"
      ref={panelRef} tabIndex={-1}>
      <div style={header}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
          <span style={badge}>STEP-THROUGH</span>
          <span className="muted" style={{ fontSize: 11.5 }}>
            replay of the captured trace — nothing is paused, this run already finished
          </span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexShrink: 0 }}>
          <span className="muted mono" style={{ fontSize: 11 }}>
            n/→ next · p/← back · Home/End · Esc
          </span>
          <button className="btn btn-sm btn-ghost" onClick={() => onClose(cur.span.span_id)}>✕ Close</button>
        </div>
      </div>

      <div style={controls}>
        <button className="btn btn-sm" onClick={() => go(idx - 1)} disabled={idx === 0}>◀ Back</button>
        <button className="btn btn-sm" onClick={() => go(idx + 1)} disabled={idx >= steps.length - 1}>Next ▶</button>
        <span style={{ fontSize: 12.5, fontWeight: 600 }}>Step {idx + 1} <span className="muted">/ {steps.length}</span></span>
        <span style={{ flex: 1, height: 4, borderRadius: 3, background: "var(--bg-2)", minWidth: 60 }}>
          <span style={{ display: "block", height: 4, borderRadius: 3, background: "var(--accent)",
            width: `${((idx + 1) / steps.length) * 100}%` }} />
        </span>
        <span className="mono muted" style={{ fontSize: 11, flexShrink: 0 }}>
          {cur.offsetMs == null ? "no timestamp" : `+${fmtDur(cur.offsetMs)} in`}
          {totals[idx].tok ? ` · ${totals[idx].tok.toLocaleString()} tok so far` : ""}
          {fmtCost(totals[idx].usd) ? ` · ${fmtCost(totals[idx].usd)} so far` : ""}
        </span>
      </div>

      <div style={body}>
        {/* left: every step, in execution order */}
        <div ref={virtual ? v.scrollRef : undefined} style={rail}>
          {virtual && v.padTop > 0 && <div aria-hidden style={{ height: v.padTop }} />}
          {(virtual ? steps.slice(v.start, v.end) : steps).map((s, k) => railRow(s, virtual ? v.start + k : k))}
          {virtual && v.padBottom > 0 && <div aria-hidden style={{ height: v.padBottom }} />}
        </div>

        {/* right: this step's captured state */}
        <div style={detail}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4, flexWrap: "wrap" }}>
            <span style={typeBadge(cur.span.type, cur.span.status)}>{cur.span.type}</span>
            <span style={{ fontSize: 13.5, fontWeight: 600 }}>{cur.span.label || "—"}</span>
            <span style={{ fontSize: 11.5, color: cur.span.status === "failed" ? "var(--red)" : "var(--green)" }}>
              {cur.span.status}
            </span>
            <span className="muted mono" style={{ fontSize: 11 }}>{fmtDur(cur.span.duration_ms || 0)}</span>
            {meta.replay_state && (
              <span style={chip(meta.replay_state === "diverged" ? "var(--amber)" : undefined)}>
                {String(meta.replay_state)}
              </span>
            )}
          </div>

          {/* what changed since the previous step */}
          {prev ? (
            <div style={diffBox}>
              <div className="muted" style={secLbl}>Changed since step {idx}</div>
              {changes.length === 0 && !carried && gapMs == null ? (
                <div className="muted" style={{ fontSize: 12 }}>
                  Nothing recorded on this span differs from the previous one — same type, status,
                  model and provider. Only its input and output are new.
                </div>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                  {changes.map((c) => (
                    <div key={c.field} style={{ display: "flex", gap: 8, alignItems: "baseline", fontSize: 12 }}>
                      <span className="muted" style={{ width: 92, flexShrink: 0 }}>{c.field}</span>
                      <span className="mono" style={{ color: "var(--muted)", textDecoration: "line-through" }}>{c.from}</span>
                      <span className="muted">→</span>
                      <span className="mono" style={{ color: c.field === "error" ? "var(--red)" : "var(--text)" }}>{c.to}</span>
                    </div>
                  ))}
                  {carried && (
                    <div style={{ fontSize: 12, display: "flex", gap: 6, alignItems: "baseline" }}>
                      <span style={{ color: "var(--green)" }}>⤷</span>
                      <span>
                        This step&apos;s input contains step {idx}&apos;s output verbatim.
                        <span className="muted"> Substring match, the same heuristic replay threads
                        an edited output forward with — not a captured data-flow edge.</span>
                      </span>
                    </div>
                  )}
                  {gapMs != null && gapMs < -1 && (
                    <div style={{ fontSize: 12, display: "flex", gap: 6, alignItems: "baseline" }}>
                      <span style={{ color: "var(--amber)" }}>⇉</span>
                      <span>
                        Started {fmtDur(-gapMs)} <b>before</b> step {idx} finished — these overlapped.
                        <span className="muted"> The list is linear; the run was not.</span>
                      </span>
                    </div>
                  )}
                  {gapMs != null && gapMs >= 1 && (
                    <div className="muted" style={{ fontSize: 12 }}>
                      {fmtDur(gapMs)} of gap after step {idx} ended.
                    </div>
                  )}
                </div>
              )}
            </div>
          ) : (
            <div style={diffBox}>
              <div className="muted" style={secLbl}>First step</div>
              <div className="muted" style={{ fontSize: 12 }}>
                The earliest captured start in this trace. Everything after it is ordered by
                {timed === steps.length ? " its own recorded start time." : " recorded start time where one exists."}
              </div>
            </div>
          )}

          <div style={{ marginTop: 12 }}>{renderBody(cur.span)}</div>

          <div className="muted" style={{ fontSize: 11, lineHeight: 1.55, marginTop: 14, paddingTop: 10,
            borderTop: "1px solid var(--border)", display: "flex", gap: 6, alignItems: "flex-start" }}>
            <span style={{ flexShrink: 0 }}>ⓘ</span>
            <span>
              State here is what the span recorded — its input, output, error and usage. Local
              variables were never captured, so this cannot show them.
              {timed < steps.length && (
                <> {steps.length - timed} of {steps.length} spans carried no timestamp; those are
                placed after the last span that did, so their position is inferred, not measured.</>
              )}
              {timed === 0 && <> No span in this trace carried a timestamp — this is tree order, not execution order.</>}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- styles

const overlay: React.CSSProperties = {
  position: "fixed", inset: 0, zIndex: 60, background: "var(--panel)",
  display: "flex", flexDirection: "column", outline: "none",
};
const header: React.CSSProperties = {
  display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10,
  padding: "10px 14px", borderBottom: "1px solid var(--border)",
};
const controls: React.CSSProperties = {
  display: "flex", alignItems: "center", gap: 10, padding: "8px 14px",
  borderBottom: "1px solid var(--border)", flexWrap: "wrap",
};
const body: React.CSSProperties = {
  flex: 1, minHeight: 0, display: "flex",
};
const rail: React.CSSProperties = {
  width: 300, flexShrink: 0, borderRight: "1px solid var(--border)", overflowY: "auto",
  padding: 6, background: "var(--bg-2)",
};
const detail: React.CSSProperties = {
  flex: 1, minWidth: 0, overflowY: "auto", padding: "12px 16px",
};
const diffBox: React.CSSProperties = {
  border: "1px solid var(--border)", borderRadius: 8, padding: "8px 10px", marginTop: 8,
  background: "var(--bg-2)",
};
const secLbl: React.CSSProperties = {
  fontSize: 10.5, textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 5,
};
const badge: React.CSSProperties = {
  fontSize: 9.5, fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.4,
  padding: "2px 7px", borderRadius: 4, color: "var(--accent)", border: "1px solid var(--accent)",
};
function chip(color?: string): React.CSSProperties {
  return {
    fontSize: 10.5, padding: "1px 7px", borderRadius: 999, color: color || "var(--muted)",
    border: `1px solid ${color || "var(--border)"}`, whiteSpace: "nowrap",
  };
}
function dot(color: string): React.CSSProperties {
  return { width: 7, height: 7, borderRadius: 999, background: color, flexShrink: 0 };
}
function railBtn(active: boolean): React.CSSProperties {
  return {
    display: "flex", alignItems: "center", gap: 7, width: "100%", textAlign: "left",
    padding: "7px 8px", borderRadius: 7, cursor: "pointer", color: "var(--text)",
    background: active ? "var(--panel-2)" : "transparent",
    border: `1px solid ${active ? "var(--border-strong)" : "transparent"}`,
  };
}
function typeBadge(type: string, status: string): React.CSSProperties {
  const c = status === "failed" ? "var(--red)" : (TYPE_COLOR[type] || "var(--muted)");
  return { fontSize: 9.5, fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.3,
    padding: "1px 5px", borderRadius: 4, color: c, border: `1px solid ${c}`, flexShrink: 0 };
}
