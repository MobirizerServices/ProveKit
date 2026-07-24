"use client";

import { useEffect, useMemo, useState } from "react";
import { api, TraceSpan, TraceSummary } from "@/lib/api";
import ConsoleShell from "@/components/ConsoleShell";
import PageHero from "@/components/PageHero";
import Empty from "@/components/Empty";

/**
 * Sessions — multi-turn conversations, grouped from the session_id captured on traces. There's
 * no separate sessions store; a session *is* the set of runs that share a conversation id, so
 * this groups them client-side from the trace list rather than inventing a parallel record. The
 * transcript is reconstructed on demand from each turn's spans (request input → result text).
 */
type Session = {
  id: string; turns: TraceSummary[]; lastAt: string; models: string[];
  spans: number; errors: number; cost: number | null;
};

function pickTurnSpan(spans: TraceSpan[]): TraceSpan | undefined {
  // The most informative span for a transcript bubble: prefer one that has both an input and an
  // output, else the first with any text. Root spans often carry the conversation-level I/O.
  return spans.find((s) => s.request?.input && s.result?.text)
    || spans.find((s) => s.request?.input || s.result?.text)
    || spans[0];
}

export default function SessionsPage() {
  const [traces, setTraces] = useState<TraceSummary[] | null>(null);
  const [sel, setSel] = useState<string | null>(null);
  const [transcript, setTranscript] = useState<Record<string, TraceSpan[]>>({});
  const [loadingT, setLoadingT] = useState(false);

  useEffect(() => { api.traces({ limit: 200 }).then(setTraces).catch(() => setTraces([])); }, []);

  const sessions = useMemo<Session[]>(() => {
    const m = new Map<string, TraceSummary[]>();
    for (const t of traces || []) {
      if (!t.session_id) continue;
      (m.get(t.session_id) || m.set(t.session_id, []).get(t.session_id)!).push(t);
    }
    return [...m.entries()].map(([id, turns]) => {
      const sorted = [...turns].sort((a, b) => +new Date(a.created_at) - +new Date(b.created_at));
      const costed = turns.filter((t) => t.cost != null);
      return {
        id, turns: sorted,
        lastAt: sorted[sorted.length - 1].created_at,
        models: [...new Set(turns.map((t) => t.model).filter(Boolean) as string[])],
        spans: turns.reduce((n, t) => n + t.span_count, 0),
        errors: turns.filter((t) => t.status === "failed").length,
        cost: costed.length ? costed.reduce((n, t) => n + (t.cost || 0), 0) : null,
      };
    }).sort((a, b) => +new Date(b.lastAt) - +new Date(a.lastAt));
  }, [traces]);

  // Default-select the newest session once loaded.
  useEffect(() => { if (sel == null && sessions.length) setSel(sessions[0].id); }, [sessions, sel]);

  const current = sessions.find((s) => s.id === sel) || null;

  // Fetch spans for each turn of the selected session (cached per trace id).
  useEffect(() => {
    if (!current) return;
    const missing = current.turns.filter((t) => !transcript[t.trace_id]);
    if (!missing.length) return;
    setLoadingT(true);
    Promise.all(missing.map((t) => api.trace(t.trace_id).then((sp) => [t.trace_id, sp] as const).catch(() => [t.trace_id, []] as const)))
      .then((pairs) => setTranscript((m) => ({ ...m, ...Object.fromEntries(pairs) })))
      .finally(() => setLoadingT(false));
  }, [current, transcript]);

  // ---- aggregate stat tiles (all real, computed from the trace list) ----
  const stat = useMemo(() => {
    const n = sessions.length;
    const healthy = sessions.filter((s) => s.errors === 0).length;
    const avgTurns = n ? sessions.reduce((a, s) => a + s.turns.length, 0) / n : 0;
    const costed = sessions.filter((s) => s.cost != null);
    const avgCost = costed.length ? costed.reduce((a, s) => a + (s.cost || 0), 0) / costed.length : null;
    return { n, healthyPct: n ? Math.round((healthy / n) * 100) : 0, avgTurns, avgCost, costedN: costed.length };
  }, [sessions]);

  return (
    <ConsoleShell>
      <div className="cs-page" style={{ maxWidth: 1180 }}>
        <PageHero eyebrow="Observability" title="Sessions"
          sub="Back-and-forth conversations, kept together. Each reply is its own run, grouped here so you can read the whole chat instead of one turn at a time." />

        {traces == null ? <div className="muted" style={{ fontSize: 13 }}>Loading…</div>
          : sessions.length === 0 ? (
            <Empty
              what="A session keeps one conversation together."
              why="Your runs are already here, just not linked. Only your code knows which ones belong to the same chat, so it has to tell us."
              code={'import provekit.trace as pk\n\n@pk.trace(name="reply", session_id=conversation_id)\ndef reply(msg): ...'}
              action={{ label: "Look at your traces", href: "/traces" }}
            />
          ) : (
            <>
              <div className="ses-stats">
                <StatTile label="Conversations" value={String(stat.n)} sub="with a session id" />
                <StatTile label="Healthy rate" value={`${stat.healthyPct}%`} sub="no failed turns" tone={stat.healthyPct >= 80 ? "ok" : "warn"} />
                <StatTile label="Avg turns" value={stat.avgTurns.toFixed(1)} sub="per conversation" />
                <StatTile label="Avg cost / session" value={stat.avgCost == null ? "—" : `$${stat.avgCost.toFixed(4)}`}
                  sub={stat.avgCost == null ? "no usage reported" : `over ${stat.costedN} priced`} />
              </div>

              <div className="ses">
                {/* LEFT — conversation stream */}
                <aside className="ses-stream">
                  <div className="ses-stream-head">Conversation stream<span className="au2-count">{sessions.length}</span></div>
                  {sessions.map((s) => (
                    <button key={s.id} className={`ses-item ${sel === s.id ? "on" : ""}`} onClick={() => setSel(s.id)}>
                      <span className="ses-avatar">{s.id.slice(0, 2).toUpperCase()}</span>
                      <span className="ses-item-main">
                        <span className="ses-item-top">
                          <span className="ses-item-id mono">{s.id}</span>
                          <span className={`se-badge ${s.errors ? "warn" : "ok"}`}>{s.errors ? `${s.errors} failed` : "healthy"}</span>
                        </span>
                        <span className="ses-item-meta">{s.turns.length} turn{s.turns.length === 1 ? "" : "s"} · {s.spans} spans{s.cost != null ? ` · $${s.cost.toFixed(4)}` : ""}</span>
                      </span>
                    </button>
                  ))}
                </aside>

                {/* RIGHT — transcript for the selected session */}
                <section className="ses-convo">
                  {!current ? <div className="muted au2-empty" style={{ padding: 40 }}>Select a conversation.</div> : (
                    <>
                      <div className="ses-convo-head">
                        <div>
                          <div className="ses-convo-id mono">{current.id}</div>
                          <div className="ses-convo-sub">{current.models.join(", ") || "—"} · last {new Date(current.lastAt).toLocaleString()}</div>
                        </div>
                        <a className="btn btn-sm" href={`/traces?trace=${encodeURIComponent(current.turns[current.turns.length - 1].trace_id)}`}>Open trace →</a>
                      </div>

                      <div className="ses-thread">
                        {current.turns.map((t, i) => {
                          const span = pickTurnSpan(transcript[t.trace_id] || []);
                          const userText = turnText(span?.request?.input);
                          const botText = turnText(span?.result?.text) ?? turnText(span?.result?.output);
                          return (
                            <div key={t.trace_id} className="ses-turn-block">
                              <div className="ses-turn-rail"><span className="ses-turn-n">{i + 1}</span></div>
                              <div className="ses-bubbles">
                                {userText && <div className="ses-bubble user"><span className="ses-bubble-role">User</span>{userText}</div>}
                                {botText && <div className={`ses-bubble bot ${t.status === "failed" ? "fail" : ""}`}>
                                  <span className="ses-bubble-role">Assistant{t.status === "failed" ? " · failed" : ""}</span>{botText}</div>}
                                {!userText && !botText && (
                                  <a className="ses-bubble muted-bubble" href={`/traces?trace=${encodeURIComponent(t.trace_id)}`}>
                                    <span className="ses-bubble-role">{t.label || "turn"}</span>
                                    {loadingT ? "Loading transcript…" : "No text captured on this turn's spans — open the trace to inspect."}</a>
                                )}
                                <a className="ses-turn-open" href={`/traces?trace=${encodeURIComponent(t.trace_id)}`}>{t.duration_ms}ms · open trace →</a>
                              </div>
                            </div>
                          );
                        })}
                      </div>

                      <div className="ses-convo-foot">
                        <span>{current.turns.length} turns</span>
                        <span>{current.spans} spans</span>
                        <span>{current.cost != null ? `$${current.cost.toFixed(4)}` : "no cost data"}</span>
                        <span className={current.errors ? "bad" : "good"}>{current.errors ? `${current.errors} failed` : "all resolved"}</span>
                      </div>
                    </>
                  )}
                </section>
              </div>
            </>
          )}
      </div>
    </ConsoleShell>
  );
}

/**
 * The human-readable side of a captured turn.
 *
 * `@pk.trace` records a decorated function's arguments, so a one-argument agent arrives as
 * `{"arg0": "How long will it take?"}` — and the transcript was printing that verbatim. On a
 * page whose entire job is letting you read a conversation, showing the caller's argument
 * packing instead of the message defeats the point.
 *
 * Unwrapped conservatively: a single-value object is almost always the message, and beyond
 * that we prefer a field a human named (`message`, `question`, `input`, `text`, `query`,
 * `prompt`) over guessing. Anything genuinely structured is left as JSON rather than having a
 * field picked out of it arbitrarily — a wrong guess reads as the user's words and is worse
 * than obvious JSON.
 */
const TURN_KEYS = ["message", "question", "input", "text", "query", "prompt", "content"];

function turnText(raw: any): string | undefined {
  if (raw == null) return undefined;
  let v: any = raw;
  if (typeof v === "string") {
    const t = v.trim();
    if (!(t.startsWith("{") || t.startsWith("["))) return v;      // already plain text
    try { v = JSON.parse(t); } catch { return v; }                // not JSON after all
  }
  if (typeof v === "string") return v;
  if (Array.isArray(v)) {
    // a messages array — the last user turn is the one being asked
    const last = [...v].reverse().find((m) => m && typeof m === "object" && "content" in m);
    if (last && typeof last.content === "string") return last.content;
    return JSON.stringify(v).slice(0, 800);
  }
  if (typeof v === "object") {
    for (const k of TURN_KEYS) {
      if (typeof v[k] === "string" && v[k].trim()) return v[k];
    }
    const vals = Object.values(v);
    if (vals.length === 1 && typeof vals[0] === "string") return vals[0];   // {"arg0": "…"}
    return JSON.stringify(v).slice(0, 800);
  }
  return String(v);
}

function outputText(out: any): string | undefined {
  if (out == null) return undefined;
  if (typeof out === "string") return out;
  try { return JSON.stringify(out).slice(0, 800); } catch { return undefined; }
}

function StatTile({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: "ok" | "warn" }) {
  return (
    <div className="ses-tile">
      <div className="ses-tile-label">{label}</div>
      <div className={`ses-tile-value ${tone || ""}`}>{value}</div>
      {sub && <div className="ses-tile-sub">{sub}</div>}
    </div>
  );
}
