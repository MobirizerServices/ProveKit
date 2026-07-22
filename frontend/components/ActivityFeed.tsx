"use client";

// Project activity (#74) — a view of the audit trail, scoped to one project.
//
// It reads /api/activity directly rather than going through lib/api's wrapper because the feed
// is the only caller of it so far; the wrapper's `j` isn't exported. Same contract though:
// same-origin, credentials included, X-Project-Id so the backend scopes and authorises it.
//
// The one thing this component must not do is imply completeness. The backend tells it which
// actions are defined but not yet recorded, and that list is rendered — a reader who can't
// tell "nobody changed anything" from "we don't capture that yet" will read the empty state
// as a guarantee nobody made a change.

import { useCallback, useEffect, useState } from "react";
import { API_BASE, getProjectId } from "@/lib/api";

interface Entry {
  id: number;
  action: string;
  label: string;          // human phrasing, decided server-side beside the action constants
  actor_email: string;
  target_type: string;
  target_id: string;
  target_label: string;
  detail: Record<string, any>;
  created_at: string;
}
interface Gap { action: string; label: string }
interface FeedResponse { entries: Entry[]; next_cursor: number | null; not_yet_recorded: Gap[] }

const PAGE = 25;

/** `projectId` overrides the globally selected project — settings shows a feed for whichever
 *  project the list is pointing at, which is not necessarily the one you're working in. */
export default function ActivityFeed({ projectId }: { projectId?: number | null }) {
  const [entries, setEntries] = useState<Entry[]>([]);
  const [cursor, setCursor] = useState<number | null>(null);
  const [gaps, setGaps] = useState<Gap[]>([]);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");

  const load = useCallback(async (after: number | null) => {
    const pid = projectId != null ? String(projectId) : getProjectId();
    const qs = new URLSearchParams({ limit: String(PAGE) });
    if (after != null) qs.set("cursor", String(after));
    const res = await fetch(`${API_BASE}/api/activity?${qs}`, {
      credentials: "include",
      headers: pid ? { "X-Project-Id": pid } : {},
    });
    if (!res.ok) throw new Error(String(res.status));
    return (await res.json()) as FeedResponse;
  }, [projectId]);

  useEffect(() => {
    let live = true;
    // Clear first: switching projects must not leave the previous tenant's rows on screen
    // while the new feed is in flight.
    setState("loading"); setEntries([]); setCursor(null);
    load(null).then((r) => {
      if (!live) return;
      setEntries(r.entries); setCursor(r.next_cursor); setGaps(r.not_yet_recorded);
      setState("ready");
    }).catch(() => { if (live) setState("error"); });
    return () => { live = false; };
  }, [load]);

  const more = () => {
    load(cursor).then((r) => {
      setEntries((prev) => [...prev, ...r.entries]);   // keyset paging: no overlap to dedupe
      setCursor(r.next_cursor);
    }).catch(() => setState("error"));
  };

  return (
    <div>
      <div style={label}>Activity</div>
      <p className="muted" style={{ fontSize: 12, margin: "0 0 8px" }}>
        Who changed what in this project. Drawn from the audit trail, so it shows the project-scoped part of the
        record the platform audit log keeps for this project.
      </p>

      {state === "error" && (
        <div className="muted" style={{ fontSize: 12.5 }}>
          Couldn&apos;t load activity for this project.
        </div>
      )}

      {state !== "error" && (
        <div style={{ ...panel, padding: 0, overflow: "hidden" }}>
          {state === "loading" && <div style={{ ...rowBox, color: "var(--faint)", fontSize: 12.5 }}>Loading…</div>}
          {state === "ready" && entries.length === 0 && (
            <div style={{ ...rowBox, color: "var(--muted)", fontSize: 12.5 }}>
              No recorded changes yet.
            </div>
          )}
          {entries.map((e) => <Row key={e.id} e={e} />)}
          {cursor != null && (
            <div style={{ ...rowBox, borderBottom: "none" }}>
              <button className="btn btn-sm btn-ghost" onClick={more}>Load older</button>
            </div>
          )}
        </div>
      )}

      {gaps.length > 0 && (
        <p className="muted" style={{ fontSize: 11.5, margin: "8px 0 0", lineHeight: 1.55 }}>
          Not captured yet, so it will never appear above:{" "}
          {gaps.map((g) => g.label).join(", ")}.
        </p>
      )}
    </div>
  );
}

function Row({ e }: { e: Entry }) {
  const chips = Object.entries(e.detail || {}).slice(0, 4);
  return (
    <div style={rowBox}>
      <div style={{ display: "flex", gap: 8, alignItems: "baseline", flexWrap: "wrap" }}>
        <span style={{ fontSize: 13 }}>{e.actor_email || "someone"}</span>
        <span className="muted" style={{ fontSize: 12.5 }}>{e.label}</span>
        {e.target_label && (
          <span style={{ fontSize: 12.5, fontFamily: "var(--mono)", color: "var(--accent)" }}>
            {e.target_label}
          </span>
        )}
        <span style={{ flex: 1 }} />
        <span className="muted" style={{ fontSize: 11.5, whiteSpace: "nowrap" }} title={e.created_at}>
          {rel(e.created_at)}
        </span>
      </div>
      {chips.length > 0 && (
        <div style={{ display: "flex", gap: 6, marginTop: 5, flexWrap: "wrap" }}>
          {chips.map(([k, v]) => (
            <span key={k} style={chip}>{k} {fmt(v)}</span>
          ))}
        </div>
      )}
    </div>
  );
}

// Values come from JSON detail blobs, so anything can turn up. Clip hard rather than let one
// long value push the timestamp off the row.
function fmt(v: any): string {
  const s = typeof v === "object" && v !== null ? JSON.stringify(v) : String(v);
  return s.length > 40 ? `${s.slice(0, 40)}…` : s;
}

function rel(iso: string): string {
  const d = (Date.now() - new Date(iso).getTime()) / 1000;
  if (!isFinite(d)) return "";
  if (d < 90) return "just now";
  if (d < 3600) return `${Math.round(d / 60)}m ago`;
  if (d < 86400) return `${Math.round(d / 3600)}h ago`;
  return `${Math.round(d / 86400)}d ago`;
}

const panel: React.CSSProperties = { background: "var(--panel)", border: "1px solid var(--border)", borderRadius: 12 };
const rowBox: React.CSSProperties = { padding: "9px 12px", borderBottom: "1px solid var(--border)" };
const chip: React.CSSProperties = {
  fontSize: 11, fontFamily: "var(--mono)", color: "var(--text-dim)",
  background: "var(--panel-2)", border: "1px solid var(--border)",
  borderRadius: 6, padding: "1px 6px",
};
const label: React.CSSProperties = { fontSize: 11, textTransform: "uppercase", letterSpacing: 0.4, color: "var(--muted)", marginBottom: 6 };
