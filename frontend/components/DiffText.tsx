"use client";

import { useMemo } from "react";

// Word-level diff (LCS) — highlights what changed from `from` to `to`.
export function diffWords(a: string, b: string): { t: "same" | "add" | "del"; w: string }[] {
  const A = (a || "").split(/\s+/).filter(Boolean), B = (b || "").split(/\s+/).filter(Boolean);
  const n = A.length, m = B.length;
  if (n > 800 || m > 800) return B.map((w) => ({ t: "same", w }));  // guard O(n·m) on huge text
  const dp = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--)
    dp[i][j] = A[i] === B[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  const out: { t: "same" | "add" | "del"; w: string }[] = [];
  let i = 0, j = 0;
  while (i < n && j < m) {
    if (A[i] === B[j]) { out.push({ t: "same", w: A[i] }); i++; j++; }
    else if (dp[i + 1][j] >= dp[i][j + 1]) { out.push({ t: "del", w: A[i] }); i++; }
    else { out.push({ t: "add", w: B[j] }); j++; }
  }
  while (i < n) out.push({ t: "del", w: A[i++] });
  while (j < m) out.push({ t: "add", w: B[j++] });
  return out;
}

export function DiffText({ from, to }: { from: string; to: string }) {
  const parts = useMemo(() => diffWords(from, to), [from, to]);
  if (!from) return <>{to}</>;
  return <>{parts.map((p, i) => p.t === "same"
    ? <span key={i}>{p.w} </span>
    : p.t === "add"
      ? <span key={i} style={{ background: "color-mix(in srgb, var(--green) 24%, transparent)", borderRadius: 3 }}>{p.w} </span>
      : <span key={i} style={{ color: "var(--red)", textDecoration: "line-through", opacity: 0.65 }}>{p.w} </span>)}</>;
}
