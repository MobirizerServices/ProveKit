"use client";

import { useCallback, useEffect, useState } from "react";
import { api, Metrics } from "@/lib/api";
import { estimateCost, fmtCost } from "@/lib/cost";
import AreaChart from "@/components/AreaChart";
import { CardGridSkeleton, Skeleton, SkeletonStyles } from "@/components/Skeleton";
import TopNav from "@/components/TopNav";

const WINDOWS = [
  { label: "24h", hours: 24 }, { label: "7 days", hours: 168 }, { label: "30 days", hours: 720 },
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
          </>
        )}
      </main>
    </>
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
