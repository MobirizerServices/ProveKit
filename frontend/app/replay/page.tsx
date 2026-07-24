"use client";

import { useEffect, useMemo, useState } from "react";
import { api, ProviderConnection, ReplayResult, TraceSpan, TraceSummary } from "@/lib/api";
import { estimateCost, fmtCost } from "@/lib/cost";
import ConsoleShell from "@/components/ConsoleShell";
import PageHero from "@/components/PageHero";
import TraceCompare from "@/components/TraceCompare";
import { parseMessages } from "@/components/TraceDetail";

/**
 * The replay workspace: take a captured run, change one thing, and re-run it against the
 * *recorded* tool responses so the only difference is the thing you changed.
 *
 * The fidelity report is the point. A replay whose tools returned something new isn't a
 * reproduction, it's a different run that happens to start the same way — so the verdict is
 * shown as prominently as the result, and a diverged replay says so rather than presenting
 * its numbers as a comparison.
 */
export default function ReplayPage() {
  const [traces, setTraces] = useState<TraceSummary[] | null>(null);
  const [originId, setOriginId] = useState<string>("");
  const [spans, setSpans] = useState<TraceSpan[] | null>(null);
  const [forkId, setForkId] = useState<string>("");
  const [conns, setConns] = useState<ProviderConnection[]>([]);
  const [connId, setConnId] = useState<string>("");

  const [model, setModel] = useState("");
  const [prompt, setPrompt] = useState("");
  // The captured span doesn't record the original sampling params, so there's nothing to carry
  // forward — but the backend replay honours whatever params it's sent. Exposing temperature
  // lets you match the original (if you know it) instead of being silently pinned to the
  // provider default. Blank = default.
  const [temperature, setTemperature] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [result, setResult] = useState<ReplayResult | null>(null);
  const [candidate, setCandidate] = useState<TraceSpan[] | null>(null);
  const [showDiff, setShowDiff] = useState(false);

  useEffect(() => { api.traces({ limit: 40 }).then(setTraces).catch(() => setTraces([])); }, []);
  useEffect(() => {
    api.connections().then((cs) => {
      const usable = cs.filter((c) => c.provider !== "mock");
      setConns(usable);
      if (usable[0]) setConnId((v) => v || String(usable[0].id));
    }).catch(() => {});
  }, []);

  // Load the chosen origin and default the fork to its first model call.
  useEffect(() => {
    if (!originId) { setSpans(null); return; }
    setSpans(null); setResult(null); setCandidate(null); setErr("");
    api.trace(originId).then((s) => {
      setSpans(s);
      const llm = s.find((x) => x.type === "llm");
      if (llm) selectFork(llm);
    }).catch(() => setSpans([]));
  }, [originId]);

  const llmSpans = useMemo(() => (spans || []).filter((s) => s.type === "llm"), [spans]);
  const fork = llmSpans.find((s) => s.span_id === forkId) || null;

  function selectFork(s: TraceSpan) {
    setForkId(s.span_id);
    setModel(s.request?.model || "");
    // A captured request stores its conversation in `input` — sometimes JSON messages,
    // sometimes plain text. parseMessages is the same reader the trace inspector uses.
    const msgs = parseMessages(s.request?.input) || [];
    const last = [...msgs].reverse().find((m) => m.role === "user") || msgs[msgs.length - 1];
    setPrompt(last?.content ?? (typeof s.request?.input === "string" ? s.request.input : ""));
  }

  const run = async () => {
    if (!fork || !originId) return;
    setBusy(true); setErr(""); setResult(null); setCandidate(null);
    try {
      // Replace the content of the message the editor is showing, leaving the rest of the
      // conversation intact — the replay is meant to isolate one change.
      const msgs = (parseMessages(fork.request?.input) || []).map((m) => ({ ...m }));
      const idx = msgs.map((m) => m.role).lastIndexOf("user");
      if (idx >= 0) msgs[idx] = { ...msgs[idx], content: prompt };
      else msgs.push({ role: "user", content: prompt });

      const t = temperature.trim();
      const params = t !== "" && !Number.isNaN(Number(t)) ? { temperature: Number(t) } : {};
      const r = await api.replay({
        origin_trace_id: originId,
        fork_span_id: fork.span_id,
        model: model || fork.request?.model || "",
        messages: msgs,
        params,
        connection_id: Number(connId),
      });
      setResult(r);
      api.trace(r.new_trace_id).then(setCandidate).catch(() => {});
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const originStats = useMemo(() => summarise(spans), [spans]);
  const candStats = useMemo(() => summarise(candidate), [candidate]);

  return (
    <ConsoleShell>
      <div className="page">
        <div className="page-inner" style={{ maxWidth: 1180 }}>
          <PageHero eyebrow="Debugging" title="Replay workspace"
            sub="Replace the prompt or model, preserve the recorded tool responses, and see precisely where execution diverges." />

          {/* ---------------- pick an origin ---------------- */}
          <div className="rp-bar">
            <label>
              <span>Origin trace</span>
              <select value={originId} onChange={(e) => setOriginId(e.target.value)}>
                <option value="">Select a captured run…</option>
                {(traces || []).map((t) => (
                  <option key={t.trace_id} value={t.trace_id}>
                    {t.label || t.trace_id.slice(0, 8)} · {t.span_count} spans · {t.status}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span>Fork at</span>
              <select value={forkId} disabled={!llmSpans.length}
                onChange={(e) => { const s = llmSpans.find((x) => x.span_id === e.target.value); if (s) selectFork(s); }}>
                {llmSpans.length === 0 && <option>no model calls in this trace</option>}
                {llmSpans.map((s) => (
                  <option key={s.span_id} value={s.span_id}>{s.label} · {s.request?.model || "—"}</option>
                ))}
              </select>
            </label>
            <label>
              <span>Run with</span>
              <select value={connId} onChange={(e) => setConnId(e.target.value)}>
                {conns.length === 0
                  ? <option value="">No model connection</option>
                  : conns.map((c) => <option key={c.id} value={String(c.id)}>{c.label || c.provider}</option>)}
              </select>
            </label>
            <button className="btn btn-run" disabled={!fork || busy} onClick={run}>
              {busy ? "Replaying…" : "Replay"}
            </button>
          </div>

          {err && <div className="auth-err" style={{ marginBottom: 14 }}>{err}</div>}

          {!originId ? (
            <div className="pr-card">
              <span className="muted">Pick a captured run to replay. Everything downstream of the
                fork point reuses its recorded tool responses.</span>
            </div>
          ) : !fork ? (
            <div className="pr-card"><span className="muted">Loading trace…</span></div>
          ) : (
            <div className="rp-grid">
              {/* ---------------- the edit ---------------- */}
              <div className="rp-edit">
                <div className="rp-panel-h">Candidate</div>
                <div className="rp-row2">
                  <label className="rp-field">
                    <span>Model</span>
                    <input value={model} onChange={(e) => setModel(e.target.value)} placeholder="gpt-4o-mini" />
                  </label>
                  <label className="rp-field">
                    <span>Temperature <span className="rp-hint">default</span></span>
                    <input type="number" min={0} max={2} step={0.1} value={temperature}
                      placeholder="—" onChange={(e) => setTemperature(e.target.value)} />
                  </label>
                </div>
                <label className="rp-field">
                  <span>Prompt</span>
                  <textarea value={prompt} rows={11} onChange={(e) => setPrompt(e.target.value)} />
                </label>
                <div className="rp-origin-note">
                  Original: <b className="mono">{fork.request?.model || "—"}</b> · forking at{" "}
                  <b className="mono">{fork.label}</b>
                </div>
              </div>

              {/* ---------------- the verdict ---------------- */}
              <div className="rp-result">
                <div className="rp-panel-h">Comparison</div>
                {!result ? (
                  <div className="rp-empty">
                    <span className="muted">Run a replay to compare it against the original.</span>
                  </div>
                ) : (
                  <>
                    <div className="rp-ab">
                      <div>
                        <span>Original</span>
                        <b>{fmtMs(originStats.duration)}</b>
                        <small>{meta(originStats)}</small>
                      </div>
                      <div className="rp-ab-arrow">→</div>
                      <div>
                        <span>Candidate</span>
                        <b>{candidate ? fmtMs(candStats.duration) : "…"}</b>
                        <small>{candidate ? meta(candStats) : "loading"}</small>
                      </div>
                    </div>

                    <Fidelity result={result} />

                    <div className="rp-out">
                      <span className="rp-out-h">Fork output</span>
                      <div className="rp-out-body">{result.fork_output || <span className="muted">empty</span>}</div>
                    </div>

                    <div className="rp-actions">
                      <button className="btn btn-run" disabled={!candidate} onClick={() => setShowDiff(true)}>
                        View structural diff
                      </button>
                      <a className="btn btn-ghost" href={`/traces?trace=${result.new_trace_id}`}>Open candidate trace</a>
                    </div>
                  </>
                )}
              </div>
            </div>
          )}
        </div>
      </div>

      {showDiff && result && (
        <TraceCompare aId={originId} bId={result.new_trace_id} onClose={() => setShowDiff(false)} />
      )}
    </ConsoleShell>
  );
}

/** The trust verdict. A diverged replay is a hypothesis, and the UI has to say so. */
function Fidelity({ result }: { result: ReplayResult }) {
  const f = result.fidelity;
  const reliable = result.reliable !== false;
  return (
    <div className={`rp-verdict ${reliable ? "ok" : "warn"}`}>
      <i>{reliable ? "✓" : "⚠"}</i>
      <div>
        <b>{reliable ? "Reliable comparison" : "Not a faithful reproduction"}</b>
        <small>
          {result.fidelity_warning
            || (f ? `${f.recorded} span${f.recorded === 1 ? "" : "s"} replayed from the recording, ${f.live} re-executed live, ${f.diverged} diverged.`
                  : "No input-dependent tool spans changed.")}
        </small>
      </div>
    </div>
  );
}

function summarise(spans: TraceSpan[] | null) {
  if (!spans?.length) return { duration: 0, tokens: 0, cost: 0 };
  const ids = new Set(spans.map((s) => s.span_id));
  const root = spans.find((s) => !s.parent_span_id || !ids.has(s.parent_span_id));
  let tokens = 0, cost = 0;
  for (const s of spans) {
    const u = s.result?.meta?.usage || {};
    tokens += (u.input_tokens || 0) + (u.output_tokens || 0);
    cost += estimateCost(s.request?.model, u.input_tokens, u.output_tokens) || 0;
  }
  return { duration: root?.duration_ms || 0, tokens, cost };
}

const fmtMs = (ms: number) => (ms >= 1000 ? `${(ms / 1000).toFixed(2)}s` : `${ms}ms`);
/** Cost is unknown for spans with no usage — drop it rather than printing a bare separator. */
function meta(s: { cost: number; tokens: number }): string {
  const cost = s.cost ? fmtCost(s.cost) : "";
  const tokens = `${s.tokens.toLocaleString()} tokens`;
  return cost ? `${cost} · ${tokens}` : tokens;
}
