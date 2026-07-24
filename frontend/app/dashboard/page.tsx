"use client";

import { useCallback, useEffect, useState } from "react";
import { api, Me, Metrics } from "@/lib/api";
import { estimateCost, fmtCost } from "@/lib/cost";
import AreaChart from "@/components/AreaChart";
import TrendChart from "@/components/TrendChart";
import AlertsPanel from "@/components/AlertsPanel";
import { CardGridSkeleton, Skeleton, SkeletonStyles } from "@/components/Skeleton";
import ConsoleShell from "@/components/ConsoleShell";
import GettingStarted from "@/components/GettingStarted";

const WINDOWS = [
  { label: "1h", hours: 1 }, { label: "24h", hours: 24 }, { label: "7d", hours: 168 },
  { label: "30d", hours: 720 }, { label: "90d", hours: 2160 },
];

export default function DashboardPage() {
  const [m, setM] = useState<Metrics | null>(null);
  const [me, setMe] = useState<Me | null>(null);
  const [hours, setHours] = useState(24);
  const [chart, setChart] = useState<"traffic" | "latency" | "tokens" | "cost">("traffic");
  const load = useCallback(() => { api.metrics(hours).then(setM).catch(() => {}); }, [hours]);
  useEffect(() => { load(); const t = setInterval(load, 10000); return () => clearInterval(t); }, [load]);
  useEffect(() => { api.me().then(setMe).catch(() => {}); }, []);

  // Priced from the real input/output split the API now reports. This used to assume 50/50,
  // which is wrong by a wide margin on anything input-heavy (RAG especially) since output
  // tokens cost 3-5x more — and it rendered exactly like a measured figure.
  const cost = m ? fmtCost(m.by_model.reduce(
    (n, r) => n + (estimateCost(r.model, r.input_tokens, r.output_tokens) || 0), 0) || null) : null;

  // A cost derived from calls that mostly didn't report usage is a floor, not an estimate.
  const cov = m?.usage_coverage;
  const partial = !!cov && cov.model_calls > 0 && cov.reported < cov.model_calls;
  const covPct = cov && cov.model_calls ? Math.round((cov.reported / cov.model_calls) * 100) : 100;

  return (
    <ConsoleShell>
      <div className="cs-page ov">
        {/* ── greeting banner ── */}
        <section className="ov-hero">
          <div className="ov-hero-in">
            <div>
              <div className="ov-eyebrow"><i />Production workspace</div>
              <h1>{greeting()}{me?.name ? `, ${me.name.split(" ")[0]}` : ""}.</h1>
              <p>{healthLine(m)}</p>
            </div>
            <div className="ov-hero-actions">
              <div className="ov-range">
                {WINDOWS.map((w) => (
                  <button key={w.hours} onClick={() => setHours(w.hours)} className={hours === w.hours ? "on" : ""}>{w.label}</button>
                ))}
              </div>
              <a href="/api-keys" className="btn btn-run btn-sm">Instrument agent</a>
            </div>
          </div>
        </section>

        <GettingStarted traceCount={m ? m.trace_count : null} />

        {!m ? (
          <>
            <CardGridSkeleton n={4} />
            <div style={{ ...panel, marginTop: 16 }}><Skeleton w="30%" h={10} /><Skeleton h={170} mt={14} r={10} /></div>
            <SkeletonStyles />
          </>
        ) : (
          <>
            {/* ── stat tiles with real deltas + sparklines ── */}
            <div className="ov-tiles">
              <Tile label="Total traces" icon="◇" value={m.trace_count.toLocaleString()}
                delta={deltaOf(m.series, "count")} series={m.series.map((b) => b.count)} tone="var(--blue)" />
              <Tile label="Error rate" icon="⚠" value={`${(m.error_rate * 100).toFixed(2)}%`}
                delta={deltaOf(m.series, "errors")} deltaGoodDown series={m.series.map((b) => b.errors)} tone="var(--red)" />
              <Tile label="P95 latency" icon="◷" value={fmtMs(m.latency_p95_ms)}
                delta={deltaOf(m.series, "p95")} deltaGoodDown series={m.series.map((b) => b.p95 || 0)} tone="var(--amber)" />
              <Tile label="Total cost" icon="$" value={cost || "—"}
                series={m.series.map((b) => costOfBucket(b).cost)} tone="var(--green)"
                note={partial ? `${covPct}% of calls reported usage` : undefined} />
            </div>

            {/* ── volume chart + health donut ── */}
            <div className="ov-split">
              <div style={{ ...panel }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
                <div style={{ display: "flex", gap: 3, background: "var(--bg-2)", borderRadius: 8, padding: 2 }}>
                  {(["traffic", "latency", "tokens", "cost"] as const).map((c) => (
                    <button key={c} onClick={() => setChart(c)} style={toggle(chart === c)}>
                      {c[0].toUpperCase() + c.slice(1)}
                    </button>
                  ))}
                </div>
                <div style={{ display: "flex", gap: 12, fontSize: 11, color: "var(--muted)" }}>
                  {chart === "traffic" && <><span><span style={legendDot("var(--blue)")} /> traces</span><span><span style={legendDot("var(--red)")} /> errors</span></>}
                  {chart === "latency" && <><span><span style={legendDot("var(--blue)")} /> p50</span><span><span style={legendDot("var(--amber)")} /> p95</span></>}
                  {chart === "tokens" && <span><span style={legendDot("var(--purple)")} /> tokens</span>}
                  {chart === "cost" && <span><span style={legendDot("var(--green)")} /> est. cost</span>}
                  <span style={{ opacity: 0.7 }}>{hours <= 48 ? "hourly" : "daily"}</span>
                </div>
              </div>
              {m.series.length === 0 ? (
                <div className="muted" style={{ fontSize: 13, padding: "40px 0", textAlign: "center" }}>No traces in this window.</div>
              ) : (
                <div style={{ marginTop: 10 }}>
                  {chart === "traffic" && <AreaChart data={m.series} height={170} />}
                  {chart === "latency" && (
                    <TrendChart data={m.series} height={170} fmtY={fmtMs}
                      lines={[{ key: "p50", color: "var(--blue)", label: "p50" }, { key: "p95", color: "var(--amber)", label: "p95" }]} />
                  )}
                  {chart === "tokens" && (
                    <TrendChart data={m.series} height={170} fmtY={fmtNum}
                      lines={[{ key: "tokens", color: "var(--purple)", label: "tokens" }]} />
                  )}
                  {chart === "cost" && (
                    <TrendChart data={m.series.map(costOfBucket)} height={170} fmtY={fmtUsd}
                      lines={[{ key: "cost", color: "var(--green)", label: "est. cost" }]} />
                  )}
                </div>
              )}
              </div>

              {/* trace-health donut — real success/error split */}
              <div style={panel} className="ov-health">
                <div style={label}>Trace health</div>
                <div className="muted" style={{ fontSize: 11.5, marginTop: 2 }}>{m.trace_count.toLocaleString()} total</div>
                <HealthDonut ok={m.trace_count - m.error_count} err={m.error_count} />
              </div>
            </div>

            <div style={panel}>
              <div style={label}>Top models by tokens</div>
              {m.by_model.length === 0 ? (
                <div className="muted" style={{ fontSize: 13 }}>No model calls in this window.</div>
              ) : (
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13, marginTop: 8 }}>
                  <thead>
                    <tr style={{ textAlign: "left", color: "var(--muted)", fontSize: 11.5 }}>
                      <th style={th}>Model</th><th style={th}>Calls</th><th style={th}>Tokens</th><th style={th}>Est. cost</th>
                    </tr>
                  </thead>
                  <tbody>
                    {m.by_model.map((r) => (
                      <tr key={r.model} style={{ borderTop: "1px solid var(--border)" }}>
                        <td style={{ ...td, fontFamily: "var(--font-mono)" }}>{r.model}</td>
                        <td style={td}>{r.calls.toLocaleString()}</td>
                        <td style={td}>{r.tokens.toLocaleString()}</td>
                        <td style={td}>{fmtCost(estimateCost(r.model, r.input_tokens, r.output_tokens)) || "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>

            <Failures m={m} />

            <AlertsPanel />
          </>
        )}
      </div>
    </ConsoleShell>
  );
}

// ── Overview helpers ──────────────────────────────────────────────────────
function greeting(): string {
  const h = new Date().getHours();
  return h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
}
function healthLine(m: Metrics | null): string {
  if (!m) return "Loading your reliability signals…";
  if (m.trace_count === 0) return "No traces yet — instrument an agent to start capturing evidence.";
  const fails = (m.recent_failures ?? []).length + (m.error_count || 0);
  if (fails === 0) return "Your agents are healthy. No reliability signals need attention.";
  return `Your agents are running. ${m.error_count} error${m.error_count === 1 ? "" : "s"} in this window need${m.error_count === 1 ? "s" : ""} a look.`;
}
// A real "vs previous period": compare the recent half of the series to the older half.
// One fetch, real data — no invented baseline.
function deltaOf(series: Metrics["series"], key: "count" | "errors" | "p95"): number | null {
  if (series.length < 4) return null;
  const mid = Math.floor(series.length / 2);
  const older = series.slice(0, mid), recent = series.slice(mid);
  const agg = (rows: Metrics["series"]) => key === "p95"
    ? rows.reduce((s, b) => s + (b.p95 || 0), 0) / Math.max(1, rows.length)
    : rows.reduce((s, b) => s + (b[key] || 0), 0);
  const a = agg(older), b = agg(recent);
  if (a === 0) return b === 0 ? 0 : null;
  return ((b - a) / a) * 100;
}

function Tile({ label, icon, value, delta, deltaGoodDown, series, tone, note }: {
  label: string; icon: string; value: string; delta?: number | null; deltaGoodDown?: boolean;
  series: number[]; tone: string; note?: string;
}) {
  const good = delta == null ? null : (deltaGoodDown ? delta <= 0 : delta >= 0);
  return (
    <div className="ov-tile">
      <div className="ov-tile-top">
        <span className="ov-tile-ic" style={{ color: tone, background: `color-mix(in srgb, ${tone} 14%, transparent)` }}>{icon}</span>
        <span className="ov-tile-label">{label}</span>
      </div>
      <div className="ov-tile-val">{value}</div>
      <div className="ov-tile-foot">
        {delta != null && (
          <span className={`ov-delta ${good ? "up" : "down"}`}>
            {delta >= 0 ? "↑" : "↓"} {Math.abs(delta).toFixed(1)}%
          </span>
        )}
        {note ? <span className="ov-tile-note">{note}</span>
          : delta != null && <span className="ov-tile-note">vs previous</span>}
        <Sparkline data={series} color={tone} />
      </div>
    </div>
  );
}

function Sparkline({ data, color }: { data: number[]; color: string }) {
  const w = 72, h = 26;
  if (!data.length || Math.max(...data) === 0) return <svg className="ov-spark" width={w} height={h} />;
  const max = Math.max(...data), n = data.length;
  const pts = data.map((v, i) => `${(i / (n - 1)) * w},${h - (v / max) * (h - 3) - 1.5}`).join(" ");
  return (
    <svg className="ov-spark" width={w} height={h} viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none">
      <polyline points={pts} fill="none" stroke={color} strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" opacity="0.85" />
    </svg>
  );
}

function HealthDonut({ ok, err }: { ok: number; err: number }) {
  const total = Math.max(1, ok + err);
  const pct = (ok / total) * 100;
  const r = 52, c = 2 * Math.PI * r;
  return (
    <div className="ov-donut">
      <svg viewBox="0 0 128 128">
        <circle cx="64" cy="64" r={r} fill="none" stroke="var(--panel-3)" strokeWidth="13" />
        <circle cx="64" cy="64" r={r} fill="none" stroke="var(--accent)" strokeWidth="13" strokeLinecap="round"
          strokeDasharray={c} strokeDashoffset={c * (1 - pct / 100)} transform="rotate(-90 64 64)" />
        {err > 0 && (
          <circle cx="64" cy="64" r={r} fill="none" stroke="var(--red)" strokeWidth="13"
            strokeDasharray={c} strokeDashoffset={c * (pct / 100)} transform="rotate(-90 64 64)" opacity="0.9" />
        )}
      </svg>
      <b>{pct.toFixed(1)}%<small>success</small></b>
      <div className="ov-donut-legend">
        <span><i style={{ background: "var(--accent)" }} />Success <b>{ok.toLocaleString()}</b></span>
        <span><i style={{ background: "var(--red)" }} />Error <b>{err.toLocaleString()}</b></span>
      </div>
    </div>
  );
}

const TYPE_COLOR: Record<string, string> = {
  agent: "var(--accent)", llm: "var(--blue)", tool: "var(--purple)", step: "var(--muted)",
};
function typeBadge(t: string): React.CSSProperties {
  const c = TYPE_COLOR[t] || "var(--muted)";
  return { fontSize: 9.5, fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.3,
    padding: "1px 6px", borderRadius: 4, color: c, border: `1px solid ${c}`, flexShrink: 0 };
}
function fmtMs(v: number): string {
  return v >= 1000 ? `${(v / 1000).toFixed(1)}s` : `${Math.round(v)}ms`;
}
// Price a series bucket from its per-model input/output token split, returning the bucket
// with a `cost` field for the trend chart.
function costOfBucket(b: Metrics["series"][number]): Metrics["series"][number] & { cost: number } {
  const models = b.by_model || {};
  const cost = Object.entries(models).reduce(
    (n, [model, t]) => n + (estimateCost(model, t.input_tokens, t.output_tokens) || 0), 0);
  return { ...b, cost };
}
function fmtUsd(v: number): string {
  if (v <= 0) return "$0";
  if (v < 0.01) return "<$0.01";
  return `$${v.toFixed(2)}`;
}
function fmtNum(v: number): string {
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
  if (v >= 1000) return `${(v / 1000).toFixed(v >= 10_000 ? 0 : 1)}k`;
  return `${Math.round(v)}`;
}
function relTime(iso: string): string {
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return `${Math.floor(s)}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

// "What's failing" — span-types that error, the most common messages, and the latest
// failing spans (each links straight to its trace). Only shown when there are failures.
function Failures({ m }: { m: Metrics }) {
  const byType = m.fail_by_type ?? [];
  const errors = m.top_errors ?? [];
  const recent = m.recent_failures ?? [];
  // Gate on span-level failures, not just failed root traces: a failed child span (e.g. a
  // retried tool call) inside an otherwise-successful trace is still worth surfacing here.
  const totalFails = byType.reduce((n, r) => n + r.count, 0);
  if (!totalFails) {
    return (
      <div style={{ ...panel, marginTop: 20, display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ color: "var(--green)", fontSize: 15 }}>✓</span>
        <span style={{ fontSize: 13.5 }}>No failures in this window.</span>
      </div>
    );
  }
  const maxType = Math.max(1, ...byType.map((r) => r.count));
  return (
    <div style={{ ...panel, marginTop: 20 }}>
      <div style={{ ...label, marginBottom: 12, color: "var(--red)" }}>Failures · {totalFails} span{totalFails === 1 ? "" : "s"}</div>
      <div style={{ display: "grid", gridTemplateColumns: "minmax(200px, 1fr) minmax(220px, 1.4fr)", gap: 22, alignItems: "start" }} className="fail-grid">
        {/* by span type */}
        <div>
          <div className="muted" style={{ fontSize: 11, marginBottom: 8 }}>By span type</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
            {byType.map((r) => (
              <div key={r.type} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span style={typeBadge(r.type)}>{r.type}</span>
                <span style={{ position: "relative", flex: 1, height: 8, background: "var(--bg-2)", borderRadius: 4 }}>
                  <span style={{ position: "absolute", left: 0, top: 0, height: 8, borderRadius: 4,
                    width: `${(r.count / maxType) * 100}%`, background: "var(--red)", opacity: 0.7 }} />
                </span>
                <span className="mono" style={{ fontSize: 11.5, width: 28, textAlign: "right" }}>{r.count}</span>
              </div>
            ))}
          </div>
          {errors.length > 0 && (
            <>
              <div className="muted" style={{ fontSize: 11, margin: "16px 0 8px" }}>Top errors</div>
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {errors.map((e, i) => (
                  <div key={i} style={{ display: "flex", alignItems: "baseline", gap: 7, fontSize: 12 }}>
                    <span className="mono" style={{ color: "var(--red)", flexShrink: 0 }}>{e.count}×</span>
                    <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={e.error}>{e.error}</span>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
        {/* recent failing spans → deep-link to the trace */}
        <div>
          <div className="muted" style={{ fontSize: 11, marginBottom: 8 }}>Recent failures</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {recent.map((f, i) => (
              <a key={i} href={`/traces?trace=${encodeURIComponent(f.trace_id)}`}
                style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 8px", borderRadius: 8,
                  border: "1px solid var(--border)", textDecoration: "none", color: "inherit" }}
                className="fail-row">
                <span style={typeBadge(f.type)}>{f.type}</span>
                <span style={{ fontSize: 12.5, minWidth: 0, flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {f.label || <span className="muted">span</span>}
                  {f.error && <span className="muted" style={{ fontSize: 11 }}> — {f.error}</span>}
                </span>
                <span className="muted" style={{ fontSize: 10.5, flexShrink: 0 }}>{relTime(f.at)}</span>
              </a>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function Stat({ label, value, accent, note }: { label: string; value: string; accent?: string; note?: string }) {
  return (
    <div style={panel}>
      <div className="muted" style={{ fontSize: 11.5, textTransform: "uppercase", letterSpacing: 0.4 }}>{label}</div>
      <div style={{ fontSize: 24, fontWeight: 700, marginTop: 4, color: accent }}>{value}</div>
      {/* Qualifies the number in place — a caveat somewhere else gets read as decoration. */}
      {note && <div className="muted" style={{ fontSize: 11, marginTop: 3 }}>{note}</div>}
    </div>
  );
}

const panel: React.CSSProperties = { background: "var(--panel)", border: "1px solid var(--border)", borderRadius: 12, padding: 16 };
const label: React.CSSProperties = { fontSize: 11, textTransform: "uppercase", letterSpacing: 0.4, color: "var(--muted)" };
function legendDot(c: string): React.CSSProperties {
  return { display: "inline-block", width: 8, height: 8, borderRadius: 999, background: c, marginRight: 4 };
}
const th: React.CSSProperties = { padding: "4px 8px", fontWeight: 500 };
const td: React.CSSProperties = { padding: "6px 8px" };
function toggle(active: boolean): React.CSSProperties {
  return { fontSize: 12, padding: "4px 13px", borderRadius: 6, cursor: "pointer", border: "none",
    background: active ? "var(--panel)" : "transparent", color: active ? "var(--text)" : "var(--muted)", fontWeight: active ? 600 : 400 };
}
