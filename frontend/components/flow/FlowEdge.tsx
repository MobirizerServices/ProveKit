"use client";

import { useState } from "react";
import { BaseEdge, EdgeLabelRenderer, getBezierPath, type EdgeProps } from "@xyflow/react";

const INSERTABLE = ["prompt", "tool", "agent", "condition", "output"];

// Animated particle edge (gold flow) + n8n-style "+" node inserter / delete at the midpoint.
export function FlowEdge({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, markerEnd, label, selected, animated, data }: EdgeProps) {
  const [path, labelX, labelY] = getBezierPath({ sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition });
  const [menu, setMenu] = useState(false);
  const d = data as any;
  const hot = !!(selected || animated);
  const reduced = typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  const at = (dy = 0) => ({ transform: `translate(-50%,-50%) translate(${labelX}px,${labelY + dy}px)` });

  return (
    <>
      <BaseEdge id={id} path={path} markerEnd={markerEnd} className={`fl-edge ${hot ? "flowing" : ""}`} />
      {!reduced && (
        <circle className={`fl-particle ${hot ? "hot" : ""}`} r={hot ? 3.4 : 2.4}>
          <animateMotion dur={`${hot ? 1.4 : 3}s`} repeatCount="indefinite" path={path} />
        </circle>
      )}
      {!reduced && animated && (
        <circle className="fl-packet" r={5}>
          <animateMotion dur="0.9s" repeatCount="indefinite" path={path} />
        </circle>
      )}
      <EdgeLabelRenderer>
        {label && <span className="fl-edge-lbl" style={at(-15)}>{label}</span>}
        <div className="edge-tools" style={at()}>
          <button className="edge-add" title="Insert node" onClick={(e) => { e.stopPropagation(); setMenu((m) => !m); }}>+</button>
          <button className="edge-del" title="Delete connection" onClick={(e) => { e.stopPropagation(); d?.remove?.(id); }}>×</button>
          {menu && (
            <div className="edge-menu" onMouseLeave={() => setMenu(false)}>
              {INSERTABLE.map((t) => (
                <button key={t} className={`edge-menu-item ${t}`} onClick={(e) => { e.stopPropagation(); d?.insert?.(id, t); setMenu(false); }}>
                  <span className="emi-dot" /> {t}
                </button>
              ))}
            </div>
          )}
        </div>
      </EdgeLabelRenderer>
    </>
  );
}
