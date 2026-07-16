"use client";

import { memo } from "react";
import { Handle, Position, NodeToolbar, type NodeProps } from "@xyflow/react";

const EMOJI: Record<string, string> = { input: "📥", prompt: "✨", tool: "🔧", agent: "🛰️", condition: "🔀", output: "📤" };

// Generic per-node description → subtitle, status pip, setup flag, and a metric (bold value + label),
// mirroring Magari's node body (emoji · title · pip / subtitle / setup-tag · metric).
function describe(t: string, cfg: any) {
  cfg = cfg || {};
  const short = (m: string) => String(m).replace(/^(gpt|claude)-/i, "");
  switch (t) {
    case "input": {
      const n = cfg.sample && typeof cfg.sample === "object" ? Object.keys(cfg.sample).length : 0;
      return { sub: "Flow input", pip: "ok", setup: false, metric: { value: n, label: n === 1 ? "field" : "fields" } };
    }
    case "prompt": {
      const setup = !cfg.connection_id;
      const m = cfg.prompt_key || cfg.model;
      return { sub: cfg.prompt_key ? "Registry prompt" : "LLM prompt", pip: setup ? "warn" : "ok", setup,
        metric: m ? { value: short(m), label: cfg.prompt_key ? "key" : "model" } : null };
    }
    case "tool": {
      const setup = !cfg.connection_id || !cfg.tool;
      return { sub: "MCP tool call", pip: setup ? "warn" : "ok", setup,
        metric: cfg.tool ? { value: cfg.tool, label: "tool" } : null };
    }
    case "agent": {
      const setup = !cfg.connection_id;
      return { sub: cfg.path ? `${cfg.method || "POST"} ${cfg.path}` : "HTTP agent", pip: setup ? "warn" : "ok", setup,
        metric: null };
    }
    case "condition": {
      return { sub: "Branch on a value", pip: "ok", setup: false,
        metric: cfg.op ? { value: cfg.op, label: "check" } : null };
    }
    case "output": {
      return { sub: "Returns a value", pip: "ok", setup: false, metric: { value: "1", label: "value" } };
    }
    default:
      return { sub: "", pip: null, setup: false, metric: null };
  }
}

function FlowNodeImpl({ id, data, selected }: NodeProps) {
  const d = data as any;
  const t: string = d.nodeType;
  const info = describe(t, d.config);
  const step = d.runStep as { branch?: string | null; duration_ms?: number; status?: string } | null;
  const cls = ["fnode", d.color, selected ? "sel" : "", d.runStatus ? `run-${d.runStatus}` : "", d.hasBreakpoint ? "has-bp" : ""].filter(Boolean).join(" ");
  const toggleBp = (e: React.MouseEvent) => { e.stopPropagation(); document.dispatchEvent(new CustomEvent("agm-flow-bp", { detail: id })); };

  const del = (e: React.MouseEvent) => { e.stopPropagation(); document.dispatchEvent(new CustomEvent("agm-flow-del", { detail: id })); };
  const dup = (e: React.MouseEvent) => { e.stopPropagation(); document.dispatchEvent(new CustomEvent("agm-flow-dup", { detail: id })); };

  return (
    <div className={cls}>
      {t !== "input" && (
        <NodeToolbar isVisible={selected} position={Position.Top} align="end" offset={8}>
          <div className="fn-toolbar">
            <button onClick={dup} title="Duplicate">⧉</button>
            <button className="del" onClick={del} title="Delete">🗑</button>
          </div>
        </NodeToolbar>
      )}
      {d.debugMode && <button className={`fn-bp ${d.hasBreakpoint ? "on" : ""}`} onClick={toggleBp} title="Breakpoint" />}
      {t !== "input" && <Handle type="target" position={Position.Left} className="fn-handle" />}
      <div className="fn-head">
        <span className="fn-ic" aria-hidden="true">{EMOJI[t] || "●"}</span>
        <span className="fn-t">{d.title || t}</span>
        {info.pip && <span className={`fn-pip ${info.pip}`} title={info.setup ? "needs setup" : "ready"} />}
      </div>
      {info.sub && <div className="fn-s">{info.sub}</div>}
      {step && (step.status === "ok" || step.status === "error") ? (
        <div className={`fn-run ${step.status}`}>
          <span className="fn-dot" />
          {step.branch && <span className="fn-branch">→ {step.branch}</span>}
          {step.duration_ms != null && <span className="fn-ms">{step.duration_ms} ms</span>}
        </div>
      ) : (info.setup || info.metric) ? (
        <div className="fn-foot">
          {info.setup && <span className="fn-tag">⚙ setup</span>}
          {info.metric && <span className="fn-count"><b>{info.metric.value}</b> {info.metric.label}</span>}
        </div>
      ) : null}
      {t === "condition" ? (
        <>
          <Handle id="true" type="source" position={Position.Right} style={{ top: "38%" }} className="fn-handle t" />
          <Handle id="false" type="source" position={Position.Right} style={{ top: "72%" }} className="fn-handle f" />
        </>
      ) : t !== "output" ? (
        <Handle type="source" position={Position.Right} className="fn-handle" />
      ) : null}
    </div>
  );
}

export const FlowNode = memo(FlowNodeImpl);
