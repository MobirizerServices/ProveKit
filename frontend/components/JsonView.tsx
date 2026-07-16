"use client";

import { useState } from "react";

function fmt(v: any): string {
  if (v === null) return "null";
  if (v === undefined) return "undefined";
  if (typeof v === "string") return `"${v}"`;
  return String(v);
}

function Node({ k, v, depth, path, onPick }: { k?: string; v: any; depth: number; path: string; onPick?: (path: string, value: any) => void }) {
  const [open, setOpen] = useState(depth < 3);
  const isObj = v && typeof v === "object";
  if (!isObj) {
    const t = v === null ? "null" : typeof v;
    return (
      <div className="jv-row" style={{ paddingLeft: 4 + depth * 14 }}>
        {k !== undefined && <span className="jv-key">{k}:</span>}
        <span className={`jv-val ${t}`}>{fmt(v)}</span>
        {onPick && path && <button className="jv-pick" title="Assert this field" onClick={(e) => { e.stopPropagation(); onPick(path, v); }}>+ assert</button>}
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
      {open && entries.map(([kk, vv]) => <Node key={kk} k={kk} v={vv} depth={depth + 1} path={path ? `${path}.${kk}` : kk} onPick={onPick} />)}
    </div>
  );
}

export default function JsonView({ data, onPick }: { data: any; onPick?: (path: string, value: any) => void }) {
  const empty = data === undefined || data === null ||
    (typeof data === "object" && !Array.isArray(data) && Object.keys(data).length === 0) ||
    (Array.isArray(data) && data.length === 0);
  if (empty) return <div className="jv-empty">— empty —</div>;
  return <div className="jv"><Node v={data} depth={0} path="" onPick={onPick} /></div>;
}
