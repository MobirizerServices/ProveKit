"use client";

// Interactive product tour (#37).
//
// A first visit to a *populated* portal should teach the flow, not present it cold — and since
// a new account now gets the "Sample data (demo)" project, there is real material to teach
// against on visit one. So this is a spotlight tour: it dims the page, rings one real element
// at a time, and explains it in place. Nothing is faked; every step points at a live control.
//
// TWO RULES IT KEEPS
//
//  1. It never runs twice. `useTour` writes the storage key the moment the tour *opens*, not
//     when it finishes — someone who reloads mid-tour, or closes the tab on step 2, has already
//     been shown it, and a tour that reappears is worse than no tour at all. Dismissal is
//     therefore permanent by construction, and the only way back in is the explicit
//     "Take the tour" button the host page renders.
//  2. A missing target never blocks it. If a step's element isn't on the page (a layout the
//     tour didn't anticipate, a trace that hasn't loaded yet), the card centres itself and the
//     step still reads — instead of the tour stalling on a `querySelector` that returned null.

import React, { useCallback, useEffect, useRef, useState } from "react";

export interface TourStep {
  /** CSS selector for the element to spotlight. Omit (or miss) → the card centres itself. */
  target?: string;
  title: string;
  body: React.ReactNode;
  /**
   * Runs just before the step is measured, so the page can put itself in the state the step
   * talks about (e.g. open a trace so the flow graph exists). Must be idempotent — a resize
   * or a re-measure can call it again.
   */
  before?: () => void;
}

const CARD_W = 330;
const GAP = 12;      // px between the ringed element and the card
const PAD = 6;       // spotlight padding around the element

/**
 * First-run gate. `ready` is the host page saying "there is something here worth touring" —
 * pass `false` while loading or while the portal is empty, or the tour teaches an empty screen
 * and burns its one showing.
 */
export function useTour(storageKey: string, ready: boolean) {
  const [open, setOpen] = useState(false);
  // Assume seen until localStorage says otherwise: the wrong guess on the first paint would
  // flash a tour at someone who has already dismissed it.
  const [seen, setSeen] = useState(true);

  useEffect(() => {
    try { setSeen(!!localStorage.getItem(storageKey)); } catch { setSeen(true); }
  }, [storageKey]);

  const markSeen = useCallback(() => {
    setSeen(true);
    try { localStorage.setItem(storageKey, "1"); } catch { /* no storage — then it may repeat */ }
  }, [storageKey]);

  useEffect(() => {
    if (ready && !seen) { markSeen(); setOpen(true); }
  }, [ready, seen, markSeen]);

  return {
    open,
    /** True once the auto-run has happened — the host uses it to offer a manual replay. */
    seen,
    start: useCallback(() => setOpen(true), []),
    close: useCallback(() => setOpen(false), []),
  };
}

export default function Tour({ steps, open, onClose }: { steps: TourStep[]; open: boolean; onClose: () => void }) {
  const [i, setI] = useState(0);
  const [rect, setRect] = useState<DOMRect | null>(null);
  const cardRef = useRef<HTMLDivElement | null>(null);
  // Steps are usually an inline literal in the host page, so a new array identity arrives on
  // every render. Holding them in a ref keeps the measurement effect keyed on the step *index*
  // — depending on the array would re-run (and re-scroll) on every parent render.
  const stepsRef = useRef(steps);
  stepsRef.current = steps;

  useEffect(() => { if (open) setI(0); }, [open]);

  useEffect(() => {
    if (!open) return;
    const step = stepsRef.current[i];
    if (!step) return;
    try { step.before?.(); } catch { /* a step that can't prepare still reads */ }

    const measure = () => {
      const el = step.target ? document.querySelector(step.target) : null;
      setRect(el ? (el as HTMLElement).getBoundingClientRect() : null);
    };
    const el = step.target ? document.querySelector(step.target) : null;
    (el as HTMLElement | null)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    measure();
    // Re-measure after the page settles: `before()` may have selected a trace whose panel is
    // still fetching, and a smooth scroll finishes on its own schedule.
    const timers = [window.setTimeout(measure, 120), window.setTimeout(measure, 450), window.setTimeout(measure, 900)];
    window.addEventListener("resize", measure);
    window.addEventListener("scroll", measure, true);
    return () => {
      timers.forEach(clearTimeout);
      window.removeEventListener("resize", measure);
      window.removeEventListener("scroll", measure, true);
    };
  }, [open, i]);

  const last = i >= steps.length - 1;
  const next = useCallback(() => { if (last) onClose(); else setI((n) => n + 1); }, [last, onClose]);
  const back = useCallback(() => setI((n) => Math.max(0, n - 1)), []);

  useEffect(() => {
    if (!open) return;
    cardRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { e.preventDefault(); onClose(); }
      else if (e.key === "ArrowRight" || e.key === "Enter") { e.preventDefault(); next(); }
      else if (e.key === "ArrowLeft") { e.preventDefault(); back(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, next, back, onClose]);

  if (!open || !steps.length) return null;
  const step = steps[Math.min(i, steps.length - 1)];

  // Card placement: under the ring if it fits, above if not, centred when there's no ring.
  const vh = typeof window === "undefined" ? 800 : window.innerHeight;
  const vw = typeof window === "undefined" ? 1200 : window.innerWidth;
  const below = rect ? rect.bottom + GAP : 0;
  const fitsBelow = rect ? vh - below > 220 : false;
  const cardStyle: React.CSSProperties = rect
    ? {
        position: "fixed", width: CARD_W, zIndex: 1002,
        left: Math.max(12, Math.min(rect.left, vw - CARD_W - 12)),
        ...(fitsBelow ? { top: below } : { bottom: Math.max(12, vh - rect.top + GAP) }),
      }
    : { position: "fixed", width: CARD_W, zIndex: 1002, left: "50%", top: "50%", transform: "translate(-50%,-50%)" };

  return (
    <>
      {/* Click-off dismisses. The ring itself is pointer-events:none so it never eats a click. */}
      <div onClick={onClose} style={{ position: "fixed", inset: 0, zIndex: 1000,
        background: rect ? "transparent" : "rgba(0,0,0,.62)" }} />
      {rect && (
        <div aria-hidden style={{
          position: "fixed", zIndex: 1001, pointerEvents: "none",
          left: rect.left - PAD, top: rect.top - PAD, width: rect.width + PAD * 2, height: rect.height + PAD * 2,
          borderRadius: 12, border: "1px solid var(--accent)",
          boxShadow: "0 0 0 9999px rgba(0,0,0,.62), 0 0 0 4px var(--accent-ring)",
          transition: "left .18s var(--ease), top .18s var(--ease), width .18s var(--ease), height .18s var(--ease)",
        }} />
      )}
      <div ref={cardRef} role="dialog" aria-modal="true" aria-label={`Tour step ${i + 1}: ${step.title}`} tabIndex={-1}
        style={{ ...cardStyle, background: "var(--panel)", border: "1px solid var(--border-strong)",
          borderRadius: 12, padding: 14, boxShadow: "var(--sh-3)", outline: "none" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 8 }}>
          <span style={{ fontSize: 13.5, fontWeight: 600 }}>{step.title}</span>
          <span className="muted mono" style={{ fontSize: 10.5 }}>{i + 1} / {steps.length}</span>
        </div>
        <div className="muted" style={{ fontSize: 12.5, lineHeight: 1.6, margin: "7px 0 12px" }}>{step.body}</div>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <button className="btn btn-sm btn-ghost" onClick={onClose}>{last ? "Close" : "Skip"}</button>
          <span style={{ flex: 1 }} />
          {i > 0 && <button className="btn btn-sm" onClick={back}>Back</button>}
          <button className="btn btn-sm" onClick={next}
            style={{ borderColor: "var(--accent)", color: "var(--accent)" }}>{last ? "Done" : "Next"}</button>
        </div>
      </div>
    </>
  );
}
