"use client";

import { useEffect, useMemo, useState } from "react";
import { api, Evaluator } from "@/lib/api";
import ConsoleShell from "@/components/ConsoleShell";

/** The evaluator catalog — every built-in scorer an experiment or automation can run,
 *  grouped by what it measures. Read-only: descriptions come from the backend registry. */
export default function EvaluatorsPage() {
  const [rows, setRows] = useState<Evaluator[] | null>(null);
  useEffect(() => { api.evaluators().then(setRows).catch(() => setRows([])); }, []);

  const groups = useMemo(() => {
    const order = ["Correctness", "Trajectory", "RAG", "Budgets", "Multi-turn", "Other"];
    const m = new Map<string, Evaluator[]>();
    for (const e of rows || []) (m.get(e.category) || m.set(e.category, []).get(e.category)!).push(e);
    return order.filter((c) => m.has(c)).map((c) => [c, m.get(c)!] as const);
  }, [rows]);

  return (
    <ConsoleShell>
      <div className="cs-page" style={{ maxWidth: 1100 }}>
        <div className="page-head" style={{ marginBottom: 22 }}>
          <div>
            <div className="page-eyebrow">Quality</div>
            <h1>Evaluators</h1>
            <p>The scorers an experiment or automation can run. Reference one by name in{" "}
              <code className="mono">pk.evaluate(scorers=[…])</code> or attach it to an automation.</p>
          </div>
        </div>

        {rows == null ? <div className="muted" style={{ fontSize: 13 }}>Loading…</div>
          : groups.map(([cat, items]) => (
            <div key={cat} className="ev-group">
              <div className="ev-cat">{cat}</div>
              <div className="ev-grid">
                {items.map((e) => (
                  <div key={e.name} className="ev-card">
                    <code className="ev-name">{e.name}</code>
                    <p>{e.description}</p>
                  </div>
                ))}
              </div>
            </div>
          ))}
      </div>
    </ConsoleShell>
  );
}
