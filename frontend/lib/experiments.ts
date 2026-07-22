import { api, getProjectId } from "@/lib/api";

// Row-level triage between two experiments. /compare answers "did the score move, and is the
// move real"; this answers "which examples moved it" — the question you actually act on.
//
// Everything the backend could not pair is reported rather than guessed at: rows are only ever
// matched on dataset item id, so `pairing` + `notes` are part of the result, not a footnote.

export type Crossed = "" | "pass_to_fail" | "fail_to_pass";

export interface TriageRow {
  item_id: number;
  a_score: number;
  b_score: number;
  delta: number;
  /** Set when the row crossed the pass/fail line — a break, not just a dip. */
  crossed: Crossed;
  input: string;
  expected: string;
  a_output: string;
  b_output: string;
}

export interface ScorerTriage {
  regressed_count: number;
  improved_count: number;
  unchanged: number;
  pass_to_fail: number;
  fail_to_pass: number;
  scored_only_in_a: number;
  scored_only_in_b: number;
  /** Worst regression first; may be shorter than `regressed_count` when truncated. */
  regressed: TriageRow[];
  improved: TriageRow[];
  truncated: boolean;
}

export interface TriagePairing {
  paired: number;
  /** Same item id, different input — the dataset item was edited between the two runs. */
  drifted: number;
  only_in_a: number;
  only_in_b: number;
  no_item_id: number;
  duplicate_item_id: number;
}

export interface ExperimentTriage {
  a: { id: number; name: string; dataset_id: number | null; created_at: string };
  b: { id: number; name: string; dataset_id: number | null; created_at: string };
  pass_at: number;
  /** False when nothing could be paired — the scorers map is then empty on purpose. */
  comparable: boolean;
  warning: string;
  notes: string[];
  pairing: TriagePairing;
  scorers: Record<string, ScorerTriage>;
}

export async function fetchTriage(a: number, b: number, passAt?: number): Promise<ExperimentTriage> {
  const pid = getProjectId();
  const qs = passAt == null ? "" : `?pass_at=${passAt}`;
  const res = await fetch(`${api.base}/api/experiments/${a}/triage/${b}${qs}`, {
    credentials: "include",
    headers: { "Content-Type": "application/json", ...(pid ? { "X-Project-Id": pid } : {}) },
  });
  if (!res.ok) throw new Error(`${res.status}: could not load triage`);
  return res.json();
}

export function formatDelta(d: number): string {
  return `${d >= 0 ? "+" : ""}${d.toFixed(3)}`;
}

/** Scorers with something broken first, then by how much broke — the panel reads top-down. */
export function scorersByDamage(t: ExperimentTriage): [string, ScorerTriage][] {
  return (Object.entries(t.scorers) as [string, ScorerTriage][]).sort(
    (x, y) => y[1].pass_to_fail - x[1].pass_to_fail || y[1].regressed_count - x[1].regressed_count,
  );
}

/** What was left out of the diff, as a single line. Empty when everything paired cleanly. */
export function unpairedSummary(p: TriagePairing): string {
  const parts = [
    p.drifted && `${p.drifted} item changed`,
    p.only_in_a && `${p.only_in_a} only in A`,
    p.only_in_b && `${p.only_in_b} only in B`,
    p.no_item_id && `${p.no_item_id} without an item id`,
    p.duplicate_item_id && `${p.duplicate_item_id} scored twice`,
  ].filter(Boolean) as string[];
  return parts.length ? `${parts.join(" · ")} — not diffed` : "";
}
