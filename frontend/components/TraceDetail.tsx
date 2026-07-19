"use client";

import { useEffect, useState } from "react";
import { api, Feedback, TraceSpan } from "@/lib/api";
import { estimateCost, fmtCost } from "@/lib/cost";
import TraceGraph from "@/components/TraceGraph";

const TYPE_COLOR: Record<string, string> = {
  agent: "var(--accent)", llm: "var(--blue)", tool: "var(--purple)", step: "var(--muted)",
};
const LOG_COLOR: Record<string, string> = {
  ERROR: "var(--red)", CRITICAL: "var(--red)", WARNING: "var(--amber)", INFO: "var(--blue)", DEBUG: "var(--muted)",
};
const ROLE_COLOR: Record<string, string> = {
  system: "var(--purple)", user: "var(--blue)", assistant: "var(--green)", tool: "var(--amber)",
};

// Detect and normalize an LLM message list so we can render it as a chat transcript
// instead of a raw JSON blob. Returns null when the value isn't message-shaped.
export function parseMessages(v: any): { role: string; content: string }[] | null {
  let data = v;
  if (typeof v === "string") {
    const t = v.trim();
    if (!t.startsWith("[") && !t.startsWith("{")) return null;
    try { data = JSON.parse(t); } catch { return null; }
  }
  if (!data) return null;
  const arr = Array.isArray(data) ? data : Array.isArray(data?.messages) ? data.messages : null;
  if (!arr) return null;
  const msgs = arr.map((m: any) => {
    if (m == null || typeof m !== "object") return null;
    const role = m.role || m.type || m.name;
    if (!role) return null;
    let content = m.content ?? m.text ?? m.message ?? "";
    if (Array.isArray(content)) {
      content = content.map((c: any) => (typeof c === "string" ? c : c?.text ?? JSON.stringify(c))).join("");
    } else if (typeof content !== "string") {
      content = JSON.stringify(content, null, 2);
    }
    return { role: String(role), content };
  }).filter(Boolean) as { role: string; content: string }[];
  return msgs.length ? msgs : null;
}

function Transcript({ msgs }: { msgs: { role: string; content: string }[] }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6, marginBottom: 8 }}>
      {msgs.map((m, i) => (
        <div key={i} style={{ border: "1px solid var(--border)", borderRadius: 8, overflow: "hidden" }}>
          <div style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.4,
            padding: "3px 8px", color: ROLE_COLOR[m.role] || "var(--muted)", background: "var(--bg-2)" }}>
            {m.role}
          </div>
          <pre style={{ ...pre, border: "none", borderRadius: 0, maxHeight: 200 }}>{m.content || <span className="muted">—</span>}</pre>
        </div>
      ))}
    </div>
  );
}

// Renders either a chat transcript (if the value is message-shaped) or a plain pre block.
function IO({ label, value }: { label: string; value: any }) {
  const msgs = parseMessages(value);
  if (msgs) {
    return (
      <div style={{ marginBottom: 8 }}>
        <div className="muted" style={fieldLabel}>{label}</div>
        <Transcript msgs={msgs} />
      </div>
    );
  }
  return <Field label={label}>{textOf(value)}</Field>;
}

export default function TraceDetail({ spans, traceId, readOnly = false }: { spans: TraceSpan[]; traceId?: string; readOnly?: boolean }) {
  const [view, setView] = useState<"flow" | "waterfall">("flow");
  const ids = new Set(spans.map((s) => s.span_id));
  const root = spans.find((s) => !s.parent_span_id || !ids.has(s.parent_span_id));
  const [picked, setPicked] = useState<string | null>(root?.span_id ?? null);
  const totalTok = spans.reduce((n, s) => n + (s.result?.meta?.usage?.input_tokens || 0) + (s.result?.meta?.usage?.output_tokens || 0), 0);
  const totalCost = fmtCost(spans.reduce((n, s) => n + (estimateCost(s.request?.model, s.result?.meta?.usage?.input_tokens, s.result?.meta?.usage?.output_tokens) || 0), 0) || null);
  const sel = spans.find((s) => s.span_id === picked) || root;
  const meta = sel?.result?.meta || {};
  const params = meta.params || {};

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10, paddingBottom: 8, borderBottom: "1px solid var(--border)" }}>
        <div style={{ minWidth: 0 }}>
          <span style={{ fontSize: 14, fontWeight: 600 }}>{root?.label || "trace"}</span>
          <span className="muted" style={{ fontSize: 12, marginLeft: 8 }}>
            {spans.length} span{spans.length === 1 ? "" : "s"} · {root?.duration_ms ?? 0}ms{totalTok ? ` · ${totalTok} tokens` : ""}{totalCost ? ` · ${totalCost}` : ""}
          </span>
          {root?.session_id && <span style={sessionBadge} title="session / thread">◆ {root.session_id}</span>}
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexShrink: 0 }}>
          {!readOnly && traceId && <ShareButton traceId={traceId} />}
          <div style={{ display: "flex", gap: 3, background: "var(--bg-2)", borderRadius: 8, padding: 2 }}>
            {(["flow", "waterfall"] as const).map((v) => (
              <button key={v} onClick={() => setView(v)} style={toggleBtn(view === v)}>
                {v === "flow" ? "Flow" : "Waterfall"}
              </button>
            ))}
          </div>
        </div>
      </div>

      {view === "flow" ? (
        <>
          <TraceGraph spans={spans} selected={picked} onSelect={setPicked} />
          {sel && (
            <div style={{ marginTop: 12 }}>
              <div style={{ fontSize: 13, fontWeight: 600 }}>{sel.label}</div>
              <div className="muted mono" style={{ fontSize: 11, margin: "4px 0 10px", display: "flex", flexWrap: "wrap", gap: "3px 14px" }}>
                <span>{sel.type}</span>
                {sel.request?.provider && <span>provider={sel.request.provider}</span>}
                {sel.request?.model && <span>model={sel.request.model}</span>}
                {sel.request?.operation && <span>op={sel.request.operation}</span>}
                <span style={{ color: sel.status === "failed" ? "var(--red)" : undefined }}>{sel.status}</span>
                <span>{sel.duration_ms}ms</span>
                {tokens(sel) && <span>{tokens(sel)}</span>}
                {(() => {
                  const c = fmtCost(estimateCost(sel.request?.model, sel.result?.meta?.usage?.input_tokens, sel.result?.meta?.usage?.output_tokens));
                  return c ? <span title="estimated cost">{c}</span> : null;
                })()}
              </div>
              <ParamRow params={params} finish={meta.finish_reason} />
              <IO label="Input" value={sel.request?.input} />
              <IO label="Output" value={sel.result?.text} />
              {(sel.error || sel.status === "failed") && <ErrorBlock error={sel.error} />}
              {Array.isArray(meta.events) && meta.events.length > 0 && (
                <div style={{ marginBottom: 8 }}>
                  <div className="muted" style={fieldLabel}>Logs</div>
                  <div style={{ ...pre, padding: 8 }}>
                    {meta.events.map((e: any, i: number) => (
                      <div key={i} style={{ display: "flex", gap: 8 }}>
                        <span style={{ color: LOG_COLOR[e.level] || "var(--muted)", fontWeight: 600, minWidth: 44 }}>{e.level}</span>
                        <span>{e.name}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </>
      ) : (
        <Tree spans={spans} />
      )}

      {!readOnly && traceId && <FeedbackPanel traceId={traceId} />}
    </div>
  );
}

function ShareButton({ traceId }: { traceId: string }) {
  const [label, setLabel] = useState("Share");
  const share = async () => {
    try {
      const { token, expires_in_days } = await api.shareTrace(traceId);
      const url = `${window.location.origin}/shared/${token}`;
      await navigator.clipboard?.writeText(url);
      setLabel(`Copied · ${expires_in_days}d link`);
      setTimeout(() => setLabel("Share"), 2200);
    } catch { setLabel("Failed"); setTimeout(() => setLabel("Share"), 1600); }
  };
  return <button className="btn btn-sm" onClick={share}>{label}</button>;
}

function FeedbackPanel({ traceId }: { traceId: string }) {
  const [items, setItems] = useState<Feedback[]>([]);
  const [comment, setComment] = useState("");
  const load = () => api.feedback(traceId).then(setItems).catch(() => {});
  useEffect(() => { load(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [traceId]);
  const add = async (body: { name: string; value?: string; score?: number | null; comment?: string }) => {
    try { await api.addFeedback(traceId, body); setComment(""); load(); } catch { /* ignore */ }
  };
  return (
    <div style={{ marginTop: 14, paddingTop: 12, borderTop: "1px solid var(--border)" }}>
      <div className="muted" style={fieldLabel}>Feedback</div>
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginBottom: items.length ? 10 : 0 }}>
        <button className="btn btn-sm" onClick={() => add({ name: "thumbs", value: "up", comment })}>👍 Good</button>
        <button className="btn btn-sm" onClick={() => add({ name: "thumbs", value: "down", comment })}>👎 Bad</button>
        <input value={comment} onChange={(e) => setComment(e.target.value)} placeholder="optional comment…"
          style={{ flex: 1, minWidth: 140, background: "var(--panel-2)", color: "var(--text)",
            border: "1px solid var(--border-strong)", borderRadius: 8, padding: "6px 10px", fontSize: 12.5 }} />
      </div>
      {items.map((f) => (
        <div key={f.id} style={{ display: "flex", gap: 8, alignItems: "baseline", fontSize: 12.5, padding: "3px 0" }}>
          <span style={{ fontWeight: 600 }}>{f.name}</span>
          {f.value && <span>{f.value === "up" ? "👍" : f.value === "down" ? "👎" : f.value}</span>}
          {f.score != null && <span className="mono">{f.score}</span>}
          {f.comment && <span className="muted">“{f.comment}”</span>}
          <span className="muted" style={{ marginLeft: "auto", fontSize: 11 }}>{f.source}</span>
        </div>
      ))}
    </div>
  );
}

function toggleBtn(active: boolean): React.CSSProperties {
  return {
    fontSize: 12, padding: "4px 13px", borderRadius: 6, cursor: "pointer", border: "none",
    background: active ? "var(--panel)" : "transparent",
    color: active ? "var(--text)" : "var(--muted)", fontWeight: active ? 600 : 400,
  };
}

function Tree({ spans }: { spans: TraceSpan[] }) {
  const [open, setOpen] = useState<string | null>(spans[0]?.span_id ?? null);
  const kids: Record<string, TraceSpan[]> = {};
  const ids = new Set(spans.map((s) => s.span_id));
  for (const s of spans) {
    const p = s.parent_span_id && ids.has(s.parent_span_id) ? s.parent_span_id : "__root__";
    (kids[p] ||= []).push(s);
  }
  const startNs = (s: TraceSpan): bigint | null => {
    const v = s.result?.meta?.start_ns;
    return v ? BigInt(v) : null;
  };
  const starts = spans.map(startNs).filter((x): x is bigint => x !== null);
  const t0 = starts.length ? starts.reduce((a, b) => (b < a ? b : a)) : 0n;
  let totalNs = 1;
  for (const s of spans) {
    const st = startNs(s);
    if (st === null) continue;
    const end = Number(st - t0) + (s.duration_ms || 0) * 1e6;
    if (end > totalNs) totalNs = end;
  }
  const bar = (s: TraceSpan) => {
    const st = startNs(s);
    if (st === null) return null;
    const left = (Number(st - t0) / totalNs) * 100;
    const width = Math.max(((s.duration_ms || 0) * 1e6 / totalNs) * 100, 1.2);
    return { left: Math.min(left, 99), width: Math.min(width, 100 - Math.min(left, 99)) };
  };
  const render = (parent: string, depth: number): React.ReactNode =>
    (kids[parent] || []).map((s) => {
      const b = bar(s);
      return (
        <div key={s.span_id}>
          <button onClick={() => setOpen(open === s.span_id ? null : s.span_id)} style={spanRow(open === s.span_id)}>
            <span style={{ paddingLeft: depth * 16, display: "inline-flex", alignItems: "center", gap: 8, minWidth: 0, flex: "0 0 46%" }}>
              <span style={badge(s.type)}>{s.type}</span>
              <span style={{ fontSize: 12.5, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.label}</span>
            </span>
            <span style={{ position: "relative", flex: 1, height: 16, background: "var(--bg-2)", borderRadius: 4 }}>
              {b && <span style={{ position: "absolute", top: 3, height: 10, borderRadius: 3,
                left: `${b.left}%`, width: `${b.width}%`, minWidth: 3,
                background: s.status === "failed" ? "var(--red)" : (TYPE_COLOR[s.type] || "var(--muted)"), opacity: 0.85 }} />}
            </span>
            <span style={{ display: "inline-flex", alignItems: "center", gap: 8, flexShrink: 0 }}>
              {tokens(s) && <span className="muted mono" style={{ fontSize: 10.5 }} title="input → output tokens">{tokens(s)}</span>}
              <span className="muted" style={{ fontSize: 11, width: 54, textAlign: "right" }}>{s.duration_ms}ms</span>
            </span>
          </button>
          {open === s.span_id && (
            <div style={{ padding: `4px 0 10px ${depth * 16 + 14}px` }}>
              {s.request?.model && <div className="muted mono" style={{ fontSize: 11.5, marginBottom: 6 }}>{s.request.model}</div>}
              <IO label="Input" value={s.request?.input} />
              <IO label="Output" value={s.result?.text} />
              {(s.error || s.status === "failed") && <ErrorBlock error={s.error} />}
            </div>
          )}
          {render(s.span_id, depth + 1)}
        </div>
      );
    });
  return <div>{render("__root__", 0)}</div>;
}

// Invocation parameters on an LLM span, shown as labelled chips (only if any were captured).
function ParamRow({ params, finish }: { params: any; finish?: any }) {
  const chips: [string, string][] = [];
  if (params?.temperature != null) chips.push(["temp", String(params.temperature)]);
  if (params?.top_p != null) chips.push(["top_p", String(params.top_p)]);
  if (params?.max_tokens != null) chips.push(["max_tokens", String(params.max_tokens)]);
  if (finish != null) chips.push(["finish", String(finish)]);
  if (!chips.length) return null;
  return (
    <div style={{ marginBottom: 8 }}>
      <div className="muted" style={fieldLabel}>Parameters</div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
        {chips.map(([k, v]) => (
          <span key={k} style={{ fontSize: 11.5, fontFamily: "var(--font-mono)", padding: "3px 9px",
            borderRadius: 6, background: "var(--bg-2)", border: "1px solid var(--border)" }}>
            <span className="muted">{k}</span> {v}
          </span>
        ))}
      </div>
    </div>
  );
}

function ErrorBlock({ error }: { error?: string }) {
  return (
    <div style={{ marginBottom: 8 }}>
      <div style={{ fontSize: 10.5, textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 4, color: "var(--red)", fontWeight: 600 }}>
        ✕ Error
      </div>
      <pre style={{ ...pre, border: "1px solid var(--red)", background: "color-mix(in srgb, var(--red) 8%, var(--bg-2))", color: "var(--text)" }}>
        {error?.trim() || <span className="muted">This span failed (no error message captured).</span>}
      </pre>
    </div>
  );
}

const CLAMP = 600;   // chars before we collapse a long payload behind "show more"

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const str = typeof children === "string" ? children : null;
  const empty = !children || (str != null && !str.trim());
  const long = str != null && str.length > CLAMP;
  const shown = long && !open ? str!.slice(0, CLAMP) + "…" : children;
  return (
    <div style={{ marginBottom: 8 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div className="muted" style={fieldLabel}>{label}</div>
        {long && (
          <button onClick={() => setOpen((o) => !o)} style={{ background: "none", border: "none",
            color: "var(--accent)", fontSize: 11, cursor: "pointer", padding: 0 }}>
            {open ? "Show less" : `Show more (${str!.length.toLocaleString()} chars)`}
          </button>
        )}
      </div>
      <pre style={pre}>{empty ? <span className="muted">—</span> : shown}</pre>
    </div>
  );
}

function textOf(v: any): string {
  if (v == null) return "";
  return typeof v === "string" ? v : JSON.stringify(v, null, 2);
}

function tokens(s: TraceSpan): string | null {
  const u = s.result?.meta?.usage;
  if (!u || u.input_tokens == null) return null;
  return `${u.input_tokens}→${u.output_tokens ?? 0} tok`;
}

const fieldLabel: React.CSSProperties = {
  fontSize: 10.5, textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 4,
};
const sessionBadge: React.CSSProperties = {
  fontSize: 11, marginLeft: 8, padding: "1px 7px", borderRadius: 5, color: "var(--purple)",
  border: "1px solid var(--border-strong)",
};
const pre: React.CSSProperties = {
  margin: 0, padding: 10, borderRadius: 8, background: "var(--bg-2)", border: "1px solid var(--border)",
  fontSize: 12, lineHeight: 1.5, fontFamily: "var(--font-mono)", whiteSpace: "pre-wrap",
  wordBreak: "break-word", maxHeight: 240, overflowY: "auto",
};
function spanRow(active: boolean): React.CSSProperties {
  return {
    display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10, width: "100%",
    textAlign: "left", padding: "7px 8px", borderRadius: 7, cursor: "pointer", color: "var(--text)",
    background: active ? "var(--panel-2)" : "transparent", border: "1px solid transparent",
  };
}
function badge(type: string): React.CSSProperties {
  return {
    fontSize: 10, fontWeight: 600, textTransform: "uppercase", letterSpacing: 0.3,
    padding: "2px 6px", borderRadius: 5, flexShrink: 0,
    color: TYPE_COLOR[type] || "var(--muted)", border: `1px solid ${TYPE_COLOR[type] || "var(--border-strong)"}`,
  };
}
