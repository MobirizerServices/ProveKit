"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { api, TraceSpan } from "@/lib/api";
import { estimateCost, fmtCost } from "@/lib/cost";
import { DiffText } from "@/components/DiffText";
import {
  AlignedNode, DiffKind, REASON_LABEL, alignTraces, countKinds, firstDivergence, flattenAligned,
  spanOutput,
} from "@/lib/traceDiff";

const TYPE_COLOR: Record<string, string> = {
  agent: "var(--accent)", llm: "var(--blue)", tool: "var(--purple)", step: "var(--muted)",
};
const KIND_COLOR: Record<DiffKind, string> = {
  same: "var(--border)", changed: "var(--amber)", "only-a": "var(--red)", "only-b": "var(--green)",
};
const KIND_LABEL: Record<DiffKind, string> = {
  same: "same", changed: "changed", "only-a": "only in A", "only-b": "only in B",
};

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

function delta(x: number, unit = "") {
  if (!x) return <span className="muted">·</span>;
  const c = x < 0 ? "var(--green)" : "var(--red)";   // less is better for duration/tokens/cost
  return <span style={{ color: c }}>{x > 0 ? "+" : ""}{x}{unit}</span>;
}

const side = (n: AlignedNode): TraceSpan => (n.b || n.a)!;

// Structural diff of two traces: top-line deltas, a root-cause callout for the first place the
// runs diverge (#59), and the two span trees aligned into one classified tree (#58). What does
// and does not count as divergence is defined in lib/traceDiff.ts — briefly: behaviour does,
// timing doesn't.
export default function TraceCompare({ aId, bId, onClose }: { aId: string; bId: string; onClose: () => void }) {
  const [a, setA] = useState<TraceSpan[] | null>(null);
  const [b, setB] = useState<TraceSpan[] | null>(null);
  const [onlyDiffs, setOnlyDiffs] = useState(true);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [flash, setFlash] = useState<string | null>(null);
  const rowRefs = useRef<Record<string, HTMLDivElement | null>>({});

  useEffect(() => { api.trace(aId).then(setA).catch(() => setA([])); }, [aId]);
  useEffect(() => { api.trace(bId).then(setB).catch(() => setB([])); }, [bId]);
  useEffect(() => {
    if (!flash) return;
    const t = setTimeout(() => setFlash(null), 1800);
    return () => clearTimeout(t);
  }, [flash]);

  const tree = useMemo(() => (a && b ? alignTraces(a, b) : []), [a, b]);
  const found = useMemo(() => firstDivergence(tree), [tree]);
  const counts = useMemo(() => countKinds(tree), [tree]);
  // Filtering to differences is the default, but it can't be in force when there are none —
  // that would answer "did anything change?" with a blank panel.
  const filtered = onlyDiffs && !!found;
  const rows = useMemo(() => flattenAligned(tree, filtered), [tree, filtered]);

  if (!a || !b) return <div className="muted" style={{ padding: 20, fontSize: 13 }}>Loading comparison…</div>;
  const sa = stats(a), sb = stats(b);

  const jump = (key: string) => {
    setExpanded((e) => ({ ...e, [key]: true }));
    setFlash(key);
    rowRefs.current[key]?.scrollIntoView({ behavior: "smooth", block: "center" });
  };

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
        <div style={{ fontSize: 14, fontWeight: 600 }}>Comparing two traces</div>
        <button className="btn btn-sm btn-ghost" onClick={onClose}>✕ Close compare</button>
      </div>

      {found
        ? <FirstDivergence found={found} statusA={sa.status} statusB={sb.status} onJump={() => jump(found.node.key)} />
        : <div style={{ ...callout, borderColor: "var(--green)", background: "color-mix(in srgb, var(--green) 7%, var(--panel))" }}>
            <div style={{ fontSize: 12.5, fontWeight: 600, color: "var(--green)" }}>✓ No divergence</div>
            <div className="muted" style={{ fontSize: 12.5, marginTop: 3 }}>
              Both runs took the same path and produced the same outputs. Only timing and token counts differ.
            </div>
          </div>}

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

      <div style={{ display: "flex", alignItems: "baseline", gap: 10, marginBottom: 8 }}>
        <div style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: 0.4, color: "var(--muted)" }}>Aligned spans</div>
        <div className="muted" style={{ fontSize: 11.5, flex: 1 }}>
          {counts.changed} changed · {counts.onlyA} only in A · {counts.onlyB} only in B · {counts.same} unchanged
        </div>
        {!!found && (
          <button className="btn btn-sm btn-ghost" onClick={() => setOnlyDiffs((v) => !v)}
            title="Hide spans whose subtree is identical in both runs">
            {filtered ? "Show all spans" : "Only differences"}
          </button>
        )}
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {rows.map((n) => (
          <Row key={n.key} n={n} isFirst={found?.node.key === n.key} flash={flash === n.key}
            open={expanded[n.key] ?? n.kind !== "same"}
            onToggle={() => setExpanded((e) => ({ ...e, [n.key]: !(e[n.key] ?? n.kind !== "same") }))}
            bind={(el) => { rowRefs.current[n.key] = el; }} />
        ))}
        {!rows.length && <div className="muted" style={{ fontSize: 12.5 }}>No spans to show.</div>}
      </div>
    </div>
  );
}

// The root-cause hint: the innermost span that went off-script, with the path that led to it.
function FirstDivergence({ found, statusA, statusB, onJump }: {
  found: { node: AlignedNode; ancestors: AlignedNode[] }; statusA: string; statusB: string; onJump: () => void;
}) {
  const { node, ancestors } = found;
  const s = side(node);
  const why = node.kind === "only-a" ? "A ran this span; B never did."
    : node.kind === "only-b" ? "B ran this span; A never did."
    : node.reasons.map((r) => REASON_LABEL[r]).join(" · ");
  const path = [...ancestors.map((n) => side(n).label), s.label];

  return (
    <div style={{ ...callout, borderColor: "var(--amber)", background: "color-mix(in srgb, var(--amber) 7%, var(--panel))" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <div style={{ fontSize: 12.5, fontWeight: 600, color: "var(--amber)" }}>⚠ First divergence</div>
        {statusA !== statusB && <div className="muted" style={{ fontSize: 11.5 }}>A {statusA} · B {statusB}</div>}
        <div style={{ flex: 1 }} />
        <button className="btn btn-sm btn-ghost" onClick={onJump}>Jump to span ↓</button>
      </div>
      <div className="mono" style={{ fontSize: 11.5, color: "var(--muted)", margin: "6px 0 2px", wordBreak: "break-word" }}>
        {path.map((p, i) => <span key={i}>{i > 0 && <span style={{ opacity: 0.5 }}> › </span>}
          <span style={{ color: i === path.length - 1 ? "var(--text)" : undefined }}>{p}</span></span>)}
      </div>
      <div style={{ fontSize: 12.5 }}>
        <span style={{ color: KIND_COLOR[node.kind], fontWeight: 600 }}>{KIND_LABEL[node.kind]}</span>
        <span className="muted"> — {why}</span>
      </div>
      <div className="muted" style={{ fontSize: 11.5, marginTop: 6 }}>
        Everything above this span differs as a consequence; this is the deepest span whose own
        children still agree.
      </div>
    </div>
  );
}

function Row({ n, isFirst, flash, open, onToggle, bind }: {
  n: AlignedNode; isFirst: boolean; flash: boolean; open: boolean;
  onToggle: () => void; bind: (el: HTMLDivElement | null) => void;
}) {
  const s = side(n);
  const c = TYPE_COLOR[s.type] || "var(--muted)";
  const border = isFirst ? "var(--accent)" : KIND_COLOR[n.kind];
  const dDur = n.a && n.b ? (n.b.duration_ms || 0) - (n.a.duration_ms || 0) : 0;
  const dTok = n.a && n.b ? spanTokens(n.b) - spanTokens(n.a) : 0;
  const relabelled = n.a && n.b && n.a.label !== n.b.label;

  return (
    <div ref={bind} style={{
      marginLeft: n.depth * 16, border: `1px solid ${border}`, borderRadius: 8, overflow: "hidden",
      boxShadow: flash ? "0 0 0 2px var(--accent-ring)" : undefined, transition: "box-shadow .3s",
    }}>
      <div onClick={onToggle} style={{ display: "flex", alignItems: "center", gap: 8, padding: "5px 10px", background: "var(--bg-2)", cursor: "pointer" }}>
        <span style={{ fontSize: 9.5, fontWeight: 700, textTransform: "uppercase", padding: "1px 5px", borderRadius: 4, color: c, border: `1px solid ${c}` }}>{s.type}</span>
        <span style={{ fontSize: 12.5, fontWeight: 500, flex: 1, minWidth: 0 }}>
          {relabelled ? <><span style={{ color: "var(--red)" }}>{n.a!.label}</span> → {n.b!.label}</> : s.label}
        </span>
        {isFirst && <span style={{ fontSize: 10, fontWeight: 700, color: "var(--accent)" }}>1st divergence</span>}
        {n.kind === "same"
          ? <span className="muted mono" style={{ fontSize: 10.5 }}>Δ {delta(dDur, "ms")} · {delta(dTok, " tok")}</span>
          : <span style={{ fontSize: 10.5, color: KIND_COLOR[n.kind] }}>
              {n.kind === "changed" ? n.reasons.map((r) => REASON_LABEL[r]).join(", ") : KIND_LABEL[n.kind]}
            </span>}
      </div>
      {open && (
        <div style={{ padding: "8px 10px", fontSize: 12.5, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
          {n.reasons.includes("model") && (
            <div className="mono" style={{ fontSize: 11.5, marginBottom: 6 }}>
              <span className="muted">model </span>
              <span style={{ color: "var(--red)" }}>{n.a!.request?.model || "—"}</span> → <span style={{ color: "var(--green)" }}>{n.b!.request?.model || "—"}</span>
            </div>
          )}
          {n.reasons.includes("input") && (
            <div style={{ marginBottom: 6 }}>
              <div className="muted" style={{ fontSize: 10.5, textTransform: "uppercase", letterSpacing: 0.4 }}>input</div>
              <DiffText from={n.a!.request?.input || ""} to={n.b!.request?.input || ""} />
            </div>
          )}
          {n.a && n.b
            ? <><div className="muted" style={{ fontSize: 10.5, textTransform: "uppercase", letterSpacing: 0.4 }}>output</div>
                <DiffText from={spanOutput(n.a)} to={spanOutput(n.b)} /></>
            : <span style={{ color: KIND_COLOR[n.kind] }}>{spanOutput(s) || <span className="muted">—</span>}</span>}
        </div>
      )}
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
const callout: React.CSSProperties = { border: "1px solid var(--border)", borderRadius: 10, padding: "10px 12px", marginBottom: 14 };
