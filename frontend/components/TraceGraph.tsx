"use client";

import { Background, Controls, Handle, Position, ReactFlow } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useMemo } from "react";
import { TraceSpan } from "@/lib/api";

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
        <span style={{ fontSize: 12.5, fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {s.label}
        </span>
      </div>
      <div className="muted" style={{ fontSize: 10.5, marginTop: 4 }}>
        {s.duration_ms}ms{tok ? ` · ${tok}` : ""}{s.status === "failed" ? " · failed" : ""}
      </div>
      <Handle type="source" position={Position.Right} style={{ opacity: 0 }} />
    </div>
  );
}

const nodeTypes = { span: SpanNode };

export default function TraceGraph({ spans, selected, onSelect }: {
  spans: TraceSpan[]; selected: string | null; onSelect: (id: string) => void;
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
    return {
      nodes: spans.map((s) => ({
        id: s.span_id, type: "span", position: pos[s.span_id] || { x: 0, y: 0 },
        data: { span: s, active: selected === s.span_id },
      })),
      edges: spans.filter((s) => s.parent_span_id && ids.has(s.parent_span_id)).map((s) => ({
        id: `${s.parent_span_id}->${s.span_id}`, source: s.parent_span_id, target: s.span_id,
        style: { stroke: "var(--border-strong)", strokeWidth: 1.5 },
      })),
    };
  }, [spans, selected]);

  return (
    <div style={{ height: 460, borderRadius: 10, overflow: "hidden", border: "1px solid var(--border)" }}>
      <ReactFlow
        nodes={nodes} edges={edges} nodeTypes={nodeTypes} fitView
        proOptions={{ hideAttribution: true }}
        nodesDraggable={false} nodesConnectable={false} elementsSelectable
        onNodeClick={(_e, n) => onSelect(n.id)}
      >
        <Background gap={18} color="var(--border)" />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}
