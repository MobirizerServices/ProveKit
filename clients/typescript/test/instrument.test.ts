/**
 * Provider instrumentation. The fakes mirror the real response shapes; what's asserted is that
 * a wrapped call produces a span the ProveKit backend classifies as an LLM call, with tokens
 * and finish reason — and that wrapping never changes what the caller receives.
 */
import assert from "node:assert/strict";
import test, { beforeEach } from "node:test";

import * as pk from "../src/index.js";

function captureFetch() {
  const calls: any[] = [];
  (globalThis as any).fetch = async (_url: string, opts: any = {}) => {
    calls.push(JSON.parse(opts.body ?? "{}"));
    return { ok: true, status: 200 };
  };
  return calls;
}

function spansOf(calls: any[]): any[] {
  return calls.flatMap((b) => b?.resourceSpans?.[0]?.scopeSpans?.[0]?.spans ?? []);
}

const attrs = (s: any) =>
  Object.fromEntries(s.attributes.map((a: any) => [a.key, Object.values(a.value)[0]]));

beforeEach(() => {
  pk._reset();
  pk.init({ apiKey: "pk_test", endpoint: "http://portal.test", flushIntervalMs: 0, batchSize: 1000 });
});

// --- fakes ------------------------------------------------------------------

const fakeOpenAI = (impl: (args: any) => any) => ({
  chat: { completions: { create: impl } },
  models: { list: async () => ["gpt-4o"] },      // an untouched method, for pass-through
});

const fakeAnthropic = (impl: (args: any) => any) => ({ messages: { create: impl } });

const OPENAI_REPLY = {
  model: "gpt-4o-2024-08-06",
  choices: [{ message: { role: "assistant", content: "Paris." }, finish_reason: "stop" }],
  usage: { prompt_tokens: 120, completion_tokens: 4 },
};

// --- tests ------------------------------------------------------------------

test("an OpenAI completion becomes an LLM span with tokens and finish reason", async () => {
  const calls = captureFetch();
  const client = pk.observeOpenAI(fakeOpenAI(async () => OPENAI_REPLY));

  const run = pk.trace("agent", async () => {
    return await (client as any).chat.completions.create({
      model: "gpt-4o", messages: [{ role: "user", content: "capital of France?" }],
      temperature: 0.2, max_tokens: 100,
    });
  });
  const res = await run();
  assert.equal(res, OPENAI_REPLY, "the caller must receive the provider's response untouched");
  await pk.flush();

  const llm = spansOf(calls).find((s) => s.name.startsWith("chat "))!;
  const a = attrs(llm);
  // provider + model are what make the backend classify this as `llm`, not a generic step
  assert.equal(a["gen_ai.provider.name"], "openai");
  assert.equal(a["gen_ai.request.model"], "gpt-4o");
  assert.equal(a["gen_ai.operation.name"], "chat");
  assert.equal(a["gen_ai.usage.input_tokens"], 120);
  assert.equal(a["gen_ai.usage.output_tokens"], 4);
  assert.equal(a["gen_ai.response.finish_reasons"], "stop");
  assert.equal(a["gen_ai.request.temperature"], 0.2);
  assert.match(String(a["gen_ai.input.messages"]), /capital of France/);
  assert.equal(a["gen_ai.output.messages"], "Paris.");
});

test("the LLM span nests under the active trace", async () => {
  const calls = captureFetch();
  const client = pk.observeOpenAI(fakeOpenAI(async () => OPENAI_REPLY));
  const run = pk.trace("agent", async () => {
    await (client as any).chat.completions.create({ model: "gpt-4o", messages: [] });
  });
  await run();
  await pk.flush();

  const spans = spansOf(calls);
  const root = spans.find((s) => s.name === "agent")!;
  const llm = spans.find((s) => s.name.startsWith("chat "))!;
  assert.equal(llm.parentSpanId, root.spanId);
  assert.equal(llm.traceId, root.traceId);
});

test("a provider error is recorded and rethrown unchanged", async () => {
  const calls = captureFetch();
  const client = pk.observeOpenAI(fakeOpenAI(async () => { throw new Error("rate limited"); }));
  await assert.rejects(
    (client as any).chat.completions.create({ model: "gpt-4o", messages: [] }), /rate limited/);
  await pk.flush();
  const llm = spansOf(calls)[0];
  assert.equal(llm.status.code, 2);
  assert.equal(llm.status.message, "rate limited");
});

test("a streamed completion closes its span only once the caller drains it", async () => {
  const calls = captureFetch();
  async function* stream() {
    yield { choices: [{ delta: { content: "Hello" } }] };
    yield { choices: [{ delta: { content: " world" } }] };
    yield { choices: [{ delta: {} }], usage: { prompt_tokens: 9, completion_tokens: 2 } };
  }
  const client = pk.observeOpenAI(fakeOpenAI(async () => stream()));

  const res = await (client as any).chat.completions.create({
    model: "gpt-4o", messages: [], stream: true });

  // Nothing recorded yet: the call returned, but not a single token has been read.
  assert.equal(pk.stats().queued, 0);

  let text = "";
  for await (const chunk of res as AsyncIterable<any>) {
    text += chunk.choices[0].delta.content ?? "";
  }
  assert.equal(text, "Hello world", "chunks must pass through to the caller unchanged");

  await pk.flush();
  const a = attrs(spansOf(calls)[0]);
  assert.equal(a["gen_ai.output.messages"], "Hello world", "accumulated from the deltas");
  assert.equal(a["gen_ai.usage.input_tokens"], 9);
  assert.equal(a["gen_ai.usage.output_tokens"], 2);
});

test("abandoning a stream early still closes the span", async () => {
  const calls = captureFetch();
  async function* stream() {
    yield { choices: [{ delta: { content: "one" } }] };
    yield { choices: [{ delta: { content: "two" } }] };
    yield { choices: [{ delta: { content: "three" } }] };
  }
  const client = pk.observeOpenAI(fakeOpenAI(async () => stream()));
  const res = await (client as any).chat.completions.create({ model: "gpt-4o", messages: [], stream: true });

  for await (const _c of res as AsyncIterable<any>) break;   // caller gives up after one chunk

  await pk.flush();
  // Without a finally, this span would never be emitted and the trace would stay incomplete.
  assert.equal(spansOf(calls).length, 1);
  assert.equal(attrs(spansOf(calls)[0])["gen_ai.output.messages"], "one");
});

test("a mid-stream failure marks the span failed", async () => {
  const calls = captureFetch();
  async function* stream() {
    yield { choices: [{ delta: { content: "partial" } }] };
    throw new Error("connection reset");
  }
  const client = pk.observeOpenAI(fakeOpenAI(async () => stream()));
  const res = await (client as any).chat.completions.create({ model: "gpt-4o", messages: [], stream: true });

  await assert.rejects(async () => { for await (const _ of res as AsyncIterable<any>) { /* drain */ } },
    /connection reset/);
  await pk.flush();
  const s = spansOf(calls)[0];
  assert.equal(s.status.code, 2);
  assert.equal(attrs(s)["gen_ai.output.messages"], "partial", "keep what did arrive");
});

test("Anthropic's different shapes map to the same attributes", async () => {
  const calls = captureFetch();
  const client = pk.observeAnthropic(fakeAnthropic(async () => ({
    model: "claude-sonnet-4",
    content: [{ type: "text", text: "Bonjour" }],
    stop_reason: "end_turn",
    usage: { input_tokens: 30, output_tokens: 3 },
  })));

  await (client as any).messages.create({
    model: "claude-sonnet-4", system: "be brief",
    messages: [{ role: "user", content: "hi" }], max_tokens: 64,
  });
  await pk.flush();

  const a = attrs(spansOf(calls)[0]);
  assert.equal(a["gen_ai.provider.name"], "anthropic");
  assert.equal(a["gen_ai.usage.input_tokens"], 30);
  assert.equal(a["gen_ai.usage.output_tokens"], 3);
  assert.equal(a["gen_ai.response.finish_reasons"], "end_turn");
  assert.equal(a["gen_ai.output.messages"], "Bonjour");
  assert.match(String(a["gen_ai.input.messages"]), /be brief/, "the system prompt is part of the input");
});

test("Anthropic streaming accumulates text and both token counts", async () => {
  const calls = captureFetch();
  async function* stream() {
    yield { type: "message_start", message: { usage: { input_tokens: 15 } } };
    yield { type: "content_block_delta", delta: { text: "Sal" } };
    yield { type: "content_block_delta", delta: { text: "ut" } };
    yield { type: "message_delta", usage: { output_tokens: 2 } };
  }
  const client = pk.observeAnthropic(fakeAnthropic(async () => stream()));
  const res = await (client as any).messages.create({ model: "claude-sonnet-4", messages: [], stream: true });
  for await (const _c of res as AsyncIterable<any>) { /* drain */ }
  await pk.flush();

  const a = attrs(spansOf(calls)[0]);
  assert.equal(a["gen_ai.output.messages"], "Salut");
  assert.equal(a["gen_ai.usage.input_tokens"], 15);
  assert.equal(a["gen_ai.usage.output_tokens"], 2);
});

test("a tool-calling turn isn't recorded as empty", async () => {
  const calls = captureFetch();
  const client = pk.observeOpenAI(fakeOpenAI(async () => ({
    choices: [{
      message: { role: "assistant", content: null, tool_calls: [{ function: { name: "get_weather" } }] },
      finish_reason: "tool_calls",
    }],
  })));
  await (client as any).chat.completions.create({ model: "gpt-4o", messages: [] });
  await pk.flush();
  assert.match(String(attrs(spansOf(calls)[0])["gen_ai.output.messages"]), /get_weather/);
});

test("the client isn't mutated and unknown methods pass through", async () => {
  captureFetch();
  const original = fakeOpenAI(async () => OPENAI_REPLY);
  const wrapped = pk.observeOpenAI(original);

  assert.deepEqual(await (wrapped as any).models.list(), ["gpt-4o"]);   // untouched path
  await (wrapped as any).chat.completions.create({ model: "gpt-4o", messages: [] });
  await pk.flush();
  assert.equal(pk.stats().queued, 0);

  // The original object is a plain client still: calling it directly records nothing.
  pk._reset();
  await original.chat.completions.create({ model: "gpt-4o", messages: [] });
  assert.equal(pk.stats().queued, 0, "wrapping must not mutate the client passed in");
});

test("with tracing inactive the wrapper is a pass-through", async () => {
  pk.init({ apiKey: "", endpoint: "" });
  const client = pk.observeOpenAI(fakeOpenAI(async () => OPENAI_REPLY));
  assert.equal(await (client as any).chat.completions.create({ model: "gpt-4o", messages: [] }),
    OPENAI_REPLY);
  assert.equal(pk.stats().queued, 0);
});
