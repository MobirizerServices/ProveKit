"use client";

import { useEffect, useMemo, useState } from "react";
import { api, PlaygroundResult, ProviderConnection, TraceSpan } from "@/lib/api";
import { estimateCost, fmtCost } from "@/lib/cost";
import { parseMessages } from "@/components/TraceDetail";

interface Msg { role: string; content: string }
const ROLES = ["system", "user", "assistant"];

// Seed an editable message list from a captured LLM span's input.
function seedMessages(span: TraceSpan): Msg[] {
  const parsed = parseMessages(span.request?.input);
  if (parsed && parsed.length) return parsed.map((m) => ({ role: m.role, content: m.content }));
  const raw = span.request?.input;
  const content = typeof raw === "string" ? raw : raw == null ? "" : JSON.stringify(raw, null, 2);
  return [{ role: "user", content }];
}

// Find {{variable}} placeholders across all messages so they can be edited as fields.
function findVars(msgs: Msg[]): string[] {
  const set = new Set<string>();
  const re = /\{\{\s*([\w.]+)\s*\}\}/g;
  for (const m of msgs) { let x; while ((x = re.exec(m.content))) set.add(x[1]); }
  return [...set];
}

// The interactive playground: edit a captured LLM call's prompt / model / params / variables and
// re-run it against a provider connection (or the keyless mock), diffing the new output. When a
// traceId is present, "Replay flow" forks the whole trace at this span and re-runs downstream.
export default function Playground({ span, traceId, onClose }: { span: TraceSpan; traceId?: string; onClose: () => void }) {
  const [msgs, setMsgs] = useState<Msg[]>(() => seedMessages(span));
  const [model, setModel] = useState(span.request?.model || "gpt-4o");
  const p = span.result?.meta?.params || {};
  const [temperature, setTemperature] = useState<string>(p.temperature != null ? String(p.temperature) : "");
  const [maxTokens, setMaxTokens] = useState<string>(p.max_tokens != null ? String(p.max_tokens) : "512");
  const [conns, setConns] = useState<ProviderConnection[]>([]);
  const [conn, setConn] = useState<string>("mock"); // "mock" or a connection id (string)
  const [vars, setVars] = useState<Record<string, string>>({});
  const [result, setResult] = useState<PlaygroundResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    api.connections().then((cs) => {
      setConns(cs);
      const real = cs.find((c) => c.provider !== "mock");
      if (real) setConn(String(real.id));
    }).catch(() => {});
  }, []);

  const varNames = useMemo(() => findVars(msgs), [msgs]);
  // Fill any newly-detected variables with a blank default without clobbering existing edits.
  useEffect(() => {
    setVars((v) => { const n = { ...v }; for (const k of varNames) if (!(k in n)) n[k] = ""; return n; });
  }, [varNames]);

  const substitute = (text: string) =>
    text.replace(/\{\{\s*([\w.]+)\s*\}\}/g, (_, k) => (vars[k] ?? `{{${k}}}`));

  const payload = () => {
    const params: Record<string, any> = { max_tokens: Number(maxTokens) || 512 };
    if (temperature !== "") params.temperature = Number(temperature);
    return {
      model, messages: msgs.map((m) => ({ role: m.role, content: substitute(m.content) })),
      params, from_span_id: span.span_id,
      ...(conn === "mock" ? { provider: "mock" } : { connection_id: Number(conn) }),
    };
  };

  const run = async () => {
    setErr(""); setBusy(true); setResult(null);
    try {
      setResult(await api.playgroundRun(payload()));
    } catch (e: any) { setErr(String(e.message || e)); } finally { setBusy(false); }
  };

  const replay = async () => {
    if (!traceId) return;
    setErr(""); setBusy(true);
    try {
      const r = await api.replay({ ...payload(), origin_trace_id: traceId, fork_span_id: span.span_id });
      // open the new branch (deep-link handles selection); it renders with per-node replay badges
      window.location.href = `/traces?trace=${encodeURIComponent(r.new_trace_id)}`;
    } catch (e: any) { setErr(String(e.message || e)); setBusy(false); }
  };

  const origOut = span.result?.text || "";
  const origUsage = span.result?.meta?.usage || {};
  const origCost = fmtCost(estimateCost(span.request?.model, origUsage.input_tokens, origUsage.output_tokens));
  const newCost = result ? fmtCost(estimateCost(result.model, result.usage.input_tokens, result.usage.output_tokens)) : null;

  const setMsg = (i: number, patch: Partial<Msg>) =>
    setMsgs((ms) => ms.map((m, j) => (j === i ? { ...m, ...patch } : m)));

  return (
    <div style={overlay}>
      <div style={header}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
          <span style={badge}>PLAYGROUND</span>
          <span style={{ fontSize: 13, fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {span.label}
          </span>
          <span className="muted" style={{ fontSize: 11.5 }}>edit &amp; re-run this call with real data</span>
        </div>
        <button className="btn btn-sm btn-ghost" onClick={onClose}>✕ Close</button>
      </div>

      <div style={body}>
        {/* left: editor */}
        <div style={{ display: "flex", flexDirection: "column", gap: 12, overflowY: "auto", paddingRight: 4 }}>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "flex-end" }}>
            <Field lbl="Connection">
              <select value={conn} onChange={(e) => setConn(e.target.value)} style={{ ...input, width: 190 }}>
                <option value="mock">Mock (no key)</option>
                {conns.filter((c) => c.provider !== "mock").map((c) => (
                  <option key={c.id} value={String(c.id)}>{c.label} · {c.provider}</option>
                ))}
              </select>
            </Field>
            <Field lbl="Model"><input value={model} onChange={(e) => setModel(e.target.value)} style={{ ...input, width: 170 }} /></Field>
            <Field lbl="Temp"><input value={temperature} onChange={(e) => setTemperature(e.target.value)} placeholder="—" style={{ ...input, width: 64 }} /></Field>
            <Field lbl="Max tok"><input value={maxTokens} onChange={(e) => setMaxTokens(e.target.value)} style={{ ...input, width: 72 }} /></Field>
          </div>

          {conn === "mock" && (
            <div className="muted" style={{ fontSize: 11.5 }}>
              Using the keyless mock model — add a real provider key in <span className="mono">Settings → Model connections</span> to run against OpenAI/Anthropic.
            </div>
          )}

          {varNames.length > 0 && (
            <div>
              <div style={secLbl}>Variables ({varNames.length})</div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: 8 }}>
                {varNames.map((k) => (
                  <label key={k} style={{ fontSize: 12 }}>
                    <span className="mono muted" style={{ fontSize: 11 }}>{k}</span>
                    <input value={vars[k] ?? ""} onChange={(e) => setVars((v) => ({ ...v, [k]: e.target.value }))}
                      style={{ ...input, width: "100%", marginTop: 3 }} />
                  </label>
                ))}
              </div>
            </div>
          )}

          <div>
            <div style={secLbl}>Messages</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {msgs.map((m, i) => (
                <div key={i} style={{ border: "1px solid var(--border)", borderRadius: 8, overflow: "hidden" }}>
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "4px 8px", background: "var(--bg-2)" }}>
                    <select value={m.role} onChange={(e) => setMsg(i, { role: e.target.value })}
                      style={{ ...input, padding: "2px 6px", fontSize: 11 }}>
                      {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
                    </select>
                    {msgs.length > 1 && <button className="btn btn-sm btn-ghost" onClick={() => setMsgs((ms) => ms.filter((_, j) => j !== i))}>✕</button>}
                  </div>
                  <textarea value={m.content} onChange={(e) => setMsg(i, { content: e.target.value })}
                    style={{ ...input, border: "none", borderRadius: 0, width: "100%", minHeight: 70, resize: "vertical", fontFamily: "var(--font-mono)", fontSize: 12 }} />
                </div>
              ))}
              <button className="btn btn-sm btn-ghost" style={{ alignSelf: "flex-start" }}
                onClick={() => setMsgs((ms) => [...ms, { role: "user", content: "" }])}>+ message</button>
            </div>
          </div>

          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <button className="btn" onClick={run} disabled={busy}>{busy ? "Running…" : "▶ Run"}</button>
            {traceId && (
              <button className="btn btn-ghost" onClick={replay} disabled={busy}
                title="Fork the whole trace here and re-run downstream calls with this edit"
                style={{ borderColor: "var(--accent)", color: "var(--accent)" }}>⑂ Replay flow</button>
            )}
          </div>
          <div className="muted" style={{ fontSize: 11 }}>
            <b>Run</b> re-runs just this call. <b>Replay flow</b> forks the trace here and threads
            the new output through downstream calls — opens as a new branch.
          </div>
          {err && <div style={errBox}>{err}</div>}
        </div>

        {/* right: original vs new */}
        <div style={{ display: "flex", flexDirection: "column", gap: 12, overflowY: "auto" }}>
          <Panel title="Original" meta={`${(origUsage.input_tokens || 0)}→${(origUsage.output_tokens || 0)} tok${origCost ? ` · ${origCost}` : ""} · ${span.duration_ms}ms`}>
            {origOut || <span className="muted">—</span>}
          </Panel>
          <Panel title="New" accent
            meta={result ? `${result.usage.input_tokens}→${result.usage.output_tokens} tok${newCost ? ` · ${newCost}` : ""} · ${result.latency_ms}ms · ${result.provider}` : ""}>
            {busy ? <span className="muted">Running…</span> : result ? result.output : <span className="muted">Edit the prompt and press Run.</span>}
          </Panel>
        </div>
      </div>
    </div>
  );
}

function Field({ lbl, children }: { lbl: string; children: React.ReactNode }) {
  return <div><div className="muted" style={{ fontSize: 11, marginBottom: 3 }}>{lbl}</div>{children}</div>;
}
function Panel({ title, meta, accent, children }: { title: string; meta?: string; accent?: boolean; children: React.ReactNode }) {
  return (
    <div style={{ border: `1px solid ${accent ? "var(--accent)" : "var(--border)"}`, borderRadius: 10, overflow: "hidden" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "6px 10px", background: "var(--bg-2)" }}>
        <span style={{ fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.4, color: accent ? "var(--accent)" : "var(--muted)" }}>{title}</span>
        {meta && <span className="muted mono" style={{ fontSize: 10.5 }}>{meta}</span>}
      </div>
      <div style={{ padding: 12, fontSize: 13, whiteSpace: "pre-wrap", wordBreak: "break-word", minHeight: 60 }}>{children}</div>
    </div>
  );
}

const overlay: React.CSSProperties = {
  position: "absolute", inset: 0, zIndex: 20, background: "var(--panel)",
  display: "flex", flexDirection: "column", borderRadius: 10,
};
const header: React.CSSProperties = {
  display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10,
  padding: "10px 14px", borderBottom: "1px solid var(--border)",
};
const body: React.CSSProperties = {
  flex: 1, minHeight: 0, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, padding: 14,
};
const badge: React.CSSProperties = {
  fontSize: 9.5, fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.4,
  padding: "2px 7px", borderRadius: 4, color: "var(--accent)", border: "1px solid var(--accent)",
};
const secLbl: React.CSSProperties = { fontSize: 11, textTransform: "uppercase", letterSpacing: 0.4, color: "var(--muted)", marginBottom: 6 };
const input: React.CSSProperties = { background: "var(--panel-2)", color: "var(--text)", border: "1px solid var(--border-strong)", borderRadius: 8, padding: "7px 10px", fontSize: 13 };
const errBox: React.CSSProperties = { background: "color-mix(in srgb, var(--red) 12%, transparent)", border: "1px solid var(--red)", color: "var(--red)", borderRadius: 8, padding: "8px 12px", fontSize: 12.5 };
