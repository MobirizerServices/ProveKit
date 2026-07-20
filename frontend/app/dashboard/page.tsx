"use client";

import { useCallback, useEffect, useState } from "react";
import { api, Metrics } from "@/lib/api";
import { estimateCost, fmtCost } from "@/lib/cost";
import AreaChart from "@/components/AreaChart";
import AlertsPanel from "@/components/AlertsPanel";
import { CardGridSkeleton, Skeleton, SkeletonStyles } from "@/components/Skeleton";
import TopNav from "@/components/TopNav";

const WINDOWS = [
  { label: "1h", hours: 1 }, { label: "24h", hours: 24 }, { label: "7d", hours: 168 },
  { label: "30d", hours: 720 }, { label: "90d", hours: 2160 },
];

export default function DashboardPage() {
  const [m, setM] = useState<Metrics | null>(null);
  const [hours, setHours] = useState(24);
  const load = useCallback(() => { api.metrics(hours).then(setM).catch(() => {}); }, [hours]);
  useEffect(() => { load(); const t = setInterval(load, 10000); return () => clearInterval(t); }, [load]);

  const cost = m ? fmtCost(m.by_model.reduce((n, r) => {
    // approximate: split tokens 50/50 in/out for the estimate
    return n + (estimateCost(r.model, Math.round(r.tokens / 2), Math.round(r.tokens / 2)) || 0);
  }, 0) || null) : null;

  return (
    <>
      <TopNav />
      <main style={{ maxWidth: 1100, margin: "0 auto", padding: "24px 20px 80px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
          <div>
            <h1 style={{ fontSize: 22, margin: "0 0 4px" }}>Dashboard</h1>
            <p className="muted" style={{ margin: 0, fontSize: 13.5 }}>Volume, errors, latency, and token usage across your traces.</p>
          </div>
          <div style={{ display: "flex", gap: 3, background: "var(--bg-2)", borderRadius: 8, padding: 2 }}>
            {WINDOWS.map((w) => (
              <button key={w.hours} onClick={() => setHours(w.hours)} style={toggle(hours === w.hours)}>{w.label}</button>
            ))}
          </div>
        </div>

        {!m ? (
          <>
            <CardGridSkeleton n={6} />
            <div style={{ ...panel, marginTop: 20 }}><Skeleton w="30%" h={10} /><Skeleton h={170} mt={14} r={10} /></div>
            <SkeletonStyles />
          </>
        ) : (
          <>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 12, marginBottom: 20 }}>
              <Stat label="Traces" value={m.trace_count.toLocaleString()} />
              <Stat label="Error rate" value={`${(m.error_rate * 100).toFixed(1)}%`} accent={m.error_rate > 0 ? "var(--red)" : undefined} />
              <Stat label="Latency p50" value={`${m.latency_p50_ms} ms`} />
              <Stat label="Latency p95" value={`${m.latency_p95_ms} ms`} />
              <Stat label="Tokens" value={m.total_tokens.toLocaleString()} />
              <Stat label="Est. cost" value={cost || "—"} />
            </div>

            <div style={{ ...panel, marginBottom: 20 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <div style={label}>Traffic {hours <= 48 ? "(hourly)" : "(daily)"}</div>
                <div style={{ display: "flex", gap: 12, fontSize: 11, color: "var(--muted)" }}>
                  <span><span style={legendDot("var(--blue)")} /> traces</span>
                  <span><span style={legendDot("var(--red)")} /> errors</span>
                </div>
              </div>
              {m.series.length === 0 ? (
                <div className="muted" style={{ fontSize: 13, padding: "40px 0", textAlign: "center" }}>No traces in this window.</div>
              ) : (
                <div style={{ marginTop: 10 }}><AreaChart data={m.series} height={170} /></div>
              )}
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
                        <td style={td}>{fmtCost(estimateCost(r.model, Math.round(r.tokens / 2), Math.round(r.tokens / 2))) || "—"}</td>
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
      </main>
    </>
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

function Stat({ label, value, accent }: { label: string; value: string; accent?: string }) {
  return (
    <div style={panel}>
      <div className="muted" style={{ fontSize: 11.5, textTransform: "uppercase", letterSpacing: 0.4 }}>{label}</div>
      <div style={{ fontSize: 24, fontWeight: 700, marginTop: 4, color: accent }}>{value}</div>
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
