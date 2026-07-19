"use client";

import dagre from "@dagrejs/dagre";
import { Background, BackgroundVariant, Controls, Handle, MarkerType, MiniMap, Position, ReactFlow } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useCallback, useMemo, useState } from "react";
import { TraceSpan } from "@/lib/api";
import { estimateCost, fmtCost } from "@/lib/cost";

const TYPE_COLOR: Record<string, string> = {
  agent: "var(--accent)", llm: "var(--blue)", tool: "var(--purple)", step: "var(--muted)",
};
// Concrete hex for the minimap — its canvas doesn't resolve CSS variables (they'd render
// black), so the mini node dots need literal colors.
const MINI_COLOR: Record<string, string> = {
  agent: "#d8b45f", llm: "#6ea8ff", tool: "#c98cf0", step: "#97979f",
};

const NODE_W = 210;  // node box width for the layout engine
const NODE_H = 60;   // approximate node box height

function tokens(s: TraceSpan): string | null {
  const u = s.result?.meta?.usage;
  if (!u || u.input_tokens == null) return null;
  return `${u.input_tokens}→${u.output_tokens ?? 0} tok`;
}

interface NodeData {
  span: TraceSpan; active: boolean; childCount?: number; collapsed?: boolean;
  onToggle?: (id: string) => void; dim?: boolean; slow?: boolean;
}

function SpanNode({ data }: { data: NodeData }) {
  const s = data.span;
  const color = s.status === "failed" ? "var(--red)" : (TYPE_COLOR[s.type] || "var(--muted)");
  const tok = tokens(s);
  const cost = fmtCost(estimateCost(s.request?.model, s.result?.meta?.usage?.input_tokens, s.result?.meta?.usage?.output_tokens));
  const nEvents = Array.isArray(s.result?.meta?.events) ? s.result!.meta!.events.length : 0;
  const hasKids = (data.childCount ?? 0) > 0;
  return (
    <div style={{
      minWidth: 176, maxWidth: 220, padding: "9px 11px", borderRadius: 10,
      background: "var(--panel)", border: `1px solid ${color}`,
      boxShadow: data.active ? `0 0 0 2px ${color}` : "var(--sh-1)", cursor: "pointer",
      opacity: data.dim ? 0.28 : 1, transition: "opacity .15s",
    }}>
      <Handle type="target" position={Position.Left} style={{ opacity: 0 }} />
      <div style={{ display: "flex", alignItems: "center", gap: 7, minWidth: 0 }}>
        <span style={{
          fontSize: 9.5, fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.3,
          padding: "1px 5px", borderRadius: 4, color, border: `1px solid ${color}`, flexShrink: 0,
        }}>{s.type}</span>
        <span style={{ fontSize: 12.5, fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1 }}>
          {s.label}
        </span>
        {/* collapse/expand toggle for nodes with children */}
        {hasKids && (
          <button title={data.collapsed ? "Expand" : "Collapse"} className="nodrag"
            onClick={(e) => { e.stopPropagation(); data.onToggle?.(s.span_id); }}
            style={{ flexShrink: 0, width: 16, height: 16, borderRadius: 4, border: `1px solid ${color}`,
              background: "var(--bg-2)", color, fontSize: 10, lineHeight: 1, cursor: "pointer", padding: 0 }}>
            {data.collapsed ? "+" : "−"}
          </button>
        )}
        {data.slow && <span title="among the slowest spans" style={{ flexShrink: 0, fontSize: 11, color: "var(--amber)" }}>⏱</span>}
        <span aria-label={s.status} style={{ flexShrink: 0, fontSize: 12, fontWeight: 700,
          color: s.status === "failed" ? "var(--red)" : "var(--green)" }}>
          {s.status === "failed" ? "✕" : "✓"}
        </span>
      </div>
      <div className="muted" style={{ fontSize: 10.5, marginTop: 4 }}>
        {s.duration_ms}ms{tok ? ` · ${tok}` : ""}{cost ? ` · ${cost}` : ""}{s.status === "failed" ? " · failed" : ""}
      </div>
      {data.collapsed && hasKids && (
        <div style={{ fontSize: 9.5, marginTop: 3, color }}>▸ {data.childCount} hidden span{data.childCount === 1 ? "" : "s"}</div>
      )}
      {!data.collapsed && nEvents > 0 && (
        <div style={{ fontSize: 9.5, marginTop: 3, color: "var(--muted)" }}>▸ {nEvents} log{nEvents === 1 ? "" : "s"}</div>
      )}
      <Handle type="source" position={Position.Right} style={{ opacity: 0 }} />
    </div>
  );
}

const nodeTypes = { span: SpanNode };

export default function TraceGraph({ spans, selected, onSelect, fill }: {
  spans: TraceSpan[]; selected: string | null; onSelect: (id: string) => void; fill?: boolean;
}) {
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [hideSteps, setHideSteps] = useState(false);
  const [search, setSearch] = useState("");
  const toggle = useCallback((id: string) => {
    setCollapsed((prev) => { const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n; });
  }, []);

  // The trace's p90 duration → mark spans at/above it as "slow".
  const slowThreshold = useMemo(() => {
    const ds = spans.map((s) => s.duration_ms || 0).sort((a, b) => a - b);
    if (ds.length < 3) return Infinity;
    return ds[Math.floor(ds.length * 0.9)] || Infinity;
  }, [spans]);

  const { nodes, edges } = useMemo(() => {
    const ids = new Set(spans.map((s) => s.span_id));
    const kids: Record<string, TraceSpan[]> = {};
    const roots: TraceSpan[] = [];
    for (const s of spans) {
      const p = s.parent_span_id && ids.has(s.parent_span_id) ? s.parent_span_id : null;
      if (p) (kids[p] ||= []).push(s);
      else roots.push(s);
    }
    // Descendant count per node (for the "+N hidden" badge).
    const descCount: Record<string, number> = {};
    const countDesc = (id: string): number => {
      const c = (kids[id] || []).reduce((n, ch) => n + 1 + countDesc(ch.span_id), 0);
      descCount[id] = c; return c;
    };
    roots.forEach((r) => countDesc(r.span_id));

    // Hidden = anything under a collapsed node, or a `step` node when hideSteps is on.
    const hidden = new Set<string>();
    const hideUnder = (id: string) => (kids[id] || []).forEach((ch) => { hidden.add(ch.span_id); hideUnder(ch.span_id); });
    collapsed.forEach((id) => hideUnder(id));
    if (hideSteps) for (const s of spans) if (s.type === "step") hidden.add(s.span_id);

    const visible = spans.filter((s) => !hidden.has(s.span_id));
    const visibleIds = new Set(visible.map((s) => s.span_id));

    // Auto-layout the visible tree with dagre (left→right, ranked by depth). This gives tighter,
    // better-balanced spacing than a naïve leaf layout and stays clean as traces get big.
    const g = new dagre.graphlib.Graph();
    g.setGraph({ rankdir: "LR", nodesep: 26, ranksep: 60, marginx: 20, marginy: 20 });
    g.setDefaultEdgeLabel(() => ({}));
    visible.forEach((s) => g.setNode(s.span_id, { width: NODE_W, height: NODE_H }));
    visible.forEach((s) => {
      if (s.parent_span_id && visibleIds.has(s.parent_span_id)) g.setEdge(s.parent_span_id, s.span_id);
    });
    dagre.layout(g);
    const pos: Record<string, { x: number; y: number }> = {};
    visible.forEach((s) => {
      const n = g.node(s.span_id);
      // dagre gives center coords; React Flow wants top-left.
      pos[s.span_id] = n ? { x: n.x - NODE_W / 2, y: n.y - NODE_H / 2 } : { x: 0, y: 0 };
    });

    const parentOf: Record<string, string | null> = {};
    for (const s of spans) parentOf[s.span_id] = s.parent_span_id && ids.has(s.parent_span_id) ? s.parent_span_id : null;
    const onPath = new Set<string>();
    for (let cur = selected; cur && parentOf[cur]; cur = parentOf[cur]!) onPath.add(`${parentOf[cur]}->${cur}`);

    return {
      nodes: visible.map((s) => {
        const q = search.trim().toLowerCase();
        const matched = !q || (s.label || "").toLowerCase().includes(q) || (s.request?.model || "").toLowerCase().includes(q) || s.type.includes(q);
        return {
          id: s.span_id, type: "span", position: pos[s.span_id] || { x: 0, y: 0 },
          data: { span: s, active: selected === s.span_id, childCount: descCount[s.span_id] || 0,
            collapsed: collapsed.has(s.span_id), onToggle: toggle,
            slow: (s.duration_ms || 0) >= slowThreshold && (s.duration_ms || 0) > 0,
            dim: !!q && !matched },
        };
      }),
      edges: visible.filter((s) => s.parent_span_id && ids.has(s.parent_span_id) && !hidden.has(s.parent_span_id)).map((s) => {
        const eid = `${s.parent_span_id}->${s.span_id}`;
        const failed = s.status === "failed";
        // Failed exits are red; the path to the selected node lights up in the accent; the
        // rest are calm. Every edge flows (animated) so entry→exit direction reads at a glance.
        const highlighted = onPath.has(eid);
        const color = failed ? "var(--red)" : highlighted ? "var(--accent)" : "var(--border-strong)";
        return {
          id: eid, source: s.parent_span_id, target: s.span_id, type: "smoothstep",
          animated: failed || highlighted,
          markerEnd: { type: MarkerType.ArrowClosed, color, width: 15, height: 15 },
          style: { stroke: color, strokeWidth: highlighted ? 2.4 : failed ? 2 : 1.5 },
        };
      }),
    };
  }, [spans, selected, collapsed, hideSteps, toggle, search, slowThreshold]);

  const hasSteps = useMemo(() => spans.some((s) => s.type === "step"), [spans]);

  // Nodes that have children (candidates for collapse-all).
  const parents = useMemo(() => {
    const ids = new Set(spans.map((s) => s.span_id));
    return spans.filter((s) => spans.some((c) => c.parent_span_id === s.span_id && ids.has(s.span_id))).map((s) => s.span_id);
  }, [spans]);

  return (
    <div style={fill
      ? { height: "100%", width: "100%", position: "relative" }
      : { height: 480, borderRadius: 10, overflow: "hidden", border: "1px solid var(--border)", position: "relative" }}>
      {/* floating declutter toolbar */}
      <div style={{ position: "absolute", top: 8, left: 8, zIndex: 5, display: "flex", gap: 6, alignItems: "center" }}>
        <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search nodes…"
          style={{ width: 140, fontSize: 11.5, padding: "4px 9px", borderRadius: 6, background: "var(--panel)",
            color: "var(--text)", border: `1px solid ${search ? "var(--accent)" : "var(--border-strong)"}` }} />
        {collapsed.size > 0
          ? <button style={tbBtn()} onClick={() => setCollapsed(new Set())}>Expand all</button>
          : parents.length > 1 && <button style={tbBtn()} onClick={() => setCollapsed(new Set(parents))}>Collapse all</button>}
        {hasSteps && <button style={tbBtn(hideSteps)} onClick={() => setHideSteps((v) => !v)}>{hideSteps ? "Show steps" : "Hide steps"}</button>}
      </div>
      <ReactFlow
        nodes={nodes} edges={edges} nodeTypes={nodeTypes}
        fitView fitViewOptions={{ padding: 0.18 }} minZoom={0.15} maxZoom={2.5}
        proOptions={{ hideAttribution: true }}
        nodesDraggable nodesConnectable={false} elementsSelectable
        onNodeClick={(_e, n) => onSelect(n.id)}
      >
        <Background variant={BackgroundVariant.Dots} gap={20} size={1} color="var(--border)" />
        <Controls showZoom showFitView showInteractive={false} position="bottom-left" />
        {/* Minimap only for big graphs (small ones fit on screen). A near-transparent mask so
            the coloured node dots stay visible instead of a dark void. */}
        {nodes.length >= 18 && (
          <MiniMap pannable zoomable nodeColor={(n) => MINI_COLOR[(n.data as any)?.span?.type] || "#97979f"}
            nodeStrokeColor={(n) => ((n.data as any)?.span?.status === "failed" ? "#f0736f" : "#2a2a33")}
            nodeStrokeWidth={2} nodeBorderRadius={2} style={{ background: "#1b1b21" }}
            maskColor="rgba(20,20,24,0.15)" />
        )}
      </ReactFlow>
    </div>
  );
}

function tbBtn(active?: boolean): React.CSSProperties {
  return {
    fontSize: 11, padding: "4px 9px", borderRadius: 6, cursor: "pointer",
    background: active ? "var(--accent-soft)" : "var(--panel)",
    color: active ? "var(--accent)" : "var(--muted)",
    border: `1px solid ${active ? "var(--accent)" : "var(--border-strong)"}`,
  };
}
