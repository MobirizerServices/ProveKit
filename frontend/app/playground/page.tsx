"use client";

import { useEffect, useState } from "react";
import { api, PlaygroundMessage, PlaygroundResult, ProviderConnection } from "@/lib/api";
import { estimateCost, fmtCost } from "@/lib/cost";
import ConsoleShell from "@/components/ConsoleShell";

/**
 * Standalone playground — compose messages and run a model without wiring an SDK. Uses the same
 * /api/playground/run the trace inspector's inline editor does; the difference is only that you
 * start from a blank prompt rather than a captured span.
 */
export default function PlaygroundPage() {
  const [conns, setConns] = useState<ProviderConnection[]>([]);
  const [connId, setConnId] = useState("mock");
  const [model, setModel] = useState("gpt-4o-mini");
  const [temp, setTemp] = useState("");
  const [msgs, setMsgs] = useState<PlaygroundMessage[]>([
    { role: "system", content: "You are a helpful assistant." },
    { role: "user", content: "" },
  ]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [result, setResult] = useState<PlaygroundResult | null>(null);

  useEffect(() => { api.connections().then(setConns).catch(() => {}); }, []);

  const setMsg = (i: number, patch: Partial<PlaygroundMessage>) =>
    setMsgs((ms) => ms.map((m, j) => (j === i ? { ...m, ...patch } : m)));
  const addMsg = () => setMsgs((ms) => [...ms, { role: ms[ms.length - 1]?.role === "user" ? "assistant" : "user", content: "" }]);
  const rmMsg = (i: number) => setMsgs((ms) => ms.filter((_, j) => j !== i));

  const run = async () => {
    setBusy(true); setErr(""); setResult(null);
    try {
      const t = temp.trim();
      const r = await api.playgroundRun({
        model,
        messages: msgs.filter((m) => m.content.trim()),
        params: t !== "" && !Number.isNaN(Number(t)) ? { temperature: Number(t) } : {},
        ...(connId === "mock" ? { provider: "mock" } : { connection_id: Number(connId) }),
      });
      setResult(r);
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  };

  return (
    <ConsoleShell>
      <div className="cs-page" style={{ maxWidth: 1180 }}>
        <div className="page-head" style={{ marginBottom: 18 }}>
          <div>
            <div className="page-eyebrow">Debugging</div>
            <h1>Playground</h1>
            <p>Run a model against an ad-hoc prompt. Use Mock to try it without a key, or pick a
              connection from Settings → Model connections.</p>
          </div>
        </div>

        <div className="rp-bar" style={{ marginBottom: 16 }}>
          <label><span>Connection</span>
            <select value={connId} onChange={(e) => setConnId(e.target.value)}>
              <option value="mock">Mock (no key)</option>
              {conns.map((c) => <option key={c.id} value={String(c.id)}>{c.label || c.provider}</option>)}
            </select>
          </label>
          <label><span>Model</span>
            <input value={model} onChange={(e) => setModel(e.target.value)} placeholder="gpt-4o-mini"
              style={{ background: "var(--bg)", color: "var(--text)", border: "1px solid var(--border-2)", borderRadius: "var(--r-sm)", padding: "8px 10px", fontSize: 12.5, width: 160 }} />
          </label>
          <label><span>Temperature</span>
            <input type="number" min={0} max={2} step={0.1} value={temp} placeholder="—"
              onChange={(e) => setTemp(e.target.value)}
              style={{ background: "var(--bg)", color: "var(--text)", border: "1px solid var(--border-2)", borderRadius: "var(--r-sm)", padding: "8px 10px", fontSize: 12.5, width: 90 }} />
          </label>
          <button className="btn btn-run" disabled={busy} onClick={run}>{busy ? "Running…" : "Run"}</button>
        </div>

        {err && <div className="auth-err" style={{ marginBottom: 14 }}>{err}</div>}

        <div className="rp-grid">
          <div className="rp-edit">
            <div className="rp-panel-h">Messages</div>
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

          <div className="rp-result">
            <div className="rp-panel-h">Output</div>
            {!result ? (
              <div className="rp-empty"><span className="muted">Run to see the model&apos;s response.</span></div>
            ) : (
              <>
                <div className="pg-out">{result.output || <span className="muted">empty</span>}</div>
                <div className="pg-meta">
                  <span className="meta-pill">{result.model || model}</span>
                  <span className="meta-pill">{(result.usage?.input_tokens || 0) + (result.usage?.output_tokens || 0)} tokens</span>
                  {result.latency_ms != null && <span className="meta-pill">{result.latency_ms}ms</span>}
                  <span className="meta-pill">{fmtCost(estimateCost(result.model || model, result.usage?.input_tokens, result.usage?.output_tokens)) || "—"}</span>
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    </ConsoleShell>
  );
}
