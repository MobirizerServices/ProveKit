"use client";

import { useCallback, useEffect, useState } from "react";
import { api, ReviewItem, ReviewQueue } from "@/lib/api";
import ConsoleShell from "@/components/ConsoleShell";
import PageHero from "@/components/PageHero";

/**
 * The human review queue (#40). Labelling used to be something you did if you happened to open
 * a trace; this makes it a work list ordered by what would teach us the most — judge-scored but
 * unlabelled first, because each of those becomes a calibration pair the moment it's labelled.
 *
 * A label is written through the same `POST /api/traces/{id}/feedback` the trace view uses, with
 * `source=human`, so there is one feedback store and calibration picks these up unchanged.
 */
const LABEL_NAME = "review";

export default function ReviewPage() {
  const [q, setQ] = useState<ReviewQueue | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState("");
  const [comment, setComment] = useState<Record<string, string>>({});
  const [done, setDone] = useState<Record<string, string>>({});

  const load = useCallback(() => {
    api.reviewQueue(50).then(setQ).catch((e) => setErr(e instanceof Error ? e.message : String(e)));
  }, []);
  useEffect(() => { load(); }, [load]);

  const label = async (it: ReviewItem, pass: boolean) => {
    setBusy(it.trace_id); setErr("");
    try {
      await api.addFeedback(it.trace_id, {
        name: LABEL_NAME,
        score: pass ? 1 : 0,
        value: pass ? "pass" : "fail",
        comment: comment[it.trace_id] || "",
      });
      // Keep the row on screen with its verdict rather than yanking it out from under the
      // cursor — the next click would otherwise land on whatever slid up into its place.
      setDone((d) => ({ ...d, [it.trace_id]: pass ? "pass" : "fail" }));
      setQ((cur) => cur && { ...cur, summary: { ...cur.summary,
        human_labelled: cur.summary.human_labelled + 1,
        paired: cur.summary.paired + (it.judge ? 1 : 0),
        pairs_needed: Math.max(0, cur.summary.pairs_needed - (it.judge ? 1 : 0)),
        awaiting: Math.max(0, cur.summary.awaiting - 1) } });
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(null); }
  };

  const s = q?.summary;
  const pending = (q?.items || []).filter((i) => !done[i.trace_id]);

  return (
    <ConsoleShell>
      <div className="cs-page" style={{ maxWidth: 1080 }}>
        <PageHero eyebrow="Quality" title="Review queue"
          sub="Traces worth a person's judgement, ordered by what they'd teach. A judge-scored run that nobody has labelled becomes a calibration pair the moment you rule on it."
          actions={<button className="btn-hero" onClick={load}>Refresh</button>} />

        {err && <div className="auth-err" style={{ marginBottom: 14 }}>{err}</div>}

        {s && (
          <div className="ses-stats" style={{ gridTemplateColumns: "repeat(4, 1fr)" }}>
            <Tile label="Awaiting review" value={String(s.awaiting)} sub={s.scanned >= s.scan_limit ? `newest ${s.scan_limit} scanned` : "unlabelled runs"} />
            <Tile label="You've labelled" value={String(s.human_labelled)} sub="human verdicts stored" />
            <Tile label="Calibration pairs" value={String(s.paired)} sub={`judge + human on the same run`} tone={s.paired >= s.min_pairs ? "ok" : "warn"} />
            <Tile label="Pairs still needed" value={String(s.pairs_needed)}
              sub={s.pairs_needed === 0 ? `past the ${s.min_pairs} minimum` : `before kappa is reported`}
              tone={s.pairs_needed === 0 ? "ok" : "warn"} />
          </div>
        )}

        {q == null ? <div className="muted" style={{ fontSize: 13 }}>Loading…</div>
          : q.items.length === 0 ? (
            <div className="pr-card">
              <span className="muted">Nothing awaiting review — every captured run in the recent
                window already carries a human verdict.</span>
            </div>
          ) : (
            <div className="rvw">
              {q.items.map((it) => {
                const verdict = done[it.trace_id];
                return (
                  <div key={it.trace_id} className={`rvw-row ${verdict ? "settled" : ""}`}>
                    <div className="rvw-main">
                      <div className="rvw-top">
                        <span className={`tx-status ${it.status === "failed" ? "err" : "ok"}`}>
                          ● {it.status === "failed" ? "Error" : "Success"}
                        </span>
                        <b>{it.label || it.trace_id.slice(0, 12)}</b>
                        {it.judge && (
                          <span className={`rvw-judge ${it.judge.verdict}`}
                            title={`${it.judge.name} scored this ${it.judge.score}`}>
                            judge says {it.judge.verdict} ({it.judge.score.toFixed(2)})
                          </span>
                        )}
                      </div>
                      <div className="rvw-meta">
                        {it.reason} · {it.model || "—"} · {it.duration_ms}ms ·{" "}
                        <a href={`/traces?trace=${encodeURIComponent(it.trace_id)}`}>open trace →</a>
                      </div>
                      {!verdict && (
                        <input className="rvw-comment" placeholder="Why? (optional, stored with the label)"
                          value={comment[it.trace_id] || ""}
                          onChange={(e) => setComment((c) => ({ ...c, [it.trace_id]: e.target.value }))} />
                      )}
                    </div>
                    <div className="rvw-actions">
                      {verdict ? (
                        <span className={`rvw-done ${verdict}`}>
                          {verdict === "pass" ? "✓ marked good" : "✕ marked bad"}
                          {it.judge && (it.judge.verdict === verdict
                            ? <em> · judge agreed</em>
                            : <em className="dis"> · judge disagreed</em>)}
                        </span>
                      ) : (
                        <>
                          <button className="btn btn-sm" disabled={busy === it.trace_id}
                            onClick={() => label(it, true)}>👍 Good</button>
                          <button className="btn btn-sm" disabled={busy === it.trace_id}
                            onClick={() => label(it, false)}>👎 Bad</button>
                        </>
                      )}
                    </div>
                  </div>
                );
              })}
              {pending.length === 0 && (
                <div className="muted" style={{ fontSize: 12.5, padding: "10px 2px" }}>
                  That's the batch. <button className="btn btn-sm btn-ghost" onClick={load}>Load more</button>
                </div>
              )}
            </div>
          )}
      </div>
    </ConsoleShell>
  );
}

function Tile({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: "ok" | "warn" }) {
  return (
    <div className="ses-tile">
      <div className="ses-tile-label">{label}</div>
      <div className={`ses-tile-value ${tone || ""}`}>{value}</div>
      {sub && <div className="ses-tile-sub">{sub}</div>}
    </div>
  );
}
