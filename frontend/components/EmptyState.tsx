"use client";

// The empty traces page, with a reason attached.
//
// "Listening for your first trace…" is true and useless: it looks identical whether no key
// has ever been created, a key exists but the SDK never reached us, or spans arrived and were
// pruned away. Those are three different bugs with three different fixes, and guessing wrong
// costs an afternoon.
//
// So this asks the server what it can actually attest to — nothing more:
//   • GET /api/api-keys        → does a project key exist here, and has it ever authenticated?
//                                (`last_used_at` is stamped whenever a key resolves, so null
//                                 means "never once reached this server as this project")
//   • GET /api/workspace/retention → how many spans are stored, and how many were pruned
//
// What it deliberately does NOT claim: that spans were *rejected*. Nothing durable records a
// 402/429/503 on ingest, so "authenticated but nothing stored" genuinely covers both an empty
// batch (SDK up, nothing instrumented) and a refused one. Rather than pick one and be wrong
// half the time, that case names both and offers `provekit doctor --send`, which settles it by
// experiment: a probe span that lands proves ingest works and instrumentation doesn't.

import Link from "next/link";
import { useEffect, useState } from "react";
import { API_BASE, ApiKey, getProjectId } from "@/lib/api";

// What ProveKit can auto-instrument. Mirrors provekit/doctor.py `_COVERAGE`, which is the
// source of truth; test_onboarding.py fails if the two drift. The portal cannot compute the
// *local* answer — these libraries live in the user's virtualenv, on a machine this server has
// never seen — so it shows the catalogue and points at `provekit doctor` for the local scan.
export const COVERAGE: { library: string; instrumentor: string; extra: string }[] = [
  { library: "openai", instrumentor: "openinference.instrumentation.openai", extra: "provekit[trace]" },
  { library: "anthropic", instrumentor: "openinference.instrumentation.anthropic", extra: "provekit[trace]" },
  { library: "langchain", instrumentor: "openinference.instrumentation.langchain", extra: "provekit[trace-all]" },
  { library: "llama_index", instrumentor: "openinference.instrumentation.llama_index", extra: "provekit[trace-all]" },
  { library: "crewai", instrumentor: "openinference.instrumentation.crewai", extra: "provekit[trace-all]" },
  { library: "litellm", instrumentor: "openinference.instrumentation.litellm", extra: "provekit[trace-all]" },
  { library: "groq", instrumentor: "openinference.instrumentation.groq", extra: "provekit[trace-all]" },
  { library: "mistralai", instrumentor: "openinference.instrumentation.mistralai", extra: "provekit[trace-all]" },
  { library: "httpx", instrumentor: "opentelemetry.instrumentation.httpx", extra: "provekit[http]" },
  { library: "requests", instrumentor: "opentelemetry.instrumentation.requests", extra: "provekit[http]" },
];

// ---------------------------------------------------------------- diagnosis

export interface IngestSignals {
  keys: ApiKey[] | null;          // null = the check itself didn't load
  storedSpans: number | null;
  prunedTotal: number | null;
}

export type DiagnosisCode =
  | "unknown" | "no_key" | "all_keys_revoked" | "key_never_used"
  | "pruned" | "no_spans_stored" | "stored_but_unlisted";

export interface Diagnosis {
  code: DiagnosisCode;
  tone: "wait" | "warn" | "bad";
  headline: string;
  observed: string;               // strictly what the server can attest to
  meaning: string;                // what that narrows it down to — no more
  fixes: string[];
}

const GENERIC: Diagnosis = {
  code: "unknown", tone: "wait",
  headline: "Listening for your first trace…",
  observed: "",
  meaning: "This page updates automatically the moment a trace arrives.",
  fixes: [],
};

/** Pure so the reasoning is inspectable (and can be read next to the backend that feeds it). */
export function diagnose(s: IngestSignals): Diagnosis {
  if (s.keys === null || s.storedSpans === null) return GENERIC;

  if (s.keys.length === 0) {
    return {
      code: "no_key", tone: "warn",
      headline: "No project key in this project yet",
      observed: "This project has no `pk_` key, so nothing has ever been able to send to it.",
      meaning:
        "A key is per project. If your agent is already running with a key, that key belongs " +
        "to a different project — its traces are there, not here.",
      fixes: [
        "Create a key on the Project keys page and set it as PROVEKIT_API_KEY.",
        "Already have a key? Switch projects with the picker in the top bar.",
      ],
    };
  }

  const live = s.keys.filter((k) => !k.revoked);
  if (live.length === 0) {
    return {
      code: "all_keys_revoked", tone: "bad",
      headline: "Every key in this project is revoked",
      observed: `All ${s.keys.length} key${s.keys.length === 1 ? "" : "s"} here are revoked — ingest with them is rejected (403).`,
      meaning: "The SDK is failing open, exactly as designed: your agent keeps working and says nothing.",
      fixes: ["Mint a new key on the Project keys page and update PROVEKIT_API_KEY."],
    };
  }

  const used = live.filter((k) => k.last_used_at);
  if (used.length === 0) {
    return {
      code: "key_never_used", tone: "bad",
      headline: "A key exists, but nothing has ever authenticated with it",
      observed:
        `${live.length} live key${live.length === 1 ? "" : "s"}, none of which has ever reached this server.`,
      meaning:
        "The request isn't arriving at all — so the problem is between your process and this " +
        "host, not in what it sends. Usual causes: PROVEKIT_ENDPOINT unset or wrong, the " +
        "provekit[trace] extra not installed (the SDK then silently no-ops), egress blocked, " +
        "or the key in your .env is from another project.",
      fixes: [
        "Run `provekit doctor` on the machine running your agent — it walks the same path the SDK takes.",
        `Confirm PROVEKIT_ENDPOINT is the base URL only (no /v1/traces).`,
      ],
    };
  }

  const lastUsed = used
    .map((k) => k.last_used_at as string)
    .sort()
    .slice(-1)[0];

  if (s.storedSpans === 0 && (s.prunedTotal ?? 0) > 0) {
    return {
      code: "pruned", tone: "warn",
      headline: "Spans did arrive — retention deleted them",
      observed: `${s.prunedTotal} span${s.prunedTotal === 1 ? "" : "s"} were pruned from this project and 0 are stored now.`,
      meaning:
        "This is a configuration answer, not an instrumentation bug: your agent is reporting " +
        "correctly and the span cap is throwing it away.",
      fixes: [
        "Raise this project's retention in Settings (or RUNS_RETENTION for the whole instance).",
        "Check Settings → retention for exactly what was deleted and when.",
      ],
    };
  }

  if (s.storedSpans === 0) {
    return {
      code: "no_spans_stored", tone: "warn",
      headline: "Your key is authenticating, but no spans are stored",
      observed: `A key here last authenticated ${rel(lastUsed)}, and this project holds 0 spans.`,
      meaning:
        "Requests are reaching this project, so the endpoint and key are right. Two things " +
        "still look identical from here, and we won't guess between them: the batches may be " +
        "empty (the SDK started but nothing is instrumented — no `import provekit.auto`, no " +
        "@pk.trace), or ingest may be refusing them (span quota, rate limit, or backlog). " +
        "Nothing durable records a refusal, so this page cannot tell you which.",
      fixes: [
        "Run `provekit doctor --send`: it posts one probe span. If it appears here, ingest is fine and instrumentation is the gap.",
        "If the probe does NOT appear, ingest is refusing writes — check quota/rate limits in Settings.",
        "Flush before exit — a short script can end before the exporter ships its batch.",
      ],
    };
  }

  return {
    code: "stored_but_unlisted", tone: "warn",
    headline: `${s.storedSpans} span${s.storedSpans === 1 ? "" : "s"} are stored, but none are listed`,
    observed: `Spans exist in this project; the trace list came back empty.`,
    meaning: "The list groups spans into traces, so this usually means a filter or a stale page.",
    fixes: ["Reload the page.", "Clear any search text or time window above the list."],
  };
}

function rel(iso?: string): string {
  if (!iso) return "recently";
  const d = (Date.now() - new Date(iso).getTime()) / 1000;
  if (!isFinite(d)) return "recently";
  if (d < 90) return "just now";
  if (d < 3600) return `${Math.round(d / 60)}m ago`;
  if (d < 86400) return `${Math.round(d / 3600)}h ago`;
  return `${Math.round(d / 86400)}d ago`;
}

// ---------------------------------------------------------------- data

async function get<T>(path: string): Promise<T | null> {
  try {
    const pid = getProjectId();
    const res = await fetch(`${API_BASE}${path}`, {
      credentials: "include",
      headers: pid ? { "X-Project-Id": pid } : {},
    });
    if (!res.ok) return null;
    return (await res.json()) as T;
  } catch {
    return null;   // a diagnostic that breaks the page it explains would be a poor trade
  }
}

interface Retention { stored_spans: number; pruned_total: number }

// ---------------------------------------------------------------- component

export default function EmptyState({ origin }: { origin: string }) {
  const [signals, setSignals] = useState<IngestSignals>({ keys: null, storedSpans: null, prunedTotal: null });
  const [showCoverage, setShowCoverage] = useState(false);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    let live = true;
    Promise.all([get<ApiKey[]>("/api/api-keys"), get<Retention>("/api/workspace/retention")])
      .then(([keys, ret]) => {
        if (!live) return;
        setSignals({
          keys, storedSpans: ret ? ret.stored_spans : null,
          prunedTotal: ret ? ret.pruned_total : null,
        });
      });
    return () => { live = false; };
  }, []);

  const d = diagnose(signals);
  const snippet = `pip install "provekit[trace]"

# .env
PROVEKIT_API_KEY=pk_...          # ← create one in Project keys
PROVEKIT_ENDPOINT=${origin}

import provekit.auto              # one import — captures everything below it

# (optional) group a run under a named root:
import provekit.trace as pk
@pk.trace(name="my-agent")
def run_agent(question: str) -> str:
    ...   # your agent — OpenAI/Anthropic calls capture themselves`;
  const copy = () => { navigator.clipboard?.writeText(snippet); setCopied(true); setTimeout(() => setCopied(false), 1500); };

  const accent = d.tone === "bad" ? "var(--red)" : d.tone === "warn" ? "var(--amber)" : "var(--green)";

  return (
    <div style={{ display: "grid", gap: 14, maxWidth: 760 }}>
      <div style={panel}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
          {d.tone === "wait"
            ? <span className="pulse-dot" />
            : <span style={{ width: 9, height: 9, borderRadius: 999, background: accent, flexShrink: 0 }} />}
          <span style={{ fontSize: 15, fontWeight: 600 }}>{d.headline}</span>
        </div>

        {d.observed && (
          <p style={{ margin: "0 0 8px", fontSize: 13, color: "var(--text-dim)" }}>
            <span style={{ color: accent, fontWeight: 600 }}>What we can see: </span>{d.observed}
          </p>
        )}
        <p className="muted" style={{ margin: "0 0 12px", fontSize: 13, lineHeight: 1.6 }}>{d.meaning}</p>

        {d.fixes.length > 0 && (
          <ol style={{ margin: "0 0 14px", paddingLeft: 18, fontSize: 13.5, lineHeight: 1.75 }}>
            {d.fixes.map((f) => <li key={f}>{f}</li>)}
          </ol>
        )}
        {d.code === "unknown" && (
          <ol style={{ margin: "0 0 14px", paddingLeft: 18, fontSize: 13.5, lineHeight: 1.7 }}>
            <li>Grab a key on the <Link href="/api-keys" style={{ color: "var(--accent)" }}>Project keys</Link> page.</li>
            <li>Drop the snippet below into your agent (fill in the key).</li>
            <li>Run your agent — the run shows up here as a nested flow.</li>
          </ol>
        )}
        {(d.code === "no_key" || d.code === "all_keys_revoked") && (
          <p style={{ margin: "0 0 14px", fontSize: 13 }}>
            → <Link href="/api-keys" style={{ color: "var(--accent)" }}>Project keys</Link>
          </p>
        )}
        {d.code === "pruned" && (
          <p style={{ margin: "0 0 14px", fontSize: 13 }}>
            → <Link href="/settings" style={{ color: "var(--accent)" }}>Settings</Link>
          </p>
        )}

        <div style={{ position: "relative" }}>
          <button className="btn btn-sm" onClick={copy} style={{ position: "absolute", top: 8, right: 8, zIndex: 1 }}>
            {copied ? "Copied" : "Copy"}
          </button>
          <pre style={pre}>{snippet}</pre>
        </div>

        <style jsx>{`
          .pulse-dot { width: 9px; height: 9px; border-radius: 999px; background: var(--green); box-shadow: 0 0 0 0 var(--green); animation: pk-pulse 1.8s infinite; flex-shrink: 0; }
          @keyframes pk-pulse { 0% { box-shadow: 0 0 0 0 rgba(80,200,120,0.5); } 70% { box-shadow: 0 0 0 8px rgba(80,200,120,0); } 100% { box-shadow: 0 0 0 0 rgba(80,200,120,0); } }
        `}</style>
      </div>

      <div style={panel}>
        <button onClick={() => setShowCoverage((v) => !v)}
          style={{ background: "none", border: "none", color: "var(--text)", cursor: "pointer", padding: 0, fontSize: 14, fontWeight: 600 }}>
          {showCoverage ? "▾" : "▸"} What ProveKit auto-instruments ({COVERAGE.length} libraries)
        </button>
        <p className="muted" style={{ margin: "6px 0 0", fontSize: 12.5, lineHeight: 1.6 }}>
          A library you call whose instrumentor isn&apos;t installed produces no span at all — the
          call happens and the trace simply doesn&apos;t mention it. This server can&apos;t see your
          virtualenv, so run <code style={code}>provekit doctor</code> where your agent runs to
          get the local answer.
        </p>
        {showCoverage && (
          <div style={{ marginTop: 12, overflowX: "auto" }}>
            <table style={{ borderCollapse: "collapse", fontSize: 12.5, width: "100%", minWidth: 420 }}>
              <thead>
                <tr>
                  <th style={th}>Library</th><th style={th}>Provided by</th>
                </tr>
              </thead>
              <tbody>
                {COVERAGE.map((c) => (
                  <tr key={c.library}>
                    <td style={td}><code style={code}>{c.library}</code></td>
                    <td style={td}><code style={code}>pip install &quot;{c.extra}&quot;</code></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

const panel: React.CSSProperties = {
  background: "var(--panel)", border: "1px solid var(--border)", borderRadius: 12, padding: 16,
};
const pre: React.CSSProperties = {
  margin: 0, padding: 14, borderRadius: 8, background: "var(--bg-2)", border: "1px solid var(--border)",
  fontSize: 12.5, lineHeight: 1.5, fontFamily: "var(--font-mono)", whiteSpace: "pre-wrap",
  wordBreak: "break-word",
};
const code: React.CSSProperties = {
  fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--accent-2)",
};
const th: React.CSSProperties = {
  textAlign: "left", padding: "6px 10px 6px 0", color: "var(--faint)", fontWeight: 500,
  borderBottom: "1px solid var(--border)", whiteSpace: "nowrap",
};
const td: React.CSSProperties = {
  padding: "6px 10px 6px 0", borderBottom: "1px solid var(--hairline)", whiteSpace: "nowrap",
};
