"use client";

import { useEffect, useState } from "react";
import { api, TraceSpan } from "@/lib/api";
import { estimateCost, fmtCost } from "@/lib/cost";
import { DiffText } from "@/components/DiffText";

const TYPE_COLOR: Record<string, string> = {
  agent: "var(--accent)", llm: "var(--blue)", tool: "var(--purple)", step: "var(--muted)",
};

function spanText(s: TraceSpan): string {
  return s.result?.text || (typeof s.result?.output === "string" ? s.result.output : "") || "";
}
function spanTokens(s: TraceSpan): number {
  const u = s.result?.meta?.usage || {};
  return (u.input_tokens || 0) + (u.output_tokens || 0);
}
function stats(spans: TraceSpan[]) {
  const ids = new Set(spans.map((s) => s.span_id));
  const root = spans.find((s) => !s.parent_span_id || !ids.has(s.parent_span_id));
  const tokens = spans.reduce((n, s) => n + spanTokens(s), 0);
  const cost = spans.reduce((n, s) => n + (estimateCost(s.request?.model, s.result?.meta?.usage?.input_tokens, s.result?.meta?.usage?.output_tokens) || 0), 0);
  return { spans: spans.length, tokens, cost, duration: root?.duration_ms || 0, status: root?.status || "—", label: root?.label || "trace" };
}

// Align two span lists by label (LCS) → matched pairs + additions/removals.
function align(A: TraceSpan[], B: TraceSpan[]): { a?: TraceSpan; b?: TraceSpan }[] {
  const n = A.length, m = B.length;
  const dp = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--)
    dp[i][j] = A[i].label === B[j].label ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  const out: { a?: TraceSpan; b?: TraceSpan }[] = [];
  let i = 0, j = 0;
  while (i < n && j < m) {
    if (A[i].label === B[j].label) { out.push({ a: A[i], b: B[j] }); i++; j++; }
    else if (dp[i + 1][j] >= dp[i][j + 1]) { out.push({ a: A[i] }); i++; }
    else { out.push({ b: B[j] }); j++; }
  }
  while (i < n) out.push({ a: A[i++] });
  while (j < m) out.push({ b: B[j++] });
  return out;
}

function delta(x: number, unit = "", inverse = false) {
  if (!x) return <span className="muted">·</span>;
  const good = inverse ? x < 0 : x > 0;
  const c = x < 0 ? "var(--green)" : "var(--red)";   // less is better for duration/tokens/cost
  return <span style={{ color: c }}>{x > 0 ? "+" : ""}{x}{unit}</span>;
}

// Side-by-side diff of two traces: top-line deltas + a span-by-span output diff.
export default function TraceCompare({ aId, bId, onClose }: { aId: string; bId: string; onClose: () => void }) {
  const [a, setA] = useState<TraceSpan[] | null>(null);
  const [b, setB] = useState<TraceSpan[] | null>(null);
  useEffect(() => { api.trace(aId).then(setA).catch(() => setA([])); }, [aId]);
  useEffect(() => { api.trace(bId).then(setB).catch(() => setB([])); }, [bId]);

  if (!a || !b) return <div className="muted" style={{ padding: 20, fontSize: 13 }}>Loading comparison…</div>;
  const sa = stats(a), sb = stats(b);
  const rows = align(a, b);

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
        <div style={{ fontSize: 14, fontWeight: 600 }}>Comparing two traces</div>
        <button className="btn btn-sm btn-ghost" onClick={onClose}>✕ Close compare</button>
      </div>

      {/* top-line stats + deltas (Δ = B − A) */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 10, marginBottom: 16 }}>
        <div style={col}><div style={colHead}>A · {sa.label}</div>
          <Stat k="duration" v={`${sa.duration}ms`} /><Stat k="spans" v={sa.spans} />
          <Stat k="tokens" v={sa.tokens.toLocaleString()} /><Stat k="cost" v={fmtCost(sa.cost) || "—"} />
          <Stat k="status" v={sa.status} /></div>
        <div style={col}><div style={colHead}>B · {sb.label}</div>
          <Stat k="duration" v={`${sb.duration}ms`} /><Stat k="spans" v={sb.spans} />
          <Stat k="tokens" v={sb.tokens.toLocaleString()} /><Stat k="cost" v={fmtCost(sb.cost) || "—"} />
          <Stat k="status" v={sb.status} /></div>
        <div style={{ ...col, borderColor: "var(--accent)" }}><div style={{ ...colHead, color: "var(--accent)" }}>Δ (B − A)</div>
          <Stat k="duration" v={delta(sb.duration - sa.duration, "ms")} />
          <Stat k="spans" v={delta(sb.spans - sa.spans)} />
          <Stat k="tokens" v={delta(sb.tokens - sa.tokens)} />
          <Stat k="cost" v={fmtCost(sb.cost - sa.cost) || <span className="muted">·</span>} />
          <Stat k="status" v={sa.status === sb.status ? <span className="muted">same</span> : <span style={{ color: "var(--amber)" }}>{sa.status}→{sb.status}</span>} /></div>
      </div>

      {/* span-by-span */}
      <div style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: 0.4, color: "var(--muted)", marginBottom: 8 }}>Spans</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {rows.map((r, i) => {
          const s = r.a || r.b!;
          const tag = !r.b ? "only in A" : !r.a ? "only in B" : null;
          const c = TYPE_COLOR[s.type] || "var(--muted)";
          const dDur = r.a && r.b ? (r.b.duration_ms || 0) - (r.a.duration_ms || 0) : 0;
          const dTok = r.a && r.b ? spanTokens(r.b) - spanTokens(r.a) : 0;
          return (
            <div key={i} style={{ border: `1px solid ${tag ? "var(--border-strong)" : "var(--border)"}`, borderRadius: 8, overflow: "hidden" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "5px 10px", background: "var(--bg-2)" }}>
                <span style={{ fontSize: 9.5, fontWeight: 700, textTransform: "uppercase", padding: "1px 5px", borderRadius: 4, color: c, border: `1px solid ${c}` }}>{s.type}</span>
                <span style={{ fontSize: 12.5, fontWeight: 500, flex: 1 }}>{s.label}</span>
                {tag ? <span style={{ fontSize: 10.5, color: !r.b ? "var(--red)" : "var(--green)" }}>{tag}</span>
                  : <span className="muted mono" style={{ fontSize: 10.5 }}>Δ {delta(dDur, "ms")} · {delta(dTok, " tok")}</span>}
              </div>
              <div style={{ padding: "8px 10px", fontSize: 12.5, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
                {r.a && r.b ? <DiffText from={spanText(r.a)} to={spanText(r.b)} />
                  : <span style={{ color: !r.b ? "var(--red)" : "var(--green)" }}>{spanText(s) || <span className="muted">—</span>}</span>}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function Stat({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12.5, padding: "3px 0" }}>
      <span className="muted">{k}</span><span style={{ fontFamily: "var(--font-mono)" }}>{v}</span>
    </div>
  );
}
const col: React.CSSProperties = { border: "1px solid var(--border)", borderRadius: 10, padding: "10px 12px", background: "var(--panel)" };
const colHead: React.CSSProperties = { fontSize: 12, fontWeight: 600, marginBottom: 6, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" };
