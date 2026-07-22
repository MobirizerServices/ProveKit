"use client";

import { type MutableRefObject, useCallback, useEffect, useMemo, useRef, useState } from "react";

// Row windowing for long lists: mount only the rows a scroll container can actually show and
// stand in for the rest with a spacer above and below. Hand-rolled rather than pulled from npm —
// the portal ships under a strict CSP with a zero-runtime-dependency posture, and a windowing
// core is ~100 lines.
//
// Heights are measured, not assumed. A waterfall row grows when its span is expanded, and an
// estimate-only virtualizer would then shift the scrollbar under the reader's cursor.

export interface VirtualRows {
  /** Attach to the element that scrolls. */
  scrollRef: MutableRefObject<HTMLDivElement | null>;
  /** Mount rows `[start, end)`. */
  start: number;
  end: number;
  /** Spacer heights standing in for the rows above / below the window. */
  padTop: number;
  padBottom: number;
  /** Ref callback for row `index` — records its real height. */
  rowRef: (index: number) => (el: HTMLElement | null) => void;
  /** Bring a row into view even when it isn't currently mounted. */
  scrollToIndex: (index: number, align?: "start" | "center" | "nearest") => void;
}

// Largest i in [0, count] with offsets[i] <= y.
function rowAt(offsets: Float64Array, y: number, count: number): number {
  let lo = 0, hi = count;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (offsets[mid] <= y) lo = mid; else hi = mid - 1;
  }
  return lo;
}

export function useVirtualRows(
  count: number,
  { estimate, overscan = 6, enabled = true }: { estimate: number; overscan?: number; enabled?: boolean },
): VirtualRows {
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const heights = useRef(new Map<number, number>());
  const mounted = useRef(new Map<number, HTMLElement>());
  const rowObserver = useRef<ResizeObserver | null>(null);
  const refCache = useRef(new Map<number, (el: HTMLElement | null) => void>());
  const [version, setVersion] = useState(0);   // bumped whenever a measurement changes
  const [scrollTop, setScrollTop] = useState(0);
  const [viewport, setViewport] = useState(0);

  // Heights are keyed by row index, so a list of a different length is a different list and
  // every measurement in the cache is stale.
  const lastCount = useRef(count);
  if (lastCount.current !== count) {
    lastCount.current = count;
    heights.current.clear();
  }

  const offsets = useMemo(() => {
    const o = new Float64Array(count + 1);
    for (let i = 0; i < count; i++) o[i + 1] = o[i] + (heights.current.get(i) ?? estimate);
    return o;
  }, [count, estimate, version]);

  // scrollToIndex is called from event handlers, so it needs the offsets of the render it fires
  // from rather than the ones it closed over.
  const offsetsRef = useRef(offsets);
  offsetsRef.current = offsets;

  const record = useCallback((index: number, h: number) => {
    if (!(h > 0)) return;
    const prev = heights.current.get(index);
    if (prev != null && Math.abs(prev - h) < 0.5) return;
    heights.current.set(index, h);
    setVersion((v) => v + 1);
  }, []);

  // A row can change height long after it mounted (its span gets expanded, a payload is
  // un-clamped), so heights come from a ResizeObserver rather than a one-shot read at mount.
  useEffect(() => {
    if (!enabled || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver((entries) => {
      for (const e of entries) {
        const el = e.target as HTMLElement;
        const i = Number(el.dataset.vrow);
        if (Number.isFinite(i)) record(i, el.offsetHeight);
      }
    });
    rowObserver.current = ro;
    // Rows attached during the first commit ran before this effect existed.
    mounted.current.forEach((el) => ro.observe(el));
    return () => { ro.disconnect(); rowObserver.current = null; };
  }, [enabled, record]);

  const rowRef = useCallback((index: number) => {
    let fn = refCache.current.get(index);
    if (!fn) {
      fn = (el: HTMLElement | null) => {
        const prev = mounted.current.get(index);
        if (prev && prev !== el) {
          rowObserver.current?.unobserve(prev);
          mounted.current.delete(index);
        }
        if (!el) return;
        el.dataset.vrow = String(index);
        mounted.current.set(index, el);
        rowObserver.current?.observe(el);
        record(index, el.offsetHeight);   // also covers browsers without ResizeObserver
      };
      refCache.current.set(index, fn);
    }
    return fn;
  }, [record]);

  useEffect(() => {
    const el = scrollRef.current;
    if (!enabled || !el) return;
    const sync = () => { setScrollTop(el.scrollTop); setViewport(el.clientHeight); };
    sync();
    el.addEventListener("scroll", sync, { passive: true });
    const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(sync) : null;
    ro?.observe(el);
    return () => { el.removeEventListener("scroll", sync); ro?.disconnect(); };
  }, [enabled]);

  const scrollToIndex = useCallback((index: number, align: "start" | "center" | "nearest" = "nearest") => {
    const el = scrollRef.current;
    const o = offsetsRef.current;
    if (!el || o.length < 2) return;
    const i = Math.max(0, Math.min(index, o.length - 2));
    const top = o[i], bottom = o[i + 1];
    const vh = el.clientHeight || 1;
    let next = el.scrollTop;
    if (align === "start") next = top;
    else if (align === "center") next = (top + bottom) / 2 - vh / 2;
    else if (top < el.scrollTop) next = top;
    else if (bottom > el.scrollTop + vh) next = bottom - vh;
    next = Math.max(0, Math.min(next, Math.max(0, o[o.length - 1] - vh)));
    if (Math.abs(next - el.scrollTop) < 0.5) return;
    el.scrollTop = next;
    // Mount the target in this render pass instead of waiting for the DOM scroll event a frame
    // later: callers (keyboard nav, deep links) want to focus the row straight afterwards.
    setScrollTop(next);
  }, []);

  const win = useMemo(() => {
    if (!enabled || count === 0) return { start: 0, end: count, padTop: 0, padBottom: 0 };
    const vh = viewport || 600;   // pre-measurement guess; corrected on the first layout pass
    const start = Math.max(0, rowAt(offsets, scrollTop, count) - overscan);
    const end = Math.min(count, rowAt(offsets, scrollTop + vh, count) + 1 + overscan);
    return { start, end, padTop: offsets[start], padBottom: offsets[count] - offsets[end] };
  }, [enabled, count, offsets, scrollTop, viewport, overscan]);

  return { scrollRef, ...win, rowRef, scrollToIndex };
}
