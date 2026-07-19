"use client";

import { useState } from "react";

export interface Point { t: string; count: number; errors: number }

// A dependency-free time-series area chart: a smooth filled area for total volume with a
// red overlay for errors, gridlines, hover crosshair + tooltip. Scales to its container.
export default function AreaChart({ data, height = 160 }: { data: Point[]; height?: number }) {
  const [hover, setHover] = useState<number | null>(null);
  const W = 800, H = height, PAD = { l: 34, r: 10, t: 12, b: 22 };
  const iw = W - PAD.l - PAD.r, ih = H - PAD.t - PAD.b;
  const max = Math.max(1, ...data.map((d) => d.count));
  const n = data.length;
  const x = (i: number) => PAD.l + (n <= 1 ? iw / 2 : (i / (n - 1)) * iw);
  const y = (v: number) => PAD.t + ih - (v / max) * ih;

  const area = (key: "count" | "errors") => {
    if (!n) return "";
    const top = data.map((d, i) => `${i === 0 ? "M" : "L"} ${x(i).toFixed(1)} ${y(d[key]).toFixed(1)}`).join(" ");
    return `${top} L ${x(n - 1).toFixed(1)} ${y(0)} L ${x(0).toFixed(1)} ${y(0)} Z`;
  };
  const line = data.map((d, i) => `${i === 0 ? "M" : "L"} ${x(i).toFixed(1)} ${y(d.count).toFixed(1)}`).join(" ");

  // y-axis ticks (0, mid, max)
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
        <defs>
          <linearGradient id="pk-area" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--blue)" stopOpacity="0.35" />
            <stop offset="100%" stopColor="var(--blue)" stopOpacity="0.02" />
          </linearGradient>
        </defs>
        {ticks.map((v) => (
          <g key={v}>
            <line x1={PAD.l} x2={W - PAD.r} y1={y(v)} y2={y(v)} stroke="var(--border)" strokeWidth="1" />
            <text x={PAD.l - 6} y={y(v) + 3} textAnchor="end" fontSize="10" fill="var(--muted)">{v}</text>
          </g>
        ))}
        {n > 0 && <path d={area("count")} fill="url(#pk-area)" />}
        {n > 0 && <path d={line} fill="none" stroke="var(--blue)" strokeWidth="2" />}
        {n > 0 && <path d={area("errors")} fill="var(--red)" fillOpacity="0.4" />}
        {/* x labels: first, middle, last */}
        {[0, Math.floor((n - 1) / 2), n - 1].filter((v, i, a) => n > 0 && a.indexOf(v) === i).map((i) => (
          <text key={i} x={x(i)} y={H - 6} textAnchor="middle" fontSize="10" fill="var(--muted)">{fmtLabel(data[i].t)}</text>
        ))}
        {hover != null && n > 0 && (
          <g>
            <line x1={x(hover)} x2={x(hover)} y1={PAD.t} y2={PAD.t + ih} stroke="var(--border-strong)" strokeWidth="1" />
            <circle cx={x(hover)} cy={y(data[hover].count)} r="3.5" fill="var(--blue)" />
          </g>
        )}
      </svg>
      {hover != null && n > 0 && (
        <div style={{ position: "absolute", top: 4, left: `${(x(hover) / W) * 100}%`, transform: "translateX(-50%)",
          pointerEvents: "none", background: "var(--panel)", border: "1px solid var(--border-strong)",
          borderRadius: 8, padding: "5px 9px", fontSize: 11.5, whiteSpace: "nowrap", boxShadow: "var(--sh-2)" }}>
          <div className="muted" style={{ fontSize: 10.5 }}>{fmtLabel(data[hover].t)}</div>
          <div>{data[hover].count} traces{data[hover].errors ? <span style={{ color: "var(--red)" }}> · {data[hover].errors} errors</span> : ""}</div>
        </div>
      )}
    </div>
  );
}
