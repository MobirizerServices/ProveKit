"use client";

import {
  Background, BackgroundVariant, Connection, Controls, Edge, Handle, Node, Position, ReactFlow,
  addEdge, useEdgesState, useNodesState,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useCallback, useEffect, useMemo } from "react";
import { FlowEdge, FlowGraph, FlowNode, FlowNodeType, FlowStep } from "@/lib/api";

/** Palette metadata — colour, glyph and default label per node type. */
export const NODE_META: Record<FlowNodeType, { label: string; hint: string; color: string; icon: string }> = {
  trigger:   { label: "Trigger",   hint: "Starts the run",      color: "var(--green)",  icon: "⚡" },
  agent:     { label: "AI Agent",  hint: "Reason & use tools",  color: "var(--accent)", icon: "◆" },
  model:     { label: "LLM Model", hint: "OpenAI, Anthropic",   color: "var(--blue)",   icon: "✷" },
  knowledge: { label: "Knowledge", hint: "Vector & web search", color: "var(--amber)",  icon: "◉" },
  logic:     { label: "Logic",     hint: "Branch & transform",  color: "var(--red)",    icon: "⑂" },
  approval:  { label: "Approval",  hint: "Human in the loop",   color: "var(--green)",  icon: "✓" },
  output:    { label: "Output",    hint: "Typed response",      color: "var(--purple)", icon: "▣" },
};

export type RunState = Record<string, FlowStep["status"] | "running">;

function StudioNode({ data }: { data: Record<string, unknown> }) {
  const type = data.kind as FlowNodeType;
  const meta = NODE_META[type] || NODE_META.agent;
  const runStatus = data.runStatus as string | undefined;
  return (
    <div className={`fnode ${runStatus ? `run-${runStatus === "ok" ? "done" : runStatus}` : ""}`}
      style={{ ["--nc" as string]: meta.color }}>
      {type !== "trigger" && <Handle type="target" position={Position.Left} className="fn-handle" />}
      <div className="fn-head">
        <span className="fn-ic" style={{ color: meta.color }}>{meta.icon}</span>
        <span className="fn-t">{(data.label as string) || meta.label}</span>
        {runStatus && <span className={`fn-pip ${runStatus === "failed" ? "down" : runStatus === "skipped" ? "warn" : "ok"}`} />}
      </div>
      <div className="fn-s">{(data.subtitle as string) || meta.hint}</div>
      <Handle type="source" position={Position.Right} className="fn-handle source" />
    </div>
  );
}

const nodeTypes = { studio: StudioNode };

function dataFor(n: FlowNode, runState?: RunState) {
  return { kind: n.type, label: n.label, subtitle: subtitleFor(n), runStatus: runState?.[n.id] };
}

export default function FlowCanvas({
  graph, onChange, selected, onSelect, runState, revision = 0,
}: {
  graph: FlowGraph;
  onChange: (g: FlowGraph) => void;
  selected: string | null;
  onSelect: (id: string | null) => void;
  runState?: RunState;
  /** Bumped only when a *different* graph is loaded (open / restore), never on canvas edits. */
  revision?: number;
}) {
  // React Flow owns node identity so it can keep its own measurements — a node rebuilt from
  // props on every render never finishes measuring and stays `visibility: hidden`.
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);

  // Full reseed: a new flow was opened or a version restored.
  useEffect(() => {
    setNodes((graph.nodes || []).map((n) => ({
      id: n.id, type: "studio", position: n.position || { x: 0, y: 0 }, data: dataFor(n, runState),
    })));
    setEdges((graph.edges || []).map((e) => ({
      id: e.id, source: e.source, target: e.target, label: e.label || undefined, animated: true,
    })));
  }, [revision]);  // eslint-disable-line react-hooks/exhaustive-deps

  // Reconcile in place: add nodes the palette created, drop deleted ones, refresh labels and
  // run status — all without replacing surviving nodes, which would discard their measurement.
  useEffect(() => {
    setNodes((cur) => {
      const wanted = graph.nodes || [];
      const kept = cur
        .filter((c) => wanted.some((w) => w.id === c.id))
        .map((c) => {
          const w = wanted.find((x) => x.id === c.id)!;
          return { ...c, selected: c.id === selected, data: dataFor(w, runState) };
        });
      const added = wanted
        .filter((w) => !cur.some((c) => c.id === w.id))
        .map((w) => ({ id: w.id, type: "studio", position: w.position || { x: 0, y: 0 }, data: dataFor(w, runState) }));
      return [...kept, ...added];
    });
    setEdges((cur) => {
      const wanted = graph.edges || [];
      const kept = cur.filter((c) => wanted.some((w) => w.id === c.id));
      const added = wanted
        .filter((w) => !cur.some((c) => c.id === w.id))
        .map((w) => ({ id: w.id, source: w.source, target: w.target, label: w.label || undefined, animated: true }));
      return [...kept, ...added];
    });
  }, [graph, selected, runState, setNodes, setEdges]);

  // Push structural changes (drag, delete) back into the graph document.
  const commitNodes = useCallback((next: Node[]) => {
    onChange({
      nodes: (graph.nodes || [])
        .filter((n) => next.some((x) => x.id === n.id))
        .map((n) => {
          const m = next.find((x) => x.id === n.id)!;
          return { ...n, position: m.position };
        }),
      edges: (graph.edges || []).filter(
        (e) => next.some((x) => x.id === e.source) && next.some((x) => x.id === e.target)),
    });
  }, [graph, onChange]);

  const onConnect = useCallback((c: Connection) => {
    const id = `e${Date.now()}`;
    setEdges((cur) => addEdge({ ...c, id, animated: true }, cur));
    onChange({
      ...graph,
      edges: [...(graph.edges || []), { id, source: c.source!, target: c.target! } as FlowEdge],
    });
  }, [graph, onChange, setEdges]);

  const styled = useMemo(
    () => nodes.map((n) => ({ ...n, selected: n.id === selected })),
    [nodes, selected]);

  return (
    <div className="rf-wrap">
      <ReactFlow
        nodes={styled} edges={edges} nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeDragStop={(_, __, all) => commitNodes(all.length ? nodes : nodes)}
        onNodesDelete={(deleted) => commitNodes(nodes.filter((n) => !deleted.some((d) => d.id === n.id)))}
        onEdgesDelete={(deleted) => onChange({
          ...graph, edges: (graph.edges || []).filter((e) => !deleted.some((d) => d.id === e.id)),
        })}
        onConnect={onConnect}
        onNodeClick={(_, n) => onSelect(n.id)}
        onPaneClick={() => onSelect(null)}
        fitView proOptions={{ hideAttribution: true }}
      >
        <Background variant={BackgroundVariant.Dots} gap={22} size={1} color="var(--border-2)" />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}

function subtitleFor(n: FlowNode): string {
  if (n.type === "agent" || n.type === "model") return n.config?.model || NODE_META[n.type].hint;
  if (n.type === "logic") {
    const c = n.config?.conditions?.length || 0;
    return c ? `${c} condition${c === 1 ? "" : "s"}` : "no conditions";
  }
  return NODE_META[n.type]?.hint || "";
}
