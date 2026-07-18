"use client";

import { useEffect, useState } from "react";
import { api, Connection, ToolDef, PromptT } from "@/lib/api";
import JsonView from "../JsonView";

export default function NodeInspector({ node, connections, runStep, onChange, onTitle, onClose }: {
  node: any; connections: Connection[]; runStep: any;
  onChange: (config: any) => void; onTitle: (title: string) => void; onClose: () => void;
}) {
  const t: string = node.data.nodeType;
  const cfg = node.data.config || {};
  const set = (patch: any) => onChange({ ...cfg, ...patch });
  const kind = t === "prompt" ? "llm" : t === "tool" ? "mcp" : t === "agent" ? "agent" : null;
  const conns = kind ? connections.filter((c) => c.kind === kind) : [];
  const conn = connections.find((c) => c.id === cfg.connection_id);
  const [tools, setTools] = useState<ToolDef[]>([]);
  useEffect(() => { if (t === "tool" && conn) api.tools(conn.id).then((r) => setTools(r.tools)).catch(() => setTools([])); }, [t, conn?.id]);
  const [prompts, setPrompts] = useState<PromptT[]>([]);
  useEffect(() => { if (t === "prompt") api.prompts().then(setPrompts).catch(() => setPrompts([])); }, [t]);
  const regPrompt = prompts.find((p) => p.key === cfg.prompt_key);
  // Local buffers for JSON fields so typing doesn't reformat under the caret. The parent keys this
  // component by node id, so switching nodes remounts and reseeds these from the node's config.
  const [jbuf, setJbuf] = useState<Record<string, string>>(() => ({ sample: json(cfg.sample), args: json(cfg.args), body: json(cfg.body) }));
  const setJson = (field: string, val: string) => { setJbuf((b) => ({ ...b, [field]: val })); set({ [field]: parse(val) }); };

  return (
    <aside className="node-insp">
      <div className="ni-head">
        <div><div className="ni-eyebrow">{t}</div><div className="ni-title">{node.data.title || t}</div></div>
        <button className="ni-x" onClick={onClose} aria-label="Close inspector">×</button>
      </div>
      <div className="ni-body">
        <Field label="Title"><input value={node.data.title || ""} onChange={(e) => onTitle(e.target.value)} /></Field>

        {kind && (
          <Field label="Connection">
            <select value={cfg.connection_id ?? ""} onChange={(e) => set({ connection_id: e.target.value ? +e.target.value : null })}>
              <option value="">— select —</option>
              {conns.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </Field>
        )}

        {t === "input" && <Field label="Sample input" hint="test data for this flow"><textarea className="mono" rows={5} value={jbuf.sample} onChange={(e) => setJson("sample", e.target.value)} /></Field>}

        {t === "prompt" && <>
          <Field label="Model">{conn?.config?.models?.length ? <select value={cfg.model || ""} onChange={(e) => set({ model: e.target.value })}>{conn.config.models.map((m: string) => <option key={m}>{m}</option>)}</select> : <input value={cfg.model || ""} onChange={(e) => set({ model: e.target.value })} />}</Field>
          <Field label="System prompt" hint="from Prompt Registry — kept in sync">
            <select value={cfg.prompt_key || ""} onChange={(e) => set({ prompt_key: e.target.value || undefined })}>
              <option value="">— inline (below) —</option>
              {prompts.map((p) => <option key={p.key} value={p.key}>{p.name} ({p.key})</option>)}
            </select>
          </Field>
          {regPrompt
            ? <div className="ni-reg">{regPrompt.content}</div>
            : <Field label="System"><textarea className="mono" rows={3} value={cfg.system || ""} onChange={(e) => set({ system: e.target.value })} /></Field>}
          <Field label="User" hint="use {{input.x}} or {{nodeId.field}}"><textarea rows={4} value={cfg.user || ""} onChange={(e) => set({ user: e.target.value })} /></Field>
          <Field label="Tools" hint="MCP servers this model may call">
            <NodeTools cfg={cfg} set={set} mcps={connections.filter((c) => c.kind === "mcp")} />
          </Field>
        </>}

        {t === "tool" && <>
          <Field label="Tool"><select value={cfg.tool || ""} onChange={(e) => set({ tool: e.target.value })} disabled={!tools.length}><option value="">{tools.length ? "— select —" : "connect MCP first"}</option>{tools.map((x) => <option key={x.name}>{x.name}</option>)}</select></Field>
          <Field label="Arguments" hint="JSON · {{refs}} allowed"><textarea className="mono" rows={4} value={jbuf.args} onChange={(e) => setJson("args", e.target.value)} /></Field>
        </>}

        {t === "agent" && <>
          <Field label="Method / Path"><div style={{ display: "flex", gap: 6 }}><select value={cfg.method || "POST"} onChange={(e) => set({ method: e.target.value })} style={{ width: 90 }}>{["GET", "POST", "PUT", "DELETE"].map((m) => <option key={m}>{m}</option>)}</select><input className="mono" value={cfg.path || ""} onChange={(e) => set({ path: e.target.value })} placeholder="/api/…" /></div></Field>
          <Field label="Body" hint="JSON"><textarea className="mono" rows={4} value={jbuf.body} onChange={(e) => setJson("body", e.target.value)} /></Field>
        </>}

        {t === "condition" && <>
          <Field label="Left" hint="{{nodeId.field}}"><input className="mono" value={cfg.left || ""} onChange={(e) => set({ left: e.target.value })} /></Field>
          <Field label="Operator"><select value={cfg.op || "=="} onChange={(e) => set({ op: e.target.value })}>{["==", "!=", "contains", ">", "<", "exists"].map((o) => <option key={o}>{o}</option>)}</select></Field>
          <Field label="Right"><input className="mono" value={cfg.right || ""} onChange={(e) => set({ right: e.target.value })} /></Field>
        </>}

        {t === "output" && <Field label="Value" hint="{{ref}} or text"><textarea className="mono" rows={3} value={cfg.value || ""} onChange={(e) => set({ value: e.target.value })} /></Field>}

        {runStep && (runStep.status === "ok" || runStep.status === "error") && (
          <div className="ni-run">
            <div className="ni-run-h">Last run {runStep.duration_ms != null && <span>{runStep.duration_ms} ms</span>}{runStep.branch && <span className="fn-branch">→ {runStep.branch}</span>}</div>
            {runStep.error ? <div className="resp-error">{runStep.error}</div> : <JsonView data={runStep.output} />}
          </div>
        )}
      </div>
    </aside>
  );
}

/** Attach MCP servers to a prompt node's model, mirroring the console's Tools panel.
 *  Same request shape the backend reads: tools: [{connection_id, execute?}]. */
function NodeTools({ cfg, set, mcps }: { cfg: any; set: (p: any) => void; mcps: Connection[] }) {
  const attached: any[] = cfg.tools || [];
  const free = mcps.filter((c) => !attached.some((a) => a.connection_id === c.id));
  const remove = (i: number) => {
    const tools = attached.filter((_, n) => n !== i);
    set({ tools: tools.length ? tools : undefined });
  };
  if (!mcps.length) return <div className="hint">No MCP connections yet.</div>;
  return (
    <>
      {attached.map((a, i) => (
        <div key={a.connection_id ?? i} style={{ display: "flex", gap: 6, alignItems: "center", marginBottom: 4 }}>
          <code style={{ flex: 1 }}>{mcps.find((c) => c.id === a.connection_id)?.name || a.connection_id}</code>
          <label className="hint" style={{ display: "flex", gap: 4, alignItems: "center" }}>
            <input type="checkbox" checked={a.execute === false}
                   onChange={(e) => set({ tools: attached.map((x, n) => (n === i ? { ...x, execute: e.target.checked ? false : undefined } : x)) })} />
            dry run
          </label>
          <button className="btn btn-ghost btn-sm" onClick={() => remove(i)} aria-label="Remove this MCP server">✕</button>
        </div>
      ))}
      {free.length > 0 && (
        <select value="" onChange={(e) => e.target.value && set({ tools: [...attached, { connection_id: +e.target.value }] })}>
          <option value="">+ attach an MCP server…</option>
          {free.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
      )}
    </>
  );
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return <div className="field"><label>{label}{hint && <span className="hint">{hint}</span>}</label>{children}</div>;
}
function json(v: any) { return v == null ? "" : typeof v === "string" ? v : JSON.stringify(v, null, 2); }
function parse(s: string) { try { return JSON.parse(s); } catch { return s; } }
