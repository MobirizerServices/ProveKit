"use client";

import { useState } from "react";

function fmt(v: any): string {
  if (v === null) return "null";
  if (v === undefined) return "undefined";
  if (typeof v === "string") return `"${v}"`;
  return String(v);
}

function Node({ k, v, depth }: { k?: string; v: any; depth: number }) {
  const [open, setOpen] = useState(depth < 3);
  const isObj = v && typeof v === "object";
  if (!isObj) {
    const t = v === null ? "null" : typeof v;
    return (
      <div className="jv-row" style={{ paddingLeft: 4 + depth * 14 }}>
        {k !== undefined && <span className="jv-key">{k}:</span>}
        <span className={`jv-val ${t}`}>{fmt(v)}</span>
      </div>
    );
  }
  const entries: [string, any][] = Array.isArray(v) ? v.map((x, i) => [String(i), x]) : Object.entries(v);
  return (
    <div>
      <div className="jv-row jv-branch" style={{ paddingLeft: 4 + depth * 14 }} onClick={() => setOpen((o) => !o)}>
        <span className="jv-tw">{open ? "▾" : "▸"}</span>
        {k !== undefined && <span className="jv-key">{k}:</span>}
        <span className="jv-meta">{Array.isArray(v) ? `[${entries.length}]` : `{${entries.length}}`}</span>
      </div>
      {open && entries.map(([kk, vv]) => <Node key={kk} k={kk} v={vv} depth={depth + 1} />)}
    </div>
  );
}

export default function JsonView({ data }: { data: any }) {
  const empty = data === undefined || data === null ||
    (typeof data === "object" && !Array.isArray(data) && Object.keys(data).length === 0) ||
    (Array.isArray(data) && data.length === 0);
  if (empty) return <div className="jv-empty">— empty —</div>;
  return <div className="jv"><Node v={data} depth={0} /></div>;
}
