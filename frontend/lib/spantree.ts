/**
 * Orphan detection for a loaded trace (#3).
 *
 * A span whose `parent_span_id` names a span that never arrived is re-parented to the top level
 * by every tree view here, so it still renders. That re-parenting is the right call — dropping
 * it would make the flow silently omit work that actually ran — but on its own it is a lie of
 * omission: the span appears to be a root when it is really a fragment of a subtree whose parent
 * is missing. These helpers name that condition so the views can mark it.
 *
 * Safe to compute client-side: `GET /api/traces/{id}` returns every span of the trace with no
 * limit, so "not in this set" genuinely means "not stored", not "not fetched yet".
 */
export interface SpanLike { span_id: string; parent_span_id?: string }

/** Ids of spans that name a parent which isn't in this trace. */
export function orphanIds(spans: SpanLike[]): Set<string> {
  const present = new Set(spans.map((s) => s.span_id));
  const out = new Set<string>();
  for (const s of spans) {
    const p = s.parent_span_id;
    // A span pointing at itself is malformed rather than orphaned, but it would otherwise loop
    // the tree builders — treat it as detached too.
    if (p && (!present.has(p) || p === s.span_id)) out.add(s.span_id);
  }
  return out;
}

/** True when any span in the trace has a parent that never arrived. */
export function hasOrphans(spans: SpanLike[]): boolean {
  return orphanIds(spans).size > 0;
}
