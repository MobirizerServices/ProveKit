"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, ApiKey, Dataset, Experiment } from "@/lib/api";

/**
 * The first-run checklist, on the first screen.
 *
 * Overview is where a new account lands, and until traffic arrives it is a wall of zeroes: 0
 * traces, 0.00% error rate, $0.00. That is accurate and tells you nothing about what to do,
 * which is the same failure the empty list pages had.
 *
 * Every step here is *derived*, never remembered. There is no "onboarding completed" flag in
 * local storage: a flag drifts from reality the moment someone rotates a key or the retention
 * window prunes the only trace, and then the product cheerfully claims a step is done when it
 * is not. Each line asks the server what is actually true right now, so the checklist is
 * correct even for an account that arrives half-configured — invited to an existing project,
 * or set up by a teammate.
 *
 * The middle step is the one that matters and the one that is easy to get wrong: a key that
 * exists is not a key that has *worked*. `last_used_at` is stamped whenever a key resolves, so
 * "created" and "has actually reached this server" are different states and are shown as such
 * — otherwise someone stares at an empty Traces page with a green tick next to their key.
 *
 * It disappears on its own once all three are true. An onboarding panel that outlives its
 * usefulness becomes furniture people learn to scroll past.
 */
type StepState = "done" | "todo";

interface Step {
  state: StepState;
  title: string;
  detail: React.ReactNode;
  action?: { label: string; href: string };
}

export default function GettingStarted({ traceCount }: { traceCount: number | null }) {
  const [keys, setKeys] = useState<ApiKey[] | null>(null);
  const [scored, setScored] = useState<boolean | null>(null);

  useEffect(() => {
    let live = true;
    api.apiKeys().then((k) => live && setKeys(k)).catch(() => live && setKeys([]));
    Promise.all([api.datasets().catch(() => [] as Dataset[]),
                 api.experiments().catch(() => [] as Experiment[])])
      .then(([d, e]) => live && setScored((d?.length ?? 0) > 0 || (e?.length ?? 0) > 0))
      .catch(() => live && setScored(false));
    return () => { live = false; };
  }, []);

  // Still loading, or nothing to say yet — render nothing rather than a flash of wrong ticks.
  if (keys == null || scored == null || traceCount == null) return null;

  const live = keys.filter((k) => !k.revoked);
  const hasTraces = traceCount > 0;
  const keyUsed = live.some((k) => k.last_used_at);
  // A trace that arrived is itself proof of a working key, so it satisfies this step on its
  // own. There are two ways to hold one — a named key in /api/api-keys, and the workspace's
  // own OTLP ingest key, whose existence the API deliberately never reports (it is stored
  // hashed and shown once). Checking only the named list told anyone using the second path
  // that they had no key while their traces were arriving on screen — a checklist
  // contradicting the page it sits on. Reality settles it.
  const hasKey = live.length > 0 || hasTraces;

  if (hasKey && hasTraces && scored) return null;      // set up — stop taking up the screen

  const steps: Step[] = [
    {
      state: hasKey ? "done" : "todo",
      title: "Create a project key",
      detail: live.length > 0
        ? `${live.length} active key${live.length === 1 ? "" : "s"}.`
        : hasTraces
          ? "A trace has arrived, so a working key exists."
          : "The SDK authenticates with it. Nothing can arrive until one exists.",
      action: hasKey ? undefined : { label: "Project keys", href: "/api-keys" },
    },
    {
      state: hasTraces ? "done" : "todo",
      title: "Send your first trace",
      detail: hasTraces
        ? `${traceCount} trace${traceCount === 1 ? "" : "s"} captured.`
        : hasKey && !keyUsed
          ? "Your key has never reached this server, so the SDK hasn't connected yet — check PROVEKIT_ENDPOINT, or run provekit doctor."
          : "Two environment variables and one decorator. Every model call underneath is captured for you.",
      action: hasTraces ? undefined : { label: "How to instrument", href: "/traces" },
    },
    {
      state: scored ? "done" : "todo",
      title: "Score a run",
      detail: scored
        ? "You have something to compare against."
        : "Tracing shows what happened. A dataset is what lets you prove a change made it better.",
      action: scored ? undefined : { label: "Datasets", href: "/datasets" },
    },
  ];

  const left = steps.filter((s) => s.state === "todo").length;

  return (
    <section className="gs">
      <div className="gs-head">
        <h2>Getting started</h2>
        <span className="gs-count">{3 - left} of 3</span>
      </div>

      <ol className="gs-steps">
        {steps.map((s) => (
          <li key={s.title} className={`gs-step ${s.state}`}>
            <span className="gs-tick" aria-hidden>{s.state === "done" ? "✓" : ""}</span>
            <span className="gs-body">
              <span className="gs-title">{s.title}</span>
              <span className="gs-detail">{s.detail}</span>
            </span>
            {s.action && <Link href={s.action.href} className="gs-action">{s.action.label} →</Link>}
          </li>
        ))}
      </ol>

      {!hasTraces && hasKey && (
        <pre className="gs-code mono">{`pip install "provekit[trace]"

export PROVEKIT_API_KEY=agm_...        # from Project keys
export PROVEKIT_ENDPOINT=${typeof window === "undefined" ? "" : window.location.origin}

import provekit.auto                   # one import — captures everything below it`}</pre>
      )}
    </section>
  );
}
