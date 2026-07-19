"use client";

import { Background, BackgroundVariant, Controls, Handle, MarkerType, MiniMap, Position, ReactFlow } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useMemo } from "react";
import { TraceSpan } from "@/lib/api";
import { estimateCost, fmtCost } from "@/lib/cost";

const TYPE_COLOR: Record<string, string> = {
  agent: "var(--accent)", llm: "var(--blue)", tool: "var(--purple)", step: "var(--muted)",
};

const COL_X = 250;   // horizontal gap per depth level
const ROW_Y = 96;    // vertical gap per leaf

function tokens(s: TraceSpan): string | null {
  const u = s.result?.meta?.usage;
  if (!u || u.input_tokens == null) return null;
  return `${u.input_tokens}→${u.output_tokens ?? 0} tok`;
}

function SpanNode({ data }: { data: { span: TraceSpan; active: boolean } }) {
  const s = data.span;
  const color = s.status === "failed" ? "var(--red)" : (TYPE_COLOR[s.type] || "var(--muted)");
  const tok = tokens(s);
  const cost = fmtCost(estimateCost(s.request?.model, s.result?.meta?.usage?.input_tokens, s.result?.meta?.usage?.output_tokens));
  const nEvents = Array.isArray(s.result?.meta?.events) ? s.result!.meta!.events.length : 0;
  return (
    <div style={{
      minWidth: 176, maxWidth: 220, padding: "9px 11px", borderRadius: 10,
      background: "var(--panel)", border: `1px solid ${color}`,
      boxShadow: data.active ? `0 0 0 2px ${color}` : "var(--sh-1)", cursor: "pointer",
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
        {/* status glyph so success/failure reads at a glance */}
        <span aria-label={s.status} style={{ flexShrink: 0, fontSize: 12, fontWeight: 700,
          color: s.status === "failed" ? "var(--red)" : "var(--green)" }}>
          {s.status === "failed" ? "✕" : "✓"}
        </span>
      </div>
      <div className="muted" style={{ fontSize: 10.5, marginTop: 4 }}>
        {s.duration_ms}ms{tok ? ` · ${tok}` : ""}{cost ? ` · ${cost}` : ""}{s.status === "failed" ? " · failed" : ""}
      </div>
      {nEvents > 0 && (
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
  const { nodes, edges } = useMemo(() => {
    const ids = new Set(spans.map((s) => s.span_id));
    const kids: Record<string, TraceSpan[]> = {};
    const roots: TraceSpan[] = [];
    for (const s of spans) {
      const p = s.parent_span_id && ids.has(s.parent_span_id) ? s.parent_span_id : null;
      if (p) (kids[p] ||= []).push(s);
      else roots.push(s);
    }
    const pos: Record<string, { x: number; y: number }> = {};
    let leaf = 0;
    const layout = (s: TraceSpan, depth: number): number => {
      const ch = kids[s.span_id] || [];
      let y: number;
      if (ch.length === 0) {
        y = leaf * ROW_Y; leaf++;
      } else {
        const ys = ch.map((c) => layout(c, depth + 1));
        y = (ys[0] + ys[ys.length - 1]) / 2;
      }
      pos[s.span_id] = { x: depth * COL_X, y };
      return y;
    };
    roots.forEach((r) => layout(r, 0));

    // The execution path from the root down to the selected span — highlighted + brighter.
    const parentOf: Record<string, string | null> = {};
    for (const s of spans) parentOf[s.span_id] = s.parent_span_id && ids.has(s.parent_span_id) ? s.parent_span_id : null;
    const onPath = new Set<string>();
    for (let cur = selected; cur && parentOf[cur]; cur = parentOf[cur]!) onPath.add(`${parentOf[cur]}->${cur}`);

    return {
      nodes: spans.map((s) => ({
        id: s.span_id, type: "span", position: pos[s.span_id] || { x: 0, y: 0 },
        data: { span: s, active: selected === s.span_id },
      })),
      edges: spans.filter((s) => s.parent_span_id && ids.has(s.parent_span_id)).map((s) => {
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
  }, [spans, selected]);

  return (
    <div style={fill
      ? { height: "100%", width: "100%" }
      : { height: 480, borderRadius: 10, overflow: "hidden", border: "1px solid var(--border)" }}>
      <ReactFlow
        nodes={nodes} edges={edges} nodeTypes={nodeTypes}
        fitView fitViewOptions={{ padding: 0.18 }} minZoom={0.15} maxZoom={2.5}
        proOptions={{ hideAttribution: true }}
        nodesDraggable nodesConnectable={false} elementsSelectable
        onNodeClick={(_e, n) => onSelect(n.id)}
      >
        <Background variant={BackgroundVariant.Dots} gap={20} size={1} color="var(--border)" />
        <Controls showZoom showFitView showInteractive={false} position="bottom-left" />
        {/* The minimap only earns its space on larger graphs — below ~8 nodes it's a dead
            black box, so hide it. */}
        {nodes.length >= 8 && (
          <MiniMap pannable zoomable nodeColor={(n) => TYPE_COLOR[(n.data as any)?.span?.type] || "var(--muted)"}
            nodeStrokeColor={(n) => ((n.data as any)?.span?.status === "failed" ? "var(--red)" : "transparent")}
            style={{ background: "var(--bg-2)" }} maskColor="rgba(0,0,0,0.55)" />
        )}
      </ReactFlow>
    </div>
  );
}
