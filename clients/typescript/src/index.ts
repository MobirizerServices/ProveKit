/**
 * ProveKit — drop-in tracing for TypeScript/JavaScript agents.
 *
 *     import * as pk from "provekit";
 *     pk.init();                                    // reads PROVEKIT_API_KEY / PROVEKIT_ENDPOINT
 *     const run = pk.trace("support-agent", handle); // every call captured as a nested flow
 *
 * Design mirrors the Python SDK deliberately, so a mixed-language team reads one mental model:
 *
 * - **Fail-open.** No key, no endpoint, or an unreachable portal degrades to a no-op. Tracing
 *   must never be the reason a production agent breaks. (`provekit-doctor` exists on the Python
 *   side precisely because this makes misconfiguration silent; `pk.diagnose()` below is the
 *   equivalent here.)
 * - **Zero runtime dependencies.** Node 18+ has `fetch`, `AsyncLocalStorage` and `randomUUID`
 *   built in. An observability client that drags in a tree of transitive packages is a liability
 *   in the one place you can least afford one.
 * - **OTLP/JSON on the wire**, byte-compatible with what the Python SDK emits, so the same
 *   ingest endpoint and span mapper handle both without a branch.
 *
 * Node-only for now: context propagation across `await` needs `AsyncLocalStorage`.
 */
import { AsyncLocalStorage } from "node:async_hooks";
import { randomBytes } from "node:crypto";

// ---------------------------------------------------------------- configuration

export interface Config {
  apiKey?: string;
  endpoint?: string;
  /** Flush automatically once this many spans are queued. */
  batchSize?: number;
  /** Flush automatically after this many ms, even if the batch isn't full. */
  flushIntervalMs?: number;
  /** Per-request timeout for the exporter. */
  timeoutMs?: number;
  /** Cap on queued spans. Beyond this the oldest are dropped rather than growing without bound. */
  maxQueue?: number;
}

interface Resolved extends Required<Config> {
  active: boolean;
}

const DEFAULTS = {
  batchSize: 50,
  flushIntervalMs: 5000,
  timeoutMs: 10000,
  maxQueue: 2048,
};

let cfg: Resolved = { apiKey: "", endpoint: "", active: false, ...DEFAULTS };
let timer: ReturnType<typeof setInterval> | null = null;
let dropped = 0;

/**
 * Configure the tracer. Returns whether tracing is active.
 *
 * Safe to call more than once; the last call wins, which makes it usable from tests without a
 * process restart.
 */
export function init(options: Config = {}): boolean {
  const env = (globalThis as any)?.process?.env ?? {};
  const apiKey = options.apiKey ?? env.PROVEKIT_API_KEY ?? "";
  const endpointRaw = options.endpoint ?? env.PROVEKIT_ENDPOINT ?? "";
  const endpoint = endpointRaw.replace(/\/+$/, "");

  cfg = {
    apiKey,
    endpoint,
    batchSize: options.batchSize ?? DEFAULTS.batchSize,
    flushIntervalMs: options.flushIntervalMs ?? DEFAULTS.flushIntervalMs,
    timeoutMs: options.timeoutMs ?? DEFAULTS.timeoutMs,
    maxQueue: options.maxQueue ?? DEFAULTS.maxQueue,
    active: Boolean(apiKey && endpoint),
  };

  if (timer) { clearInterval(timer); timer = null; }
  if (cfg.active && cfg.flushIntervalMs > 0) {
    timer = setInterval(() => { void flush(); }, cfg.flushIntervalMs);
    // Don't hold a short-lived script open just because the tracer is ticking.
    (timer as any).unref?.();
  }
  return cfg.active;
}

/** Whether spans are currently being captured. */
export function isActive(): boolean {
  return cfg.active;
}

/**
 * Why nothing is being captured — the TypeScript counterpart of `provekit-doctor`.
 *
 * Fail-open means a missing key and a working setup look identical from the outside, so there
 * has to be something that says which one you have.
 */
export function diagnose(): { active: boolean; problems: string[] } {
  const problems: string[] = [];
  if (!cfg.apiKey) problems.push("PROVEKIT_API_KEY is not set — create a project key in the portal.");
  if (!cfg.endpoint) {
    problems.push("PROVEKIT_ENDPOINT is not set — use your portal's base URL.");
  } else if (/\/v1\/traces$/.test(cfg.endpoint)) {
    problems.push("PROVEKIT_ENDPOINT already ends in /v1/traces — set the base URL only, the SDK appends it.");
  } else if (!/^https?:\/\//.test(cfg.endpoint)) {
    problems.push(`PROVEKIT_ENDPOINT (${cfg.endpoint}) is missing a http:// or https:// scheme.`);
  }
  if (dropped > 0) problems.push(`${dropped} span(s) dropped: the queue filled faster than it flushed.`);
  return { active: cfg.active, problems };
}

// ---------------------------------------------------------------- span model

type AttrValue = string | number | boolean | null | undefined;

interface RawSpan {
  name: string;
  traceId: string;
  spanId: string;
  parentSpanId: string;
  startTimeUnixNano: string;
  endTimeUnixNano: string;
  status: { code: number; message?: string };
  attributes: { key: string; value: Record<string, unknown> }[];
}

interface Ctx {
  traceId: string;
  spanId: string;
  sessionId?: string;
}

const store = new AsyncLocalStorage<Ctx>();
const queue: RawSpan[] = [];

const hex = (bytes: number) => randomBytes(bytes).toString("hex");

/** Wall-clock nanoseconds as a string, matching OTLP's field type. */
function nowNanos(): string {
  // Date.now() is milliseconds; OTLP wants nanos, and JS numbers can't hold them precisely,
  // so the multiplication happens in string space rather than floating point.
  return `${BigInt(Date.now()) * 1_000_000n}`;
}

function attr(value: AttrValue): Record<string, unknown> {
  if (typeof value === "boolean") return { boolValue: value };
  if (typeof value === "number") {
    return Number.isInteger(value) ? { intValue: value } : { doubleValue: value };
  }
  return { stringValue: value == null ? "" : String(value) };
}

/** Best-effort JSON for a call's inputs/outputs; never throws on a cycle or a BigInt. */
function payload(value: unknown): string {
  if (typeof value === "string") return value.slice(0, 8000);
  try {
    const seen = new WeakSet();
    return JSON.stringify(value, (_k, v) => {
      if (typeof v === "bigint") return String(v);
      if (typeof v === "object" && v !== null) {
        if (seen.has(v)) return "[circular]";
        seen.add(v);
      }
      return v;
    })?.slice(0, 8000) ?? "";
  } catch {
    return String(value).slice(0, 8000);
  }
}

function enqueue(span: RawSpan): void {
  if (queue.length >= cfg.maxQueue) {
    // Drop the oldest rather than the newest: recent spans describe what's happening now, and
    // an unbounded queue would turn a portal outage into the agent's memory problem.
    queue.shift();
    dropped++;
  }
  queue.push(span);
  if (queue.length >= cfg.batchSize) void flush();
}

// ---------------------------------------------------------------- public API

export interface SpanOptions {
  /** Groups multi-turn runs into a conversation in the portal. */
  sessionId?: string;
  /** Extra span attributes. */
  attributes?: Record<string, AttrValue>;
  /** OTel `gen_ai.operation.name`; defaults to `invoke_agent` for traces, `step` for spans. */
  operation?: string;
}

async function record<T>(
  name: string,
  operation: string,
  fn: () => Promise<T> | T,
  options: SpanOptions,
  input?: unknown,
): Promise<T> {
  if (!cfg.active) return await fn();          // tracing off → straight through

  const parent = store.getStore();
  const ctx: Ctx = {
    traceId: parent?.traceId ?? hex(16),
    spanId: hex(8),
    sessionId: options.sessionId ?? parent?.sessionId,
  };
  const start = nowNanos();

  const attrs: { key: string; value: Record<string, unknown> }[] = [
    { key: "gen_ai.operation.name", value: attr(operation) },
  ];
  if (ctx.sessionId) attrs.push({ key: "session.id", value: attr(ctx.sessionId) });
  if (input !== undefined) attrs.push({ key: "gen_ai.input.messages", value: attr(payload(input)) });
  for (const [k, v] of Object.entries(options.attributes ?? {})) {
    attrs.push({ key: k, value: attr(v) });
  }

  const finish = (code: number, message?: string, output?: unknown) => {
    if (output !== undefined) {
      attrs.push({ key: "gen_ai.output.messages", value: attr(payload(output)) });
    }
    enqueue({
      name,
      traceId: ctx.traceId,
      spanId: ctx.spanId,
      parentSpanId: parent?.spanId ?? "",
      startTimeUnixNano: start,
      endTimeUnixNano: nowNanos(),
      status: message ? { code, message: message.slice(0, 500) } : { code },
      attributes: attrs,
    });
  };

  try {
    const result = await store.run(ctx, async () => await fn());
    finish(1, undefined, result);
    return result;
  } catch (err) {
    // Record the failure, then rethrow untouched: swallowing it would make the tracer change
    // program behaviour, which is the one thing it must never do.
    finish(2, err instanceof Error ? err.message : String(err));
    throw err;
  }
}

/**
 * Wrap an agent entrypoint so every call is captured as one trace. Anything traced inside —
 * `pk.span()` blocks, nested `pk.trace()` calls — nests beneath it.
 *
 *     const runAgent = pk.trace("support-agent", async (q: string) => { ... });
 */
export function trace<A extends unknown[], R>(
  name: string,
  fn: (...args: A) => Promise<R> | R,
  options: SpanOptions = {},
): (...args: A) => Promise<R> {
  return (...args: A) =>
    record(name, options.operation ?? "invoke_agent", () => fn(...args), options, args);
}

/**
 * Capture one sub-step — a retrieval, a tool call, a branch.
 *
 *     const docs = await pk.span("retrieve", () => search(q));
 */
export function span<T>(
  name: string,
  fn: () => Promise<T> | T,
  options: SpanOptions = {},
): Promise<T> {
  return record(name, options.operation ?? "step", fn, options);
}

/** The active trace id, or null outside a trace — useful for correlating your own logs. */
export function currentTraceId(): string | null {
  return store.getStore()?.traceId ?? null;
}

/**
 * Attach a feedback score to the current trace (a heuristic, a guardrail, an LLM judge).
 * No-ops outside a trace rather than throwing — scoring is not worth failing a request over.
 */
export async function score(
  name: string,
  opts: { score?: number; value?: string; comment?: string } = {},
): Promise<boolean> {
  const ctx = store.getStore();
  if (!cfg.active || !ctx) return false;
  try {
    const res = await fetch(`${cfg.endpoint}/v1/traces/${ctx.traceId}/feedback`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${cfg.apiKey}` },
      body: JSON.stringify({ name, source: "sdk", ...opts }),
      signal: AbortSignal.timeout(cfg.timeoutMs),
    });
    return res.ok;
  } catch {
    return false;
  }
}

// ---------------------------------------------------------------- export

/**
 * Ship queued spans. Returns how many were sent.
 *
 * Call before a short-lived process exits — serverless handlers especially — or the last batch
 * dies with the process.
 */
export async function flush(): Promise<number> {
  if (!cfg.active || queue.length === 0) return 0;
  const batch = queue.splice(0, queue.length);
  const body = {
    resourceSpans: [{
      resource: {
        attributes: [{ key: "service.name", value: { stringValue: "provekit-js" } }],
      },
      scopeSpans: [{ scope: { name: "provekit", version: "0.1.0" }, spans: batch }],
    }],
  };
  try {
    const res = await fetch(`${cfg.endpoint}/v1/traces`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${cfg.apiKey}` },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(cfg.timeoutMs),
    });
    if (!res.ok) {
      // Re-queueing a batch the server *rejected* (401, 422) would retry forever and grow the
      // queue without bound. Ingest is idempotent, so a genuinely retryable 5xx is safe to
      // replay — anything else is dropped.
      if (res.status >= 500) requeue(batch);
      return res.ok ? batch.length : 0;
    }
    return batch.length;
  } catch {
    requeue(batch);           // network failure: keep them for the next attempt
    return 0;
  }
}

function requeue(batch: RawSpan[]): void {
  const room = Math.max(0, cfg.maxQueue - queue.length);
  if (room < batch.length) dropped += batch.length - room;
  queue.unshift(...batch.slice(batch.length - room));
}

/** Flush and stop the background timer. Idempotent. */
export async function shutdown(): Promise<void> {
  await flush();
  if (timer) { clearInterval(timer); timer = null; }
}

/** Queue depth and drop count — for tests and for `diagnose()`. */
export function stats(): { queued: number; dropped: number } {
  return { queued: queue.length, dropped };
}

/** Test helper: clear queue and counters without touching configuration. */
export function _reset(): void {
  queue.length = 0;
  dropped = 0;
}
