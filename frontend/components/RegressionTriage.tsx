"use client";

import { useEffect, useState } from "react";
import {
  ExperimentTriage, ScorerTriage, TriageRow,
  fetchTriage, formatDelta, scorersByDamage, unpairedSummary,
} from "@/lib/experiments";

// "Score dropped 0.08" is where triage starts, not where it ends. This panel names the rows
// that dropped, worst first, so the next click is the broken example rather than a table scan.
// Rows the backend could not pair are stated in words instead of being quietly dropped — a
// diff that looks complete but isn't is the failure mode worth spending pixels on.

const PREVIEW = 4;

export default function RegressionTriage({ a, b }: { a: number; b: number }) {
  const [data, setData] = useState<ExperimentTriage | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let live = true;
    setData(null); setError("");
    fetchTriage(a, b)
      .then((t) => { if (live) setData(t); })
      .catch((e) => { if (live) setError(String(e.message || e)); });
    return () => { live = false; };
  }, [a, b]);

  if (error) return <div style={{ ...box, fontSize: 12, color: "var(--err)" }}>{error}</div>;
  if (!data) return null;

  const scorers = scorersByDamage(data);
  const unpaired = unpairedSummary(data.pairing);

  return (
    <div style={box}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 8, flexWrap: "wrap" }}>
        <div style={{ fontSize: 12.5, fontWeight: 600 }}>What changed, row by row</div>
        <div className="muted" style={{ fontSize: 11.5 }}>
          {data.pairing.paired} item{data.pairing.paired === 1 ? "" : "s"} scored in both · pass ≥ {data.pass_at}
        </div>
      </div>

      {/* Refusals first: if the runs aren't comparable, no table below is worth reading. */}
      {data.warning && (
        <div style={{ fontSize: 12, color: "var(--amber)", marginTop: 8 }}>{data.warning}</div>
      )}
      {unpaired && <div className="muted" style={{ fontSize: 11.5, marginTop: 6 }}>{unpaired}</div>}
      {data.notes.map((n) => (
        <div key={n} className="muted" style={{ fontSize: 11.5, marginTop: 4, lineHeight: 1.45 }}>{n}</div>
      ))}

      {data.comparable && scorers.length === 0 && (
        <div className="muted" style={{ fontSize: 12, marginTop: 8 }}>No scores on the paired rows.</div>
      )}
      {scorers.map(([name, s]) => <Scorer key={name} name={name} s={s} />)}
    </div>
  );
}

function Scorer({ name, s }: { name: string; s: ScorerTriage }) {
  const [all, setAll] = useState(false);
  const rows = all ? s.regressed : s.regressed.slice(0, PREVIEW);
  const quiet = s.regressed_count === 0 && s.improved_count === 0;

  return (
    <div style={{ marginTop: 12, paddingTop: 10, borderTop: "1px solid var(--border)" }}>
      <div style={{ display: "flex", gap: 10, alignItems: "baseline", flexWrap: "wrap", fontSize: 12 }}>
        <span className="mono" style={{ fontWeight: 600 }}>{name}</span>
        <span style={{ color: s.regressed_count ? "var(--err)" : "var(--muted)" }}>
          {s.regressed_count} worse
        </span>
        <span className="muted">{s.improved_count} better · {s.unchanged} unchanged</span>
        {/* The headline number: a row that went from passing to failing is a break. */}
        {s.pass_to_fail > 0 && <span style={badge("var(--err)")}>{s.pass_to_fail} pass → fail</span>}
        {s.fail_to_pass > 0 && <span style={badge("var(--green)")}>{s.fail_to_pass} fail → pass</span>}
      </div>

      {(s.scored_only_in_a > 0 || s.scored_only_in_b > 0) && (
        <div className="muted" style={{ fontSize: 11.5, marginTop: 4 }}>
          Scored in only one run: {s.scored_only_in_a} in A, {s.scored_only_in_b} in B — this scorer
          did not run on both sides, so those rows are not a change in behaviour.
        </div>
      )}

      {quiet ? (
        <div className="muted" style={{ fontSize: 11.5, marginTop: 4 }}>Every paired row scored the same.</div>
      ) : (
        <>
          <div style={{ marginTop: 6 }}>{rows.map((r) => <Row key={r.item_id} r={r} />)}</div>
          {s.regressed_count > rows.length && (
            <button className="btn btn-sm" style={{ marginTop: 6 }} onClick={() => setAll(true)}>
              Show {s.regressed_count - rows.length} more
              {s.truncated && s.regressed_count > s.regressed.length ? ` (${s.regressed.length} loaded)` : ""}
            </button>
          )}
          {s.regressed_count === 0 && (
            <div className="muted" style={{ fontSize: 11.5, marginTop: 4 }}>Nothing regressed.</div>
          )}
        </>
      )}
    </div>
  );
}

function Row({ r }: { r: TriageRow }) {
  return (
    <details style={{ borderTop: "1px solid var(--border)", padding: "6px 0" }}>
      <summary style={{ cursor: "pointer", display: "flex", gap: 8, alignItems: "baseline", flexWrap: "wrap", fontSize: 12 }}>
        <span className="mono muted" style={{ fontSize: 11 }}>#{r.item_id}</span>
        <span style={{ fontWeight: 600, color: "var(--err)" }}>{formatDelta(r.delta)}</span>
        <span className="muted mono" style={{ fontSize: 11 }}>{r.a_score} → {r.b_score}</span>
        {r.crossed === "pass_to_fail" && <span style={badge("var(--err)")}>broke</span>}
        <span className="muted" style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {r.input}
        </span>
      </summary>
      <div style={{ marginTop: 6, display: "grid", gap: 6, fontSize: 11.5 }}>
        {r.expected && <Field label="expected" value={r.expected} />}
        <Field label="A output" value={r.a_output} />
        <Field label="B output" value={r.b_output} />
      </div>
    </details>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="muted" style={{ fontSize: 10.5, textTransform: "uppercase", letterSpacing: 0.4 }}>{label}</div>
      <div className="mono" style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>{value || "—"}</div>
    </div>
  );
}

const box: React.CSSProperties = {
  marginTop: 10, padding: 12, border: "1px solid var(--border)",
  borderRadius: 10, background: "var(--panel-2)",
};
function badge(color: string): React.CSSProperties {
  return { fontSize: 10.5, fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.3, color };
}
