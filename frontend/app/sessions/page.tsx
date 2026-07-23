"use client";

import { useEffect, useMemo, useState } from "react";
import { api, TraceSummary } from "@/lib/api";
import ConsoleShell from "@/components/ConsoleShell";

/**
 * Sessions — multi-turn conversations, grouped from the session_id captured on traces. There's
 * no separate sessions store; a session *is* the set of runs that share a conversation id, so
 * this groups them client-side from the trace list rather than inventing a parallel record.
 */
type Session = {
  id: string; turns: TraceSummary[]; lastAt: string; models: string[]; spans: number; errors: number;
};

export default function SessionsPage() {
  const [traces, setTraces] = useState<TraceSummary[] | null>(null);
  useEffect(() => { api.traces({ limit: 200 }).then(setTraces).catch(() => setTraces([])); }, []);

  const sessions = useMemo<Session[]>(() => {
    const m = new Map<string, TraceSummary[]>();
    for (const t of traces || []) {
      if (!t.session_id) continue;
      (m.get(t.session_id) || m.set(t.session_id, []).get(t.session_id)!).push(t);
    }
    return [...m.entries()].map(([id, turns]) => {
      const sorted = [...turns].sort((a, b) => +new Date(a.created_at) - +new Date(b.created_at));
      return {
        id, turns: sorted,
        lastAt: sorted[sorted.length - 1].created_at,
        models: [...new Set(turns.map((t) => t.model).filter(Boolean) as string[])],
        spans: turns.reduce((n, t) => n + t.span_count, 0),
        errors: turns.filter((t) => t.status === "failed").length,
      };
    }).sort((a, b) => +new Date(b.lastAt) - +new Date(a.lastAt));
  }, [traces]);

  return (
    <ConsoleShell>
      <div className="cs-page" style={{ maxWidth: 1100 }}>
        <div className="page-head" style={{ marginBottom: 22 }}>
          <div>
            <div className="page-eyebrow">Observability</div>
            <h1>Sessions</h1>
            <p>Multi-turn conversations, grouped by the session id your agent reports. Each turn
              is a captured trace — open one to inspect its spans.</p>
          </div>
        </div>

        {traces == null ? <div className="muted" style={{ fontSize: 13 }}>Loading…</div>
          : sessions.length === 0 ? (
            <div className="pr-card">
              <span className="muted">No sessions yet. Pass a stable <code className="mono">session_id</code>{" "}
                (or <code className="mono">gen_ai.conversation.id</code>) on the runs of one conversation
                and they group here.</span>
            </div>
          ) : (
            <div className="se-list">
              {sessions.map((s) => (
                <div key={s.id} className="se-card">
                  <div className="se-head">
                    <span className="se-id mono">{s.id}</span>
                    <span className={`se-badge ${s.errors ? "warn" : "ok"}`}>
                      {s.errors ? `${s.errors} failed` : "healthy"}
                    </span>
                    <span className="se-meta">{s.turns.length} turn{s.turns.length === 1 ? "" : "s"} · {s.spans} spans · {s.models.join(", ") || "—"}</span>
                    <span className="se-time">{new Date(s.lastAt).toLocaleString()}</span>
                  </div>
                  <div className="se-turns">
                    {s.turns.map((t, i) => (
                      <a key={t.trace_id} href={`/traces?trace=${encodeURIComponent(t.trace_id)}`}
                        className={`se-turn ${t.status === "failed" ? "fail" : ""}`} title={t.label}>
                        <span className="se-turn-n">{i + 1}</span>
                        <span className="se-turn-label">{t.label || "turn"}</span>
                        <span className="se-turn-ms">{t.duration_ms}ms</span>
                      </a>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
      </div>
    </ConsoleShell>
  );
}
