/**
 * The properties that matter for a tracer: it never changes program behaviour, it nests
 * correctly across `await`, and it degrades quietly when the portal isn't there.
 */
import assert from "node:assert/strict";
import test, { beforeEach } from "node:test";

import * as pk from "../src/index.js";

const ENDPOINT = "http://portal.test";

/** Capture what the SDK would have sent, without a network. */
function captureFetch() {
  const calls: { url: string; body: any; headers: Record<string, string> }[] = [];
  (globalThis as any).fetch = async (url: string, opts: any = {}) => {
    calls.push({ url: String(url), body: JSON.parse(opts.body ?? "{}"), headers: opts.headers ?? {} });
    return { ok: true, status: 200 };
  };
  return calls;
}

function spansOf(calls: { body: any }[]): any[] {
  return calls.flatMap((c) => c.body?.resourceSpans?.[0]?.scopeSpans?.[0]?.spans ?? []);
}

beforeEach(() => {
  pk._reset();
  pk.init({ apiKey: "pk_test", endpoint: ENDPOINT, flushIntervalMs: 0, batchSize: 1000 });
});

test("inactive without a key or endpoint, and the wrapped function still runs", async () => {
  pk.init({ apiKey: "", endpoint: "" });
  assert.equal(pk.isActive(), false);

  const run = pk.trace("agent", async (x: number) => x * 2);
  assert.equal(await run(21), 42);          // fail-open: behaviour is unchanged
  assert.equal(pk.stats().queued, 0);
});

test("a traced call is captured with input, output and ok status", async () => {
  const calls = captureFetch();
  const run = pk.trace("support-agent", async (q: string) => `answer to ${q}`);
  assert.equal(await run("hello"), "answer to hello");
  await pk.flush();

  const spans = spansOf(calls);
  assert.equal(spans.length, 1);
  const s = spans[0];
  assert.equal(s.name, "support-agent");
  assert.equal(s.status.code, 1);
  assert.equal(s.parentSpanId, "");
  assert.match(s.traceId, /^[0-9a-f]{32}$/);   // the ingest rebuilds the tree from these
  assert.match(s.spanId, /^[0-9a-f]{16}$/);
  const keys = Object.fromEntries(s.attributes.map((a: any) => [a.key, a.value]));
  assert.equal(keys["gen_ai.operation.name"].stringValue, "invoke_agent");
  assert.match(keys["gen_ai.input.messages"].stringValue, /hello/);
  assert.match(keys["gen_ai.output.messages"].stringValue, /answer to hello/);
});

test("nested spans share a trace and point at their parent, across await", async () => {
  const calls = captureFetch();
  const run = pk.trace("root", async () => {
    await pk.span("retrieve", async () => {
      await new Promise((r) => setTimeout(r, 5));       // the await boundary context must survive
      await pk.span("rerank", async () => "ok");
    });
    await pk.span("generate", async () => "done");
  });
  await run();
  await pk.flush();

  const spans = spansOf(calls);
  const byName = Object.fromEntries(spans.map((s) => [s.name, s]));
  assert.equal(spans.length, 4);
  const traceIds = new Set(spans.map((s) => s.traceId));
  assert.equal(traceIds.size, 1, "one run is one trace");

  assert.equal(byName.root.parentSpanId, "");
  assert.equal(byName.retrieve.parentSpanId, byName.root.spanId);
  assert.equal(byName.rerank.parentSpanId, byName.retrieve.spanId);
  assert.equal(byName.generate.parentSpanId, byName.root.spanId);
});

test("concurrent traces don't bleed into each other", async () => {
  const calls = captureFetch();
  const run = pk.trace("agent", async (tag: string) => {
    await pk.span(`step-${tag}`, async () => {
      await new Promise((r) => setTimeout(r, tag === "a" ? 10 : 1));
    });
  });
  await Promise.all([run("a"), run("b")]);
  await pk.flush();

  const spans = spansOf(calls);
  const a = spans.find((s) => s.name === "step-a")!;
  const b = spans.find((s) => s.name === "step-b")!;
  assert.notEqual(a.traceId, b.traceId, "interleaved runs must not merge into one trace");
  assert.equal(a.parentSpanId, spans.find((s) => s.spanId === a.parentSpanId)!.spanId);
});

test("a throwing function is recorded as failed and the error still propagates", async () => {
  const calls = captureFetch();
  const run = pk.trace("agent", async () => { throw new Error("model refused"); });

  await assert.rejects(run(), /model refused/);        // behaviour unchanged
  await pk.flush();

  const s = spansOf(calls)[0];
  assert.equal(s.status.code, 2);
  assert.equal(s.status.message, "model refused");
});

test("session id groups multi-turn runs and is inherited by children", async () => {
  const calls = captureFetch();
  const run = pk.trace("turn", async () => { await pk.span("inner", async () => 1); },
    { sessionId: "conv-7" });
  await run();
  await pk.flush();

  for (const s of spansOf(calls)) {
    const keys = Object.fromEntries(s.attributes.map((a: any) => [a.key, a.value]));
    assert.equal(keys["session.id"].stringValue, "conv-7");
  }
});

test("a portal outage never surfaces to the caller and spans are retried", async () => {
  (globalThis as any).fetch = async () => { throw new Error("ECONNREFUSED"); };
  const run = pk.trace("agent", async () => "fine");
  assert.equal(await run(), "fine");                   // the agent is unaffected
  assert.equal(await pk.flush(), 0);
  assert.equal(pk.stats().queued, 1, "kept for the next attempt, not lost");

  const calls = captureFetch();
  assert.equal(await pk.flush(), 1);                   // recovers when the portal returns
  assert.equal(spansOf(calls).length, 1);
});

test("a rejected batch is dropped rather than retried forever", async () => {
  (globalThis as any).fetch = async () => ({ ok: false, status: 401 });
  const run = pk.trace("agent", async () => "x");
  await run();
  await pk.flush();
  // A 401 will never succeed on replay; retrying it would grow the queue without bound.
  assert.equal(pk.stats().queued, 0);
});

test("a 5xx is retried, because ingest is idempotent", async () => {
  (globalThis as any).fetch = async () => ({ ok: false, status: 503 });
  const run = pk.trace("agent", async () => "x");
  await run();
  await pk.flush();
  assert.equal(pk.stats().queued, 1);
});

test("the queue is bounded and reports what it dropped", async () => {
  pk.init({ apiKey: "pk_test", endpoint: ENDPOINT, flushIntervalMs: 0, batchSize: 100000, maxQueue: 3 });
  (globalThis as any).fetch = async () => { throw new Error("down"); };
  const run = pk.trace("agent", async () => "x");
  for (let i = 0; i < 10; i++) await run();
  assert.equal(pk.stats().queued, 3, "bounded — a portal outage must not become a memory leak");
  assert.ok(pk.stats().dropped > 0);
  assert.ok(pk.diagnose().problems.some((p) => /dropped/.test(p)));
});

test("diagnose names the misconfiguration instead of staying silent", () => {
  pk.init({ apiKey: "", endpoint: "" });
  const d = pk.diagnose();
  assert.equal(d.active, false);
  assert.ok(d.problems.some((p) => /PROVEKIT_API_KEY/.test(p)));
  assert.ok(d.problems.some((p) => /PROVEKIT_ENDPOINT/.test(p)));

  // The mistake the Python doctor catches most often.
  pk.init({ apiKey: "pk_x", endpoint: "https://portal.test/v1/traces" });
  assert.ok(pk.diagnose().problems.some((p) => /already ends in/.test(p)));
});

test("currentTraceId correlates your own logs, and is null outside a trace", async () => {
  assert.equal(pk.currentTraceId(), null);
  captureFetch();
  let seen: string | null = null;
  const run = pk.trace("agent", async () => { seen = pk.currentTraceId(); });
  await run();
  assert.match(seen!, /^[0-9a-f]{32}$/);
});

test("circular and exotic payloads don't break the caller", async () => {
  const calls = captureFetch();
  const cyclic: any = { a: 1 };
  cyclic.self = cyclic;
  const run = pk.trace("agent", async (_x: unknown) => ({ big: 10n }));
  await run(cyclic);                                    // must not throw
  await pk.flush();
  const s = spansOf(calls)[0];
  const keys = Object.fromEntries(s.attributes.map((a: any) => [a.key, a.value]));
  assert.match(keys["gen_ai.input.messages"].stringValue, /circular/);
  assert.match(keys["gen_ai.output.messages"].stringValue, /10/);
});

test("the bearer key is sent, and the ingest path is appended once", async () => {
  const calls = captureFetch();
  pk.init({ apiKey: "pk_secret", endpoint: `${ENDPOINT}/`, flushIntervalMs: 0 });
  const run = pk.trace("agent", async () => "x");
  await run();
  await pk.flush();
  assert.equal(calls[0].url, `${ENDPOINT}/v1/traces`);   // trailing slash normalised
  assert.equal(calls[0].headers.Authorization, "Bearer pk_secret");
});
