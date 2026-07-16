"use client";

import { useEffect, useState } from "react";
import { api, Connection, ReqType, ToolDef } from "@/lib/api";
import AssertionsEditor from "./AssertionsEditor";

const TYPES: { key: ReqType; label: string; kind: string }[] = [
  { key: "prompt", label: "Prompt", kind: "llm" },
  { key: "tool", label: "Tool", kind: "mcp" },
  { key: "agent", label: "Agent", kind: "agent" },
  { key: "a2a", label: "A2A", kind: "a2a" },
];

export default function RequestEditor({ req, setReq, connections }: {
  req: any; setReq: (r: any) => void; connections: Connection[];
}) {
  const type: ReqType = req.type;
  const kind = TYPES.find((t) => t.key === type)!.kind;
  const conns = connections.filter((c) => c.kind === kind);
  const conn = connections.find((c) => c.id === req.connection_id);
  const set = (patch: any) => setReq({ ...req, ...patch });

  const switchType = (t: ReqType) => {
    const k = TYPES.find((x) => x.key === t)!.kind;
    // For LLM prompts prefer a key'd provider, else the keyless mock agent (first-run friendly).
    const firstConn = k === "llm"
      ? (connections.find((c) => c.kind === "llm" && c.config?.has_key) || connections.find((c) => c.kind === "llm" && c.config?.provider === "mock") || connections.find((c) => c.kind === "llm"))
      : connections.find((c) => c.kind === k);
    const base: any = { type: t, connection_id: firstConn?.id ?? null };
    if (t === "prompt") setReq({ ...base, model: (firstConn?.config?.models || [""])[0] || "", system: "", user: "", temperature: 0.7, max_tokens: 1024 });
    else if (t === "tool") setReq({ ...base, tool: "", args: {} });
    else if (t === "a2a") setReq({ ...base, message: "", stream: false });
    else setReq({ ...base, method: "POST", path: "", headers: {}, body: null });
  };

  return (
    <>
      <div className="type-tabs">
        {TYPES.map((t) => (
          <button key={t.key} className={`type-tab ${t.key} ${type === t.key ? "on" : ""}`} onClick={() => switchType(t.key)}>
            {t.label}
          </button>
        ))}
      </div>

      <div className="editor-scroll">
        <div className="field">
          <label>Connection</label>
          <select value={req.connection_id ?? ""} onChange={(e) => set({ connection_id: e.target.value ? +e.target.value : null })}>
            <option value="">— select a {kind} connection —</option>
            {conns.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </div>

        {type === "prompt" && <PromptForm req={req} set={set} conn={conn} />}
        {type === "tool" && <ToolForm key={req._k} req={req} set={set} conn={conn} />}
        {type === "agent" && <AgentForm key={req._k} req={req} set={set} />}
        {type === "a2a" && <A2AForm req={req} set={set} conn={conn} />}

        <AssertionsEditor assertions={req.assertions || []} onChange={(a) => set({ assertions: a })} connections={connections} />
      </div>
    </>
  );
}

function PromptForm({ req, set, conn }: any) {
  const models: string[] = conn?.config?.models || [];
  return (
    <>
      <div className="field">
        <label>Model</label>
        {models.length ? (
          <select value={req.model || ""} onChange={(e) => set({ model: e.target.value })}>
            {models.map((m) => <option key={m}>{m}</option>)}
          </select>
        ) : (
          <input value={req.model || ""} onChange={(e) => set({ model: e.target.value })} placeholder="model id" />
        )}
      </div>
      <div className="field">
        <label>System <span className="hint">supports {"{{variables}}"}</span></label>
        <textarea className="mono" value={req.system || ""} onChange={(e) => set({ system: e.target.value })} rows={3} placeholder="You are a helpful assistant…" />
      </div>
      <div className="field">
        <label>User</label>
        <textarea value={req.user || ""} onChange={(e) => set({ user: e.target.value })} rows={5} placeholder="Your prompt…" />
      </div>
      <div className="row2">
        <div className="field"><label>Temperature</label><input type="number" step="0.1" min="0" max="2" value={req.temperature ?? 0.7} onChange={(e) => { const v = parseFloat(e.target.value); set({ temperature: Number.isNaN(v) ? 0.7 : v }); }} /></div>
        <div className="field"><label>Max tokens</label><input type="number" value={req.max_tokens ?? 1024} onChange={(e) => set({ max_tokens: parseInt(e.target.value || "0") || 0 })} /></div>
      </div>
    </>
  );
}

function ToolForm({ req, set, conn }: any) {
  const [tools, setTools] = useState<ToolDef[]>([]);
  const [rawMode, setRawMode] = useState(false);
  const [rawText, setRawText] = useState("{}");
  const [err, setErr] = useState("");

  useEffect(() => {
    if (!conn) { setTools([]); return; }
    api.tools(conn.id).then((r) => setTools(r.tools)).catch(() => setTools([]));
  }, [conn?.id]);

  const tool = tools.find((t) => t.name === req.tool);
  const props: Record<string, any> = tool?.input_schema?.properties || {};
  const required: string[] = tool?.input_schema?.required || [];
  const setArg = (k: string, v: any) => set({ args: { ...req.args, [k]: v } });

  return (
    <>
      <div className="field">
        <label>Tool</label>
        <select value={req.tool || ""} onChange={(e) => set({ tool: e.target.value, args: {} })} disabled={!tools.length}>
          <option value="">{tools.length ? "— select a tool —" : "connect an MCP server first"}</option>
          {tools.map((t) => <option key={t.name} value={t.name}>{t.name}</option>)}
        </select>
      </div>

      {tool && (
        <>
          {tool.description && <div className="tool-desc">{tool.description}</div>}
          <div className="field">
            <label>Arguments
              <button className="btn btn-ghost btn-sm" style={{ marginLeft: "auto" }}
                onClick={() => { if (!rawMode) setRawText(JSON.stringify(req.args || {}, null, 2)); setRawMode(!rawMode); setErr(""); }}>
                {rawMode ? "Form" : "{ } JSON"}
              </button>
            </label>
            {rawMode ? (
              <>
                <textarea className="mono" rows={7} value={rawText}
                  onChange={(e) => { setRawText(e.target.value); try { set({ args: JSON.parse(e.target.value) }); setErr(""); } catch { setErr("Invalid JSON"); } }} />
                {err && <span className="hint" style={{ color: "var(--err)" }}>{err}</span>}
              </>
            ) : (
              Object.keys(props).length === 0 ? <div className="jv-empty">This tool takes no arguments.</div> :
              Object.entries(props).map(([k, spec]: any) => (
                <div className="field" key={k} style={{ marginBottom: 10 }}>
                  <label>{k}{required.includes(k) ? " *" : ""} <span className="hint">{spec.type}{spec.description ? ` — ${spec.description}` : ""}</span></label>
                  <ArgField spec={spec} value={req.args?.[k]} onChange={(v) => setArg(k, v)} />
                </div>
              ))
            )}
          </div>
        </>
      )}
    </>
  );
}

function ArgField({ spec, value, onChange }: { spec: any; value: any; onChange: (v: any) => void }) {
  const t = spec.type;
  if (t === "boolean") return <input type="checkbox" checked={!!value} onChange={(e) => onChange(e.target.checked)} style={{ width: 18, height: 18 }} />;
  if (t === "number" || t === "integer") return <input type="number" value={value ?? ""} onChange={(e) => onChange(e.target.value === "" ? undefined : Number(e.target.value))} />;
  if (t === "array" || t === "object") {
    return <textarea className="mono" rows={3} value={typeof value === "string" ? value : JSON.stringify(value ?? (t === "array" ? [] : {}), null, 2)}
      onChange={(e) => { try { onChange(JSON.parse(e.target.value)); } catch { onChange(e.target.value); } }} />;
  }
  return <input value={value ?? ""} onChange={(e) => onChange(e.target.value)} placeholder={spec.default != null ? String(spec.default) : ""} />;
}

function A2AForm({ req, set, conn }: any) {
  const [card, setCard] = useState<any>(null);
  const [err, setErr] = useState("");
  useEffect(() => { setCard(null); setErr(""); if (conn) api.agentCard(conn.id).then((r) => setCard(r.card)).catch((e) => setErr(String(e.message || e))); }, [conn?.id]);
  return (
    <>
      {conn && (
        <div className="tool-desc">
          {card ? <><b>{card.name}</b> <span className="hint">A2A {card._version}</span>{card.description ? <div>{card.description}</div> : null}
            {Array.isArray(card.skills) && card.skills.length ? <div className="hint">skills: {card.skills.map((s: any) => s.name || s.id).join(", ")}</div> : null}</>
            : err ? <span className="hint" style={{ color: "var(--err)" }}>no agent card ({err})</span> : <span className="hint">discovering agent card…</span>}
        </div>
      )}
      <div className="field">
        <label>Message <span className="hint">supports {"{{variables}}"}</span></label>
        <textarea value={req.message || ""} onChange={(e) => set({ message: e.target.value })} rows={5} placeholder="Ask the agent…" />
      </div>
      <div className="field">
        <label style={{ gap: 6 }}><input type="checkbox" checked={!!req.stream} onChange={(e) => set({ stream: e.target.checked })} /> stream (message/stream)</label>
      </div>
    </>
  );
}

function AgentForm({ req, set }: any) {
  // Local text buffers so invalid-mid-edit JSON doesn't revert the field; the parent remounts
  // this form (via key={req._k}) when a different request is loaded, resetting the buffers.
  const [headersText, setHeadersText] = useState(() => (Object.keys(req.headers || {}).length ? JSON.stringify(req.headers, null, 2) : ""));
  const [bodyText, setBodyText] = useState(() => (req.body != null ? JSON.stringify(req.body, null, 2) : ""));
  return (
    <>
      <div className="field">
        <label>Request</label>
        <div className="row3">
          <select value={req.method || "POST"} onChange={(e) => set({ method: e.target.value })} style={{ width: 100 }}>
            {["GET", "POST", "PUT", "PATCH", "DELETE"].map((m) => <option key={m}>{m}</option>)}
          </select>
          <input value={req.path || ""} onChange={(e) => set({ path: e.target.value })} placeholder="/api/…" className="mono" />
        </div>
      </div>
      <div className="field">
        <label>Headers <span className="hint">JSON</span></label>
        <textarea className="mono" rows={3} value={headersText}
          onChange={(e) => { setHeadersText(e.target.value); try { set({ headers: e.target.value.trim() ? JSON.parse(e.target.value) : {} }); } catch {} }} placeholder='{ "Authorization": "Bearer …" }' />
      </div>
      <div className="field">
        <label>Body <span className="hint">JSON</span>
          <label style={{ marginLeft: "auto", fontWeight: 400, gap: 6 }}>
            <input type="checkbox" checked={!!req.stream} onChange={(e) => set({ stream: e.target.checked })} /> stream (SSE)
          </label>
        </label>
        <textarea className="mono" rows={6} value={bodyText}
          onChange={(e) => { setBodyText(e.target.value); try { set({ body: e.target.value.trim() ? JSON.parse(e.target.value) : null }); } catch {} }}
          placeholder='{ "input": … }' />
      </div>
    </>
  );
}
