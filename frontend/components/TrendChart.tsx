"use client";

import { useState } from "react";

export interface TrendLine { key: string; color: string; label: string }

// A dependency-free multi-line time series: gridlines, y-ticks, x labels, hover crosshair +
// tooltip. Shares the visual language of AreaChart but plots one or more arbitrary numeric
// keys (e.g. latency p50/p95, tokens) instead of the fixed count/errors area.
export default function TrendChart({ data, lines, height = 170, fmtY }: {
  data: Record<string, any>[]; lines: TrendLine[]; height?: number; fmtY?: (v: number) => string;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const W = 800, H = height, PAD = { l: 42, r: 10, t: 12, b: 22 };
  const iw = W - PAD.l - PAD.r, ih = H - PAD.t - PAD.b;
  const n = data.length;
  const max = Math.max(1, ...data.flatMap((d) => lines.map((l) => d[l.key] || 0)));
  const x = (i: number) => PAD.l + (n <= 1 ? iw / 2 : (i / (n - 1)) * iw);
  const y = (v: number) => PAD.t + ih - (v / max) * ih;
  const fy = fmtY || ((v: number) => `${v}`);

  const path = (key: string) =>
    data.map((d, i) => `${i === 0 ? "M" : "L"} ${x(i).toFixed(1)} ${y(d[key] || 0).toFixed(1)}`).join(" ");
  const ticks = [0, Math.round(max / 2), max].filter((v, i, a) => a.indexOf(v) === i);
  const fmtLabel = (t: string) => (t.includes("T") ? t.slice(11, 16) : t.slice(5));

  return (
    <div style={{ position: "relative", width: "100%" }}>
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" style={{ width: "100%", height, display: "block" }}
        onMouseLeave={() => setHover(null)}
        onMouseMove={(e) => {
          const r = (e.currentTarget as SVGSVGElement).getBoundingClientRect();
          const px = ((e.clientX - r.left) / r.width) * W;
          let best = 0, bd = Infinity;
          for (let i = 0; i < n; i++) { const d = Math.abs(x(i) - px); if (d < bd) { bd = d; best = i; } }
          setHover(best);
        }}>
        {ticks.map((v) => (
          <g key={v}>
            <line x1={PAD.l} x2={W - PAD.r} y1={y(v)} y2={y(v)} stroke="var(--border)" strokeWidth="1" />
            <text x={PAD.l - 6} y={y(v) + 3} textAnchor="end" fontSize="10" fill="var(--muted)">{fy(v)}</text>
          </g>
        ))}
        {/* A single bucket can't form a line — draw a dot per series so it's still visible. */}
        {n === 1
          ? lines.map((l) => <circle key={l.key} cx={x(0)} cy={y(data[0][l.key] || 0)} r="3.5" fill={l.color} />)
          : lines.map((l) => (
              <g key={l.key}>
                <path d={path(l.key)} fill="none" stroke={l.color} strokeWidth="2" />
                {data.map((d, i) => <circle key={i} cx={x(i)} cy={y(d[l.key] || 0)} r="2" fill={l.color} />)}
              </g>
            ))}
        {[0, Math.floor((n - 1) / 2), n - 1].filter((v, i, a) => n > 0 && a.indexOf(v) === i).map((i) => (
          <text key={i} x={x(i)} y={H - 6} textAnchor="middle" fontSize="10" fill="var(--muted)">{fmtLabel(data[i].t)}</text>
        ))}
        {hover != null && n > 0 && (
          <>
            <line x1={x(hover)} x2={x(hover)} y1={PAD.t} y2={PAD.t + ih} stroke="var(--border-strong)" strokeWidth="1" />
            {lines.map((l) => <circle key={l.key} cx={x(hover)} cy={y(data[hover][l.key] || 0)} r="3.5" fill={l.color} />)}
          </>
        )}
      </svg>
      {hover != null && n > 0 && (
        <div style={{ position: "absolute", top: 4, left: `${(x(hover) / W) * 100}%`, transform: "translateX(-50%)",
          pointerEvents: "none", background: "var(--panel)", border: "1px solid var(--border-strong)",
          borderRadius: 8, padding: "5px 9px", fontSize: 11.5, whiteSpace: "nowrap", boxShadow: "var(--sh-2)" }}>
          <div className="muted" style={{ fontSize: 10.5 }}>{fmtLabel(data[hover].t)}</div>
          {lines.map((l) => (
            <div key={l.key}>
              <span style={{ display: "inline-block", width: 8, height: 8, borderRadius: 999, background: l.color, marginRight: 5 }} />
              {l.label}: {fy(data[hover][l.key] || 0)}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
