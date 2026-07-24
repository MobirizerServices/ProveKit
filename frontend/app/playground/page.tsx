"use client";

import { useEffect, useMemo, useState } from "react";
import { api, PlaygroundMessage, PlaygroundResult, ProviderConnection, SavedPrompt } from "@/lib/api";
import { estimateCost, fmtCost } from "@/lib/cost";
import ConsoleShell from "@/components/ConsoleShell";
import PageHero from "@/components/PageHero";

/**
 * Standalone playground — compose messages and run a model without wiring an SDK. Uses the same
 * /api/playground/run the trace inspector's inline editor does. Two modes: Prompt (single run)
 * and Compare (the same messages against two model configs side by side, so a swap is a diff you
 * can read rather than a guess).
 */
type Variant = { connId: string; model: string; temp: string };
// No connection until one is loaded: every run goes through a real provider key, so there is
// nothing to fall back to when a workspace has none.
const DEFAULT_VARIANT: Variant = { connId: "", model: "gpt-4o-mini", temp: "" };

export default function PlaygroundPage() {
  const [conns, setConns] = useState<ProviderConnection[]>([]);
  const [prompts, setPrompts] = useState<SavedPrompt[]>([]);
  const [mode, setMode] = useState<"prompt" | "compare">("prompt");
  const [a, setA] = useState<Variant>({ ...DEFAULT_VARIANT });
  const [b, setB] = useState<Variant>({ ...DEFAULT_VARIANT, model: "gpt-4o" });
  const [msgs, setMsgs] = useState<PlaygroundMessage[]>([
    { role: "system", content: "You are a helpful assistant." },
    { role: "user", content: "" },
  ]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [resA, setResA] = useState<PlaygroundResult | null>(null);
  const [resB, setResB] = useState<PlaygroundResult | null>(null);

  useEffect(() => {
    api.connections().then((cs) => {
      // Legacy mock connections can no longer run — never offer one as a choice.
      const usable = cs.filter((c) => c.provider !== "mock");
      setConns(usable);
      const first = usable[0];
      if (first) {
        setA((v) => v.connId ? v : { ...v, connId: String(first.id) });
        setB((v) => v.connId ? v : { ...v, connId: String(first.id) });
      }
    }).catch(() => {});
  }, []);
  useEffect(() => { api.prompts().then(setPrompts).catch(() => {}); }, []);

  // Latest version of each named saved prompt — the useful thing to load into the composer.
  const promptOptions = useMemo(() => {
    const m = new Map<string, SavedPrompt>();
    for (const p of prompts) { const e = m.get(p.name); if (!e || p.version > e.version) m.set(p.name, p); }
    return [...m.values()];
  }, [prompts]);

  const setMsg = (i: number, patch: Partial<PlaygroundMessage>) =>
    setMsgs((ms) => ms.map((m, j) => (j === i ? { ...m, ...patch } : m)));
  const addMsg = () => setMsgs((ms) => [...ms, { role: ms[ms.length - 1]?.role === "user" ? "assistant" : "user", content: "" }]);
  const rmMsg = (i: number) => setMsgs((ms) => ms.filter((_, j) => j !== i));

  const loadPrompt = (name: string) => {
    const p = promptOptions.find((x) => x.name === name);
    if (!p) return;
    setMsgs(p.messages?.length ? p.messages : msgs);
    setA((v) => ({ ...v, model: p.model || v.model, temp: p.params?.temperature != null ? String(p.params.temperature) : v.temp }));
  };

  const runOne = (v: Variant) => api.playgroundRun({
    model: v.model,
    messages: msgs.filter((m) => m.content.trim()),
    params: v.temp.trim() !== "" && !Number.isNaN(Number(v.temp)) ? { temperature: Number(v.temp) } : {},
    connection_id: Number(v.connId),
  });

  const run = async () => {
    setBusy(true); setErr(""); setResA(null); setResB(null);
    try {
      if (mode === "prompt") { setResA(await runOne(a)); }
      else { const [ra, rb] = await Promise.all([runOne(a), runOne(b)]); setResA(ra); setResB(rb); }
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  };

  return (
    <ConsoleShell>
      <div className="cs-page" style={{ maxWidth: 1220 }}>
        <PageHero eyebrow="Debugging" title="Playground"
          sub="Run a model against an ad-hoc prompt using your own provider key. Load a saved prompt, or switch to Compare to run two models against the same messages." />

        <div className="pgx-tabs">
          <button className={`pgx-tab ${mode === "prompt" ? "on" : ""}`} onClick={() => setMode("prompt")}>Prompt</button>
          <button className={`pgx-tab ${mode === "compare" ? "on" : ""}`} onClick={() => setMode("compare")}>Compare</button>
          <div className="pgx-tabs-right">
            {promptOptions.length > 0 && (
              <label className="pgx-load"><span>Load prompt</span>
                <select defaultValue="" onChange={(e) => { loadPrompt(e.target.value); e.target.value = ""; }}>
                  <option value="" disabled>Saved prompt…</option>
                  {promptOptions.map((p) => <option key={p.name} value={p.name}>{p.name} (v{p.version})</option>)}
                </select>
              </label>
            )}
            <button className="btn btn-run" disabled={busy || !a.connId || (mode === "compare" && !b.connId)} onClick={run}>
              {busy ? "Running…" : mode === "compare" ? "Run both" : "Run"}</button>
          </div>
        </div>

        {conns.length === 0 && (
          <div className="pr-card" style={{ marginBottom: 14 }}>
            <span className="muted">No model connection yet. Runs go to your own provider with your
              own key — add one in <a href="/settings" style={{ color: "var(--accent)" }}>Settings → Model connections</a> to use the playground.</span>
          </div>
        )}

        {err && <div className="auth-err" style={{ marginBottom: 14 }}>{err}</div>}

        <div className="rp-grid">
          {/* LEFT — shared composer */}
          <div className="rp-edit">
            <VariantBar v={a} set={setA} conns={conns} tag={mode === "compare" ? "A" : undefined} />
            <div className="rp-panel-h" style={{ marginTop: 12 }}>Messages</div>
            <div className="pg-msgs">
              {msgs.map((m, i) => (
                <div key={i} className="pg-msg">
                  <div className="pg-msg-top">
                    <select value={m.role} onChange={(e) => setMsg(i, { role: e.target.value })} className="reg-sel">
                      <option value="system">system</option>
                      <option value="user">user</option>
                      <option value="assistant">assistant</option>
                    </select>
                    {msgs.length > 1 && <button className="pg-rm" onClick={() => rmMsg(i)} aria-label="Remove">×</button>}
                  </div>
                  <textarea value={m.content} rows={m.role === "system" ? 2 : 4}
                    onChange={(e) => setMsg(i, { content: e.target.value })}
                    placeholder={m.role === "user" ? "Your prompt…" : ""} />
                </div>
              ))}
            </div>
            <button className="btn btn-sm btn-ghost" onClick={addMsg} style={{ marginTop: 8 }}>+ Add message</button>
          </div>

          {/* RIGHT — output(s) */}
          <div className="rp-result">
            {mode === "compare" && <VariantBar v={b} set={setB} conns={conns} tag="B" />}
            <div className="rp-panel-h" style={{ marginTop: mode === "compare" ? 12 : 0 }}>Model output</div>
            {mode === "prompt" ? (
              <OutputPanel result={resA} model={a.model} />
            ) : (
              <div className="pgx-compare">
                <div><div className="pgx-col-tag">A · {a.model}</div><OutputPanel result={resA} model={a.model} compact /></div>
                <div><div className="pgx-col-tag">B · {b.model}</div><OutputPanel result={resB} model={b.model} compact /></div>
              </div>
            )}
          </div>
        </div>
      </div>
    </ConsoleShell>
  );
}

function VariantBar({ v, set, conns, tag }: { v: Variant; set: (u: Variant) => void; conns: ProviderConnection[]; tag?: string }) {
  return (
    <div className="pgx-varbar">
      {tag && <span className="pgx-tag">{tag}</span>}
      <label><span>Connection</span>
        <select value={v.connId} onChange={(e) => set({ ...v, connId: e.target.value })}>
          {conns.length === 0
            ? <option value="">No model connection</option>
            : conns.map((c) => <option key={c.id} value={String(c.id)}>{c.label || c.provider}</option>)}
        </select>
      </label>
      <label><span>Model</span>
        <input value={v.model} onChange={(e) => set({ ...v, model: e.target.value })} placeholder="gpt-4o-mini" style={{ width: 150 }} />
      </label>
      <label><span>Temp</span>
        <input type="number" min={0} max={2} step={0.1} value={v.temp} placeholder="—" onChange={(e) => set({ ...v, temp: e.target.value })} style={{ width: 74 }} />
      </label>
    </div>
  );
}

function OutputPanel({ result, model, compact }: { result: PlaygroundResult | null; model: string; compact?: boolean }) {
  if (!result) {
    return (
      <div className="rp-empty pgx-empty">
        <div className="pgx-run-glyph">▶</div>
        <span className="muted">{compact ? "Not run yet." : "Run a traced prompt to see the model's response."}</span>
      </div>
    );
  }
  return (
    <>
      <div className="pg-out">{result.output || <span className="muted">empty</span>}</div>
      <div className="pg-meta">
        <span className="meta-pill">{result.model || model}</span>
        <span className="meta-pill">{(result.usage?.input_tokens || 0) + (result.usage?.output_tokens || 0)} tokens</span>
        {result.latency_ms != null && <span className="meta-pill">{result.latency_ms}ms</span>}
        <span className="meta-pill">{fmtCost(estimateCost(result.model || model, result.usage?.input_tokens, result.usage?.output_tokens)) || "—"}</span>
      </div>
    </>
  );
}
