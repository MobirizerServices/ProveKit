"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  ReactFlow, ReactFlowProvider, Background, BackgroundVariant, Controls, MiniMap, Panel,
  useNodesState, useEdgesState, addEdge, useReactFlow,
  type Node as RFNode, type Edge as RFEdge, type Connection,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { api, Connection as Conn, FlowSummary, FlowEvent } from "@/lib/api";
import TopNav from "@/components/TopNav";
import { FlowNode } from "@/components/flow/FlowNode";
import { FlowEdge } from "@/components/flow/FlowEdge";
import NodeInspector from "@/components/flow/NodeInspector";

const nodeTypes = { fnode: FlowNode };
const edgeTypes = { add: FlowEdge };
const COLOR: Record<string, string> = { input: "muted", prompt: "prompt", tool: "tool", agent: "agent", condition: "purple", output: "ok" };
const PALETTE = ["prompt", "tool", "agent", "condition", "output"];
const uid = () => (typeof crypto !== "undefined" && crypto.randomUUID ? crypto.randomUUID().slice(0, 6) : String(Math.floor(Math.random() * 1e6)));

// Starter templates so a new flow isn't a blank canvas.
const N = (id: string, type: string, title: string, x: number, y: number, config: any = {}) => ({ id, type, position: { x, y }, data: { title }, config });
const E = (s: string, t: string, branch?: string) => ({ id: `e-${s}-${t}`, source: s, target: t, ...(branch ? { condition: { branch } } : {}) });
const TEMPLATES = [
  { id: "blank", name: "Blank canvas", desc: "Start from an input node", icon: "▢",
    nodes: [N("input", "input", "Input", 80, 200)], edges: [] },
  { id: "prompt", name: "Prompt → Output", desc: "Send a prompt, return its text", icon: "✨",
    nodes: [N("input", "input", "Input", 60, 200), N("p", "prompt", "Prompt", 340, 200, { user: "{{input.text}}" }), N("out", "output", "Output", 640, 200, { value: "{{p.text}}" })],
    edges: [E("input", "p"), E("p", "out")] },
  { id: "tool", name: "Tool → Branch", desc: "Call a tool, branch on the result", icon: "🔧",
    nodes: [N("input", "input", "Input", 40, 220), N("t", "tool", "Tool", 320, 220), N("c", "condition", "Check", 600, 220, { left: "{{t.status}}", op: "==", right: "ok" }), N("y", "output", "Yes", 880, 130, { value: "yes" }), N("n", "output", "No", 880, 320, { value: "no" })],
    edges: [E("input", "t"), E("t", "c"), E("c", "y", "true"), E("c", "n", "false")] },
];

function toRF(flow: any): { nodes: RFNode[]; edges: RFEdge[] } {
  return {
    nodes: (flow.nodes || []).map((n: any) => ({
      id: n.id, type: "fnode", position: n.position || { x: 0, y: 0 },
      data: { title: n.data?.title, nodeType: n.type, color: COLOR[n.type] || "muted", config: n.config || {} },
    })),
    edges: (flow.edges || []).map((e: any) => ({
      id: e.id, source: e.source, target: e.target,
      sourceHandle: e.condition?.branch || undefined, label: e.condition?.branch,
      data: {}, type: "add",
    })),
  };
}
function toGraph(nodes: RFNode[], edges: RFEdge[]) {
  return {
    nodes: nodes.map((n) => ({ id: n.id, type: (n.data as any).nodeType, position: { x: Math.round(n.position.x), y: Math.round(n.position.y) }, data: { title: (n.data as any).title }, config: (n.data as any).config || {} })),
    edges: edges.map((e) => ({ id: e.id, source: e.source, target: e.target, condition: e.sourceHandle ? { branch: e.sourceHandle } : undefined })),
  };
}

function Editor() {
  const [flows, setFlows] = useState<FlowSummary[]>([]);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [connections, setConnections] = useState<Conn[]>([]);
  const [rfNodes, setRfNodes, onNodesChange] = useNodesState<RFNode>([]);
  const [rfEdges, setRfEdges, onEdgesChange] = useEdgesState<RFEdge>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [baseline, setBaseline] = useState("");
  const [debugMode, setDebugMode] = useState(false);
  const [breakpoints, setBreakpoints] = useState<Set<string>>(new Set());
  const [runByNode, setRunByNode] = useState<Record<string, string>>({});
  const [stepsById, setStepsById] = useState<Record<string, any>>({});
  const [runStatus, setRunStatus] = useState("idle");
  const [runId, setRunId] = useState("");
  const [pausedNode, setPausedNode] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [tplPicker, setTplPicker] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const { screenToFlowPosition, fitView } = useReactFlow();
  const nodesRef = useRef<RFNode[]>([]); nodesRef.current = rfNodes;
  const edgesRef = useRef<RFEdge[]>([]); edgesRef.current = rfEdges;
  const actionsRef = useRef<any>({});

  const flash = (t: string) => { setToast(t); setTimeout(() => setToast(null), 2200); };
  const loadFlows = () => api.flows().then((fs) => {
    setFlows(fs);
    const q = typeof window !== "undefined" ? new URLSearchParams(window.location.search).get("flow") : null;
    const wanted = q && fs.some((f) => String(f.id) === q) ? Number(q) : null;
    setActiveId((id) => wanted ?? id ?? fs[0]?.id ?? null);
  });

  useEffect(() => { api.connections().then(setConnections).catch(() => {}); loadFlows(); }, []);
  // Abort any in-flight run stream on unmount.
  useEffect(() => () => abortRef.current?.abort(), []);
  useEffect(() => {
    if (!activeId) return;
    abortRef.current?.abort();  // stop a run still streaming from the previous flow
    setRunning(false);
    setSelected(null); setRunByNode({}); setStepsById({}); setRunStatus("idle"); setBreakpoints(new Set());
    let cancelled = false; let timer: any;
    api.getFlow(activeId).then((f) => {
      if (cancelled) return;  // ignore an out-of-order response for a flow we've since left
      const { nodes, edges } = toRF(f);
      setRfNodes(nodes); setRfEdges(edges);
      setBaseline(JSON.stringify(toGraph(nodes, edges)));
      timer = setTimeout(() => { if (!cancelled) fitView({ padding: 0.2, duration: 0 }); }, 60);
    }).catch(() => {});
    return () => { cancelled = true; clearTimeout(timer); };
  }, [activeId]);

  // breakpoint toggle from node gutter
  useEffect(() => {
    const h = (ev: Event) => { const id = (ev as CustomEvent).detail as string; setBreakpoints((p) => { const s = new Set(p); s.has(id) ? s.delete(id) : s.add(id); return s; }); };
    document.addEventListener("agm-flow-bp", h); return () => document.removeEventListener("agm-flow-bp", h);
  }, []);

  // inject run/debug overlay into node data (also re-runs when nodes are added/removed so a
  // freshly added/duplicated/inserted node immediately gets debugMode + breakpoint gutter)
  useEffect(() => {
    setRfNodes((nds) => nds.map((n) => ({ ...n, data: { ...n.data, runStatus: runByNode[n.id] ?? null, runStep: stepsById[n.id] ?? null, hasBreakpoint: breakpoints.has(n.id), debugMode } })));
  }, [runByNode, stepsById, breakpoints, debugMode, rfNodes.length, setRfNodes]);

  const dirty = baseline !== "" && JSON.stringify(toGraph(rfNodes, rfEdges)) !== baseline;

  const onConnect = useCallback((c: Connection) => setRfEdges((eds) => addEdge({ ...c, id: `e-${uid()}`, type: "add", label: c.sourceHandle || undefined }, eds)), [setRfEdges]);
  const onSelectionChange = useCallback(({ nodes }: any) => setSelected(nodes.length === 1 ? nodes[0].id : null), []);

  const addNode = (type: string) => {
    const pos = screenToFlowPosition({ x: 380, y: 260 });
    setRfNodes((nds) => nds.concat({ id: `${type}-${uid()}`, type: "fnode", position: pos, data: { title: type, nodeType: type, color: COLOR[type], config: {} } }));
  };

  const patchConfig = (config: any) => selected && setRfNodes((nds) => nds.map((n) => (n.id === selected ? { ...n, data: { ...n.data, config } } : n)));
  const patchTitle = (title: string) => selected && setRfNodes((nds) => nds.map((n) => (n.id === selected ? { ...n, data: { ...n.data, title } } : n)));

  // canvas editing: delete/duplicate a node, delete or insert-on an edge (n8n-style "+")
  const removeEdge = useCallback((eid: string) => setRfEdges((eds) => eds.filter((e) => e.id !== eid)), [setRfEdges]);
  const deleteNode = useCallback((nid: string) => {
    setRfNodes((nds) => nds.filter((n) => n.id !== nid));
    setRfEdges((eds) => eds.filter((e) => e.source !== nid && e.target !== nid));
    setSelected((s) => (s === nid ? null : s));
  }, [setRfNodes, setRfEdges]);
  const dupNode = useCallback((nid: string) => {
    const n = nodesRef.current.find((x) => x.id === nid); if (!n) return;
    const t = (n.data as any).nodeType; const id = `${t}-${uid()}`;
    setRfNodes((nds) => nds.concat({ ...n, id, selected: false, position: { x: n.position.x + 44, y: n.position.y + 64 }, data: { ...(n.data as any), runStatus: null, runStep: null } }));
    setSelected(id);
  }, [setRfNodes]);
  const insertOnEdge = useCallback((eid: string, type: string) => {
    const e = edgesRef.current.find((x) => x.id === eid); if (!e) return;
    const tt = nodesRef.current.find((n) => n.id === e.target); if (!tt) return;
    const nid = `${type}-${uid()}`;
    const branch = (e as any).sourceHandle;
    const DX = 248; // node width + gap; drop the new node where the target was and shove the rest right
    const dropAt = { x: tt.position.x, y: tt.position.y };
    setRfNodes((nds) => nds
      .map((n) => (n.position.x >= tt.position.x - 1 ? { ...n, position: { x: n.position.x + DX, y: n.position.y } } : n))
      .concat({ id: nid, type: "fnode", position: dropAt, data: { title: type, nodeType: type, color: COLOR[type], config: {} } }));
    setRfEdges((eds) => eds.filter((x) => x.id !== eid).concat([
      { id: `e-${uid()}`, source: e.source, target: nid, sourceHandle: branch || undefined, label: branch || undefined, type: "add", data: {} } as RFEdge,
      { id: `e-${uid()}`, source: nid, target: e.target, type: "add", data: {} } as RFEdge,
    ]));
    setSelected(nid);
  }, [setRfNodes, setRfEdges]);

  useEffect(() => {
    const del = (ev: Event) => deleteNode((ev as CustomEvent).detail as string);
    const dup = (ev: Event) => dupNode((ev as CustomEvent).detail as string);
    document.addEventListener("agm-flow-del", del); document.addEventListener("agm-flow-dup", dup);
    return () => { document.removeEventListener("agm-flow-del", del); document.removeEventListener("agm-flow-dup", dup); };
  }, [deleteNode, dupNode]);

  // keyboard shortcuts: ⌘↵ run · ⌘S save · ⌘D duplicate · ⌫ delete (React Flow handles delete natively)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = document.activeElement as HTMLElement | null;
      const typing = !!el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT" || el.isContentEditable);
      const mod = e.metaKey || e.ctrlKey; const a = actionsRef.current;
      if (e.key === "Escape" && !typing) { if (a.tplPicker) a.setTplPicker(false); else if (a.selected) a.setSelected(null); return; }
      if (mod && e.key === "Enter") { e.preventDefault(); if (!a.running) a.run(false); }
      else if (mod && (e.key === "s" || e.key === "S")) { e.preventDefault(); if (a.dirty) a.save(); }
      else if (mod && (e.key === "d" || e.key === "D") && !typing) { e.preventDefault(); if (a.selected) a.dupNode(a.selected); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  async function save() {
    if (!activeId) return;
    const g = toGraph(rfNodes, rfEdges);
    const f = flows.find((x) => x.id === activeId);
    await api.updateFlow(activeId, { name: f?.name || "flow", nodes: g.nodes, edges: g.edges });
    setBaseline(JSON.stringify(g)); flash("Saved");
  }
  async function newFlowFrom(tpl: typeof TEMPLATES[number]) {
    const f = await api.createFlow(tpl.name === "Blank canvas" ? "New flow" : tpl.name, tpl.nodes, tpl.edges);
    setTplPicker(false); await loadFlows(); setActiveId(f.id);
  }

  function lightEdge(nid: string, branch: string | null | undefined) {
    setRfEdges((eds) => eds.map((e) => e.source === nid && (!branch || e.sourceHandle === branch) ? { ...e, animated: true, style: { stroke: "var(--accent)" } } : e));
  }
  function resetRun() { setRunByNode({}); setStepsById({}); setRunStatus("idle"); setRunId(""); setPausedNode(null); setRfEdges((eds) => eds.map((e) => ({ ...e, animated: false, style: undefined }))); }

  const onEvent = useCallback((e: FlowEvent) => {
    if (e.type === "start") { setRunId(e.run_id || ""); setRunStatus("running"); return; }
    if (e.type === "node" && e.status === "running") { setRunByNode((p) => ({ ...p, [e.node_id!]: "running" })); return; }
    if (e.type === "node") { setRunByNode((p) => ({ ...p, [e.node_id!]: e.status === "error" ? "failed" : "done" })); setStepsById((p) => ({ ...p, [e.node_id!]: e })); if (e.status !== "error") lightEdge(e.node_id!, e.branch); return; }
    if (e.type === "pause") { setPausedNode(e.node_id!); setRunId(e.run_id || ""); setRunStatus("paused"); setRunByNode((p) => ({ ...p, [e.node_id!]: "paused" })); return; }
    if (e.type === "done") { setRunStatus(e.status || "completed"); setPausedNode(null); return; }
    if (e.type === "error") setRunStatus("failed");
  }, []);

  const flowInput = () => { const inp = rfNodes.find((n) => (n.data as any).nodeType === "input"); return (inp?.data as any)?.config?.sample || {}; };

  async function run(step = false) {
    if (!activeId) return;
    await save().catch(() => {});
    resetRun(); setRunStatus("running"); setRunning(true);
    const ac = new AbortController(); abortRef.current = ac;
    try { await api.runFlowStream(activeId, flowInput(), { breakpoints: [...breakpoints], step }, onEvent, ac.signal); }
    catch (e: any) { if (e.name !== "AbortError") flash(e.message); }
    finally { setRunning(false); abortRef.current = null; }
  }
  async function cont(step = false) {
    if (!activeId || !runId || !pausedNode) return;
    setRunByNode((p) => ({ ...p, [pausedNode]: "running" })); setPausedNode(null); setRunStatus("running"); setRunning(true);
    const ac = new AbortController(); abortRef.current = ac;
    try { await api.continueFlowStream(activeId, { run_id: runId, node_id: pausedNode, breakpoints: [...breakpoints], step }, onEvent, ac.signal); }
    catch (e: any) { if (e.name !== "AbortError") flash(e.message); }
    finally { setRunning(false); abortRef.current = null; }
  }
  const stepBtn = () => (runStatus === "paused" ? cont(true) : run(true));
  const stop = () => { abortRef.current?.abort(); setRunning(false); setRunStatus((s) => (s === "running" ? "idle" : s)); };

  actionsRef.current = { run, save, dupNode, selected, running, dirty, tplPicker, setTplPicker, setSelected };

  const selNode = selected ? rfNodes.find((n) => n.id === selected) : null;
  // Animate edges leaving any node that has already run — the "flow" pulses along the executed path.
  const displayEdges = rfEdges.map((e) => {
    const done = !!runByNode[e.source] && runByNode[e.source] !== "running";
    const live = running || runStatus === "paused";
    return { ...e, type: "add", animated: live && done, data: { ...(e.data as any), insert: insertOnEdge, remove: removeEdge } };
  });

  return (
    <div className="app" style={{ gridTemplateRows: "auto 1fr" }}>
      <TopNav />
      <div className="flows-ws">
        <aside className="flow-list">
          <div className="side-head"><span>Flows</span><button onClick={() => setTplPicker(true)} title="New flow">+</button></div>
          {flows.length === 0 && <div className="side-empty">No flows yet.<br />Hit <b>+</b> to start from a template.</div>}
          {flows.map((f) => (
            <div key={f.id} className={`fl-item ${activeId === f.id ? "on" : ""}`} onClick={() => setActiveId(f.id)}>
              <div className="fl-name">{f.name}</div><div className="fl-desc">{f.description}</div>
            </div>
          ))}
        </aside>

        <div className="flow-canvas">
          <div className="flow-bar">
            <div className="fb-pal">{PALETTE.map((t) => <button key={t} className={`pal-chip ${COLOR[t]}`} onClick={() => addNode(t)}>+ {t}</button>)}</div>
            <span className="fb-sep" />
            <button className={`btn btn-sm ${debugMode ? "on-d" : ""}`} onClick={() => setDebugMode((o) => !o)}>⏵ Debug</button>
            {!running ? <button className="btn btn-run btn-sm" title="Run (⌘↵)" onClick={() => run(false)}>▶ Run</button> : <button className="btn btn-stop btn-sm" onClick={stop}>■ Stop</button>}
            {debugMode && <button className="btn btn-sm" onClick={stepBtn} disabled={running && runStatus !== "paused"}>⏭ Step</button>}
            {debugMode && <button className="btn btn-sm" onClick={() => cont(false)} disabled={runStatus !== "paused"}>⏩ Continue</button>}
            <span className={`fb-status ${runStatus}`}>{runStatus}</span>
            <span style={{ marginLeft: "auto" }} />
            {dirty && <span className="pr-dirty">● unsaved</span>}
            <button className="btn btn-sm" title="Save (⌘S)" disabled={!dirty} onClick={save}>Save</button>
          </div>
          <div className="rf-wrap">
            <ReactFlow
              nodes={rfNodes} edges={displayEdges} onNodesChange={onNodesChange} onEdgesChange={onEdgesChange}
              onConnect={onConnect} onSelectionChange={onSelectionChange} nodeTypes={nodeTypes} edgeTypes={edgeTypes}
              defaultEdgeOptions={{ type: "add" }}
              fitView fitViewOptions={{ padding: 0.3, maxZoom: 1 }} proOptions={{ hideAttribution: true }} deleteKeyCode={["Backspace", "Delete"]} minZoom={0.3}>
              <Background variant={BackgroundVariant.Dots} gap={26} size={1.4} color="#2a2a3a" />
              <MiniMap pannable zoomable maskColor="rgba(9,9,17,0.72)" nodeColor={(n) => `var(--${(n.data as any)?.color === "muted" ? "faint" : (n.data as any)?.color || "faint"})`} />
              <Controls showInteractive={false} />
            </ReactFlow>
            {!activeId && (
              <div className="flow-empty">
                <div className="fe-icon">🔀</div>
                <h3>Build your first agent flow</h3>
                <p>Wire prompts, tools, and conditions into a runnable graph — then run it and step-debug node by node.</p>
                <button className="btn btn-run" onClick={() => setTplPicker(true)}>+ New flow from template</button>
              </div>
            )}
          </div>
        </div>

        {selNode && <NodeInspector key={selNode.id} node={selNode} connections={connections} runStep={stepsById[selNode.id]} onChange={patchConfig} onTitle={patchTitle} onClose={() => setSelected(null)} />}
      </div>
      {tplPicker && (
        <div className="overlay" onClick={() => setTplPicker(false)}>
          <div className="modal wiz" onClick={(e) => e.stopPropagation()}>
            <div className="modal-head">New flow<button onClick={() => setTplPicker(false)}>×</button></div>
            <div className="modal-body">
              <p className="wiz-lead">Start from a template — or a blank canvas.</p>
              <div className="wiz-grid">
                {TEMPLATES.map((t) => (
                  <button key={t.id} className="wiz-provider" onClick={() => newFlowFrom(t)}>
                    <span className="wp-ic">{t.icon}</span>
                    <span className="wp-main"><span className="wp-name">{t.name}</span><span className="wp-desc">{t.desc}</span></span>
                    <span className="wp-arrow">›</span>
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}
      {toast && <div className="toast">{toast}</div>}
    </div>
  );
}

export default function FlowsPage() {
  return <ReactFlowProvider><Editor /></ReactFlowProvider>;
}
