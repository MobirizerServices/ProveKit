"use client";

import { useEffect, useState } from "react";
import { api, Feedback, TraceSpan } from "@/lib/api";
import { estimateCost, fmtCost } from "@/lib/cost";
import TraceGraph, { heatColor } from "@/components/TraceGraph";

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
  const [inspectorOpen, setInspectorOpen] = useState(true);
  const totalTok = spans.reduce((n, s) => n + (s.result?.meta?.usage?.input_tokens || 0) + (s.result?.meta?.usage?.output_tokens || 0), 0);
  const totalCost = fmtCost(spans.reduce((n, s) => n + (estimateCost(s.request?.model, s.result?.meta?.usage?.input_tokens, s.result?.meta?.usage?.output_tokens) || 0), 0) || null);
  const sel = spans.find((s) => s.span_id === picked) || root;

  return (
    <div>
      {/* Header: name + status-chip bar + view toggle */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10, marginBottom: 10, paddingBottom: 8, borderBottom: "1px solid var(--border)", flexWrap: "wrap" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0, flexWrap: "wrap" }}>
          <span style={{ fontSize: 14, fontWeight: 600 }}>{root?.label || "trace"}</span>
          <span style={chip()}>{spans.length} spans</span>
          <span style={chip()}>{root?.duration_ms ?? 0}ms</span>
          {totalTok ? <span style={chip()}>{totalTok.toLocaleString()} tok</span> : null}
          {totalCost ? <span style={chip()}>{totalCost}</span> : null}
          <span style={chip(root?.status === "failed" ? "var(--red)" : "var(--green)")}>{root?.status ?? "—"}</span>
          {root?.session_id && <span style={chip("var(--purple)")} title="session / thread">◆ {root.session_id}</span>}
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
        // Full-height studio: canvas fills the space, a resizable/collapsible inspector on the right.
        <div className="flow-studio" style={{ display: "flex", height: "62vh", minHeight: 420, border: "1px solid var(--border)", borderRadius: 10, overflow: "hidden", position: "relative" }}>
          <div className="flow-canvas" style={{ flex: 1, minWidth: 0, position: "relative" }}>
            <TraceGraph spans={spans} selected={picked} onSelect={setPicked} fill />
          </div>
          {/* collapse toggle on the divider */}
          <button className="flow-collapse-btn" onClick={() => setInspectorOpen((o) => !o)} title={inspectorOpen ? "Hide inspector" : "Show inspector"}
            style={{ ...collapseBtn, right: inspectorOpen ? 388 : 8 }}>{inspectorOpen ? "›" : "‹"}</button>
          {inspectorOpen && (
            <div className="flow-inspector" style={{ width: 380, flexShrink: 0, borderLeft: "1px solid var(--border)", overflowY: "auto", background: "var(--panel)" }}>
              {sel ? <Inspector span={sel} traceId={traceId} readOnly={readOnly} /> : <div className="muted" style={{ padding: 16, fontSize: 13 }}>Click a node to inspect it.</div>}
            </div>
          )}
        </div>
      ) : (
        <Tree spans={spans} />
      )}

      {!readOnly && traceId && <FeedbackPanel traceId={traceId} />}
    </div>
  );
}

// Right-hand node inspector — tabbed (Output / Raw / Node / Logs) with per-node CTAs.
function Inspector({ span: s, traceId, readOnly }: { span: TraceSpan; traceId?: string; readOnly?: boolean }) {
  const [tab, setTab] = useState<"output" | "raw" | "node" | "logs">("output");
  const meta = s.result?.meta || {};
  const params = meta.params || {};
  const events: any[] = Array.isArray(meta.events) ? meta.events : [];
  const cost = fmtCost(estimateCost(s.request?.model, s.result?.meta?.usage?.input_tokens, s.result?.meta?.usage?.output_tokens));
  const copy = (v: any) => navigator.clipboard?.writeText(typeof v === "string" ? v : JSON.stringify(v, null, 2));

  const rows: [string, React.ReactNode][] = [
    ["type", s.type],
    ["status", <span style={{ color: s.status === "failed" ? "var(--red)" : "var(--green)" }}>{s.status}</span>],
    ["duration", `${s.duration_ms} ms`],
  ];
  if (s.request?.provider) rows.push(["provider", s.request.provider]);
  if (s.request?.model) rows.push(["model", s.request.model]);
  if (s.request?.operation) rows.push(["operation", s.request.operation]);
  if (params.temperature != null) rows.push(["temperature", String(params.temperature)]);
  if (params.top_p != null) rows.push(["top_p", String(params.top_p)]);
  if (params.max_tokens != null) rows.push(["max_tokens", String(params.max_tokens)]);
  if (meta.finish_reason != null) rows.push(["finish_reason", String(meta.finish_reason)]);
  if (tokens(s)) rows.push(["tokens", tokens(s)]);
  if (cost) rows.push(["est. cost", cost]);
  if (s.span_id) rows.push(["span id", <span className="mono" style={{ fontSize: 11 }}>{s.span_id}</span>]);
  if (s.session_id) rows.push(["session", s.session_id]);

  const tabs: [typeof tab, string, number?][] = [
    ["output", "Output"], ["raw", "Raw"], ["node", "Node"], ["logs", "Logs", events.length],
  ];

  return (
    <div>
      <div style={{ position: "sticky", top: 0, background: "var(--panel)", padding: "12px 14px 0", zIndex: 1 }}>
        <div style={{ fontSize: 13, fontWeight: 600, display: "flex", alignItems: "center", gap: 7 }}>
          <span style={insBadge(s.type, s.status)}>{s.type}</span>
          <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.label}</span>
        </div>
        <div style={{ display: "flex", gap: 2, marginTop: 10, borderBottom: "1px solid var(--border)" }}>
          {tabs.map(([t, label, n]) => (
            <button key={t} onClick={() => setTab(t)} style={insTab(tab === t)}>
              {label}{n ? <span style={{ marginLeft: 4, fontSize: 9.5, color: "var(--muted)" }}>{n}</span> : null}
            </button>
          ))}
        </div>
      </div>

      <div style={{ padding: 14 }}>
        {tab === "output" && (
          <>
            <IO label="Input" value={s.request?.input} />
            <IO label="Output" value={s.result?.text} />
            {(s.error || s.status === "failed") && <ErrorBlock error={s.error} />}
          </>
        )}
        {tab === "raw" && (
          <pre style={{ ...pre, maxHeight: "48vh" }}>{JSON.stringify({ request: s.request, result: s.result }, null, 2)}</pre>
        )}
        {tab === "node" && (
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12.5 }}>
            <tbody>
              {rows.map(([k, v], i) => (
                <tr key={i} style={{ borderTop: i ? "1px solid var(--border)" : "none" }}>
                  <td style={{ padding: "7px 0", color: "var(--muted)", width: "42%" }}>{k}</td>
                  <td style={{ padding: "7px 0", textAlign: "right", fontFamily: "var(--font-mono)" }}>{v}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {tab === "logs" && (
          events.length ? (
            <div style={{ ...pre, padding: 8 }}>
              {events.map((e, i) => (
                <div key={i} style={{ display: "flex", gap: 8 }}>
                  <span style={{ color: LOG_COLOR[e.level] || "var(--muted)", fontWeight: 600, minWidth: 44 }}>{e.level}</span>
                  <span>{e.name}</span>
                </div>
              ))}
            </div>
          ) : <div className="muted" style={{ fontSize: 12.5 }}>No logs on this span.</div>
        )}

        {/* per-node CTAs */}
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 14, paddingTop: 12, borderTop: "1px solid var(--border)" }}>
          <button className="btn btn-sm" onClick={() => copy(s.result?.text ?? s.request?.input ?? "")}>Copy I/O</button>
          <button className="btn btn-sm" onClick={() => copy({ request: s.request, result: s.result })}>Copy JSON</button>
          {!readOnly && traceId && <ScoreButtons traceId={traceId} />}
        </div>
      </div>
    </div>
  );
}

function ScoreButtons({ traceId }: { traceId: string }) {
  const [done, setDone] = useState("");
  const send = async (value: string) => {
    try { await api.addFeedback(traceId, { name: "thumbs", value }); setDone(value === "up" ? "👍" : "👎"); setTimeout(() => setDone(""), 1500); } catch { /* ignore */ }
  };
  return (
    <>
      <button className="btn btn-sm" onClick={() => send("up")}>👍</button>
      <button className="btn btn-sm" onClick={() => send("down")}>👎</button>
      {done && <span style={{ fontSize: 12, alignSelf: "center" }}>{done} saved</span>}
    </>
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

// Compact duration label: "840ms", "1.2s", "12s".
function fmtDur(ms: number): string {
  if (ms >= 1000) return `${(ms / 1000).toFixed(ms >= 10000 ? 0 : 1)}s`;
  return `${Math.round(ms)}ms`;
}

function Tree({ spans }: { spans: TraceSpan[] }) {
  const [open, setOpen] = useState<string | null>(spans[0]?.span_id ?? null);
  const [heat, setHeat] = useState(false);
  const maxDur = Math.max(1, ...spans.map((s) => s.duration_ms || 0));
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
  const hasReal = starts.length > 0;
  const t0 = starts.length ? starts.reduce((a, b) => (b < a ? b : a)) : 0n;

  // Synthetic fallback timing: when spans carry no wall-clock timestamps we still want a
  // readable waterfall, so lay siblings out sequentially (each starts when the previous ends)
  // nested under their parent's start. It's an approximation — flagged in the UI below —
  // because without timestamps we can't know which siblings actually ran in parallel.
  const synth: Record<string, number> = {};
  {
    let cursor = 0;
    const layout = (s: TraceSpan, start: number) => {
      synth[s.span_id] = start;
      let c = start;
      for (const ch of kids[s.span_id] || []) { layout(ch, c); c += ch.duration_ms || 0; }
    };
    for (const r of kids["__root__"] || []) { layout(r, cursor); cursor += r.duration_ms || 0; }
  }

  // A span's start offset (ms from trace start): real timestamp if present, else synthetic.
  const offsetMs = (s: TraceSpan): number => {
    const st = startNs(s);
    if (st !== null) return Number(st - t0) / 1e6;
    return synth[s.span_id] ?? 0;
  };
  const totalMs = Math.max(1, ...spans.map((s) => offsetMs(s) + (s.duration_ms || 0)));

  const bar = (s: TraceSpan) => {
    const left = (offsetMs(s) / totalMs) * 100;
    const width = Math.max(((s.duration_ms || 0) / totalMs) * 100, 0.8);
    return { left: Math.min(left, 99.2), width: Math.min(width, 100 - Math.min(left, 99.2)) };
  };

  const ticks = [0, 0.25, 0.5, 0.75, 1];
  // Vertical gridlines at each quarter, drawn behind every bar track so they line up.
  const gridBg = "repeating-linear-gradient(90deg, transparent 0, transparent calc(25% - 1px), var(--border) calc(25% - 1px), var(--border) 25%)";

  const render = (parent: string, depth: number): React.ReactNode =>
    (kids[parent] || []).map((s) => {
      const b = bar(s);
      const off = offsetMs(s);
      const pct = Math.round(((s.duration_ms || 0) / totalMs) * 100);
      const failed = s.status === "failed";
      return (
        <div key={s.span_id}>
          <button onClick={() => setOpen(open === s.span_id ? null : s.span_id)} style={spanRow(open === s.span_id)}>
            <span style={{ paddingLeft: depth * 16, display: "inline-flex", alignItems: "center", gap: 8, minWidth: 0, flex: "0 0 42%" }}>
              <span style={badge(s.type)}>{s.type}</span>
              <span style={{ fontSize: 12.5, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.label}</span>
            </span>
            <span title={`start +${fmtDur(off)} · ${s.duration_ms}ms · ${pct}% of trace`}
              style={{ position: "relative", flex: 1, height: 16, background: "var(--bg-2)", backgroundImage: gridBg, borderRadius: 4 }}>
              <span style={{ position: "absolute", top: 3, height: 10, borderRadius: 3,
                left: `${b.left}%`, width: `${b.width}%`, minWidth: 3,
                background: failed ? "var(--red)" : heat ? heatColor((s.duration_ms || 0) / maxDur) : (TYPE_COLOR[s.type] || "var(--muted)"),
                opacity: 0.9, boxShadow: open === s.span_id ? "0 0 0 1px var(--text)" : "none" }} />
            </span>
            <span style={{ display: "inline-flex", alignItems: "center", gap: 8, flexShrink: 0 }}>
              {tokens(s) && <span className="muted mono" style={{ fontSize: 10.5 }} title="input → output tokens">{tokens(s)}</span>}
              <span className="mono" style={{ fontSize: 11, width: 58, textAlign: "right", color: failed ? "var(--red)" : "var(--muted)" }}>{fmtDur(s.duration_ms || 0)}</span>
            </span>
          </button>
          {open === s.span_id && (
            <div style={{ padding: `4px 0 10px ${depth * 16 + 14}px` }}>
              {s.request?.model && <div className="muted mono" style={{ fontSize: 11.5, marginBottom: 6 }}>{s.request.model}</div>}
              <IO label="Input" value={s.request?.input} />
              <IO label="Output" value={s.result?.text} />
              {(s.error || failed) && <ErrorBlock error={s.error} />}
            </div>
          )}
          {render(s.span_id, depth + 1)}
        </div>
      );
    });

  return (
    <div>
      {/* toolbar: latency-heat toggle (mirrors the flow graph), with a legend when on */}
      <div style={{ display: "flex", justifyContent: "flex-end", alignItems: "center", gap: 10, marginBottom: 8 }}>
        {heat && (
          <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 10.5, color: "var(--muted)" }}>
            <span>fast</span>
            <span style={{ width: 54, height: 7, borderRadius: 4, background: `linear-gradient(90deg, ${heatColor(0)}, ${heatColor(0.5)}, ${heatColor(1)})` }} />
            <span>slow · {fmtDur(maxDur)}</span>
          </div>
        )}
        {spans.length > 1 && (
          <button onClick={() => setHeat((v) => !v)} title="Colour bars by latency" style={toggleBtn(heat)}>{heat ? "Heat ✓" : "Heat"}</button>
        )}
      </div>
      {/* time ruler aligned with the bar tracks */}
      <div style={{ display: "flex", alignItems: "center", padding: "0 0 6px", fontSize: 10, color: "var(--muted)" }}>
        <span style={{ flex: "0 0 42%" }} />
        <span style={{ position: "relative", flex: 1, height: 12 }}>
          {ticks.map((f) => (
            <span key={f} style={{ position: "absolute", left: `${f * 100}%`,
              transform: f === 1 ? "translateX(-100%)" : f === 0 ? "none" : "translateX(-50%)", whiteSpace: "nowrap" }}>
              {fmtDur(f * totalMs)}
            </span>
          ))}
        </span>
        <span style={{ flex: "0 0 82px" }} />
      </div>
      {render("__root__", 0)}
      {!hasReal && (
        <div className="muted" style={{ fontSize: 11, marginTop: 12, display: "flex", alignItems: "flex-start", gap: 6, lineHeight: 1.5 }}>
          <span style={{ flexShrink: 0 }}>ⓘ</span>
          <span>Approximate timing — no per-span timestamps were captured, so siblings are laid out sequentially. Absolute offsets may differ if some spans actually ran in parallel.</span>
        </div>
      )}
    </div>
  );
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
function chip(color?: string): React.CSSProperties {
  return {
    fontSize: 11, padding: "2px 8px", borderRadius: 999, color: color || "var(--muted)",
    border: `1px solid ${color ? color : "var(--border)"}`, background: "var(--bg-2)", whiteSpace: "nowrap",
  };
}
const collapseBtn: React.CSSProperties = {
  position: "absolute", top: 10, zIndex: 5, width: 22, height: 22, borderRadius: 6,
  border: "1px solid var(--border-strong)", background: "var(--panel)", color: "var(--muted)",
  cursor: "pointer", fontSize: 14, lineHeight: 1, display: "grid", placeItems: "center",
};
function insBadge(type: string, status: string): React.CSSProperties {
  const c = status === "failed" ? "var(--red)" : (TYPE_COLOR[type] || "var(--muted)");
  return { fontSize: 9.5, fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.3,
    padding: "1px 5px", borderRadius: 4, color: c, border: `1px solid ${c}`, flexShrink: 0 };
}
function insTab(active: boolean): React.CSSProperties {
  return { fontSize: 12, padding: "6px 10px", background: "none", border: "none", cursor: "pointer",
    color: active ? "var(--text)" : "var(--muted)", fontWeight: active ? 600 : 400,
    borderBottom: `2px solid ${active ? "var(--accent)" : "transparent"}`, marginBottom: -1 };
}
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
