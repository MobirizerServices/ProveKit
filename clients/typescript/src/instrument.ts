/**
 * Provider auto-instrumentation.
 *
 *     const openai = pk.observeOpenAI(new OpenAI());
 *     // every completion is now an LLM span with model, messages, tokens and finish reason
 *
 * **Why wrapping and not monkey-patching.** The Python SDK patches provider libraries at import
 * time because `import` there is interceptable. In ESM it is not, without a loader hook that
 * has to be installed before anything else and breaks under bundlers. Wrapping the client is
 * one honest line at the call site, works identically in ESM/CJS/bundled/serverless, and can't
 * silently stop working after someone changes their build. It's also what the caller can *see*,
 * which matters when the alternative failure mode is a silently untraced app.
 *
 * The wrapper is a `Proxy`, so it doesn't mutate the client you pass in, and any method we
 * don't know about passes straight through untouched.
 */
import { AttrValue, OpenSpan, SpanOptions, startSpan } from "./index.js";

// ---------------------------------------------------------------- proxy plumbing

type AnyFn = (...args: any[]) => any;

/**
 * Return a proxy of `target` where the function at `path` is replaced by `wrap(original)`.
 * Everything else resolves normally.
 */
function proxyPath<T extends object>(target: T, path: string[], wrap: (fn: AnyFn) => AnyFn): T {
  const [head, ...rest] = path;
  return new Proxy(target, {
    get(obj, prop, receiver) {
      const value = Reflect.get(obj, prop, receiver);
      if (prop !== head) return value;
      if (rest.length === 0) {
        // Bind to the owner so provider SDKs that rely on `this` keep working.
        return typeof value === "function" ? wrap((value as AnyFn).bind(obj)) : value;
      }
      return value && typeof value === "object"
        ? proxyPath(value as object, rest, wrap)
        : value;
    },
  }) as T;
}

// ---------------------------------------------------------------- provider adapters

interface Adapter {
  provider: string;
  /** Attributes known before the call. */
  request(args: any): Record<string, AttrValue>;
  /** Attributes from a completed non-streaming response. */
  response(res: any): Record<string, AttrValue>;
  /** Text and usage carried by one streamed chunk, if any. */
  chunk(c: any): { text?: string; usage?: Record<string, AttrValue> };
}

/** Shared: the request fields both providers spell the same way. */
function commonRequest(args: any): Record<string, AttrValue> {
  const out: Record<string, AttrValue> = {};
  if (args?.model) out["gen_ai.request.model"] = String(args.model);
  if (typeof args?.temperature === "number") out["gen_ai.request.temperature"] = args.temperature;
  if (typeof args?.max_tokens === "number") out["gen_ai.request.max_tokens"] = args.max_tokens;
  return out;
}

function messagesText(messages: unknown): string {
  try {
    return JSON.stringify(messages).slice(0, 8000);
  } catch {
    return "";
  }
}

const OPENAI: Adapter = {
  provider: "openai",
  request(args) {
    const out = commonRequest(args);
    if (typeof args?.max_completion_tokens === "number") {
      out["gen_ai.request.max_tokens"] = args.max_completion_tokens;
    }
    if (args?.messages) out["gen_ai.input.messages"] = messagesText(args.messages);
    return out;
  },
  response(res) {
    const out: Record<string, AttrValue> = {};
    const choice = res?.choices?.[0];
    const text = choice?.message?.content;
    if (text != null) out["gen_ai.output.messages"] = String(text).slice(0, 8000);
    else if (choice?.message?.tool_calls) {
      // A tool-calling turn has no content. Recording nothing would make it look empty.
      out["gen_ai.output.messages"] = messagesText(choice.message.tool_calls);
    }
    if (choice?.finish_reason) out["gen_ai.response.finish_reasons"] = String(choice.finish_reason);
    if (res?.model) out["gen_ai.response.model"] = String(res.model);
    const u = res?.usage;
    if (u?.prompt_tokens != null) out["gen_ai.usage.input_tokens"] = u.prompt_tokens;
    if (u?.completion_tokens != null) out["gen_ai.usage.output_tokens"] = u.completion_tokens;
    return out;
  },
  chunk(c) {
    const out: { text?: string; usage?: Record<string, AttrValue> } = {};
    const delta = c?.choices?.[0]?.delta?.content;
    if (typeof delta === "string") out.text = delta;
    // Only present when the caller passed stream_options:{include_usage:true}; absent is normal.
    if (c?.usage?.prompt_tokens != null) {
      out.usage = {
        "gen_ai.usage.input_tokens": c.usage.prompt_tokens,
        "gen_ai.usage.output_tokens": c.usage.completion_tokens ?? 0,
      };
    }
    return out;
  },
};

const ANTHROPIC: Adapter = {
  provider: "anthropic",
  request(args) {
    const out = commonRequest(args);
    const parts: unknown[] = [];
    if (args?.system) parts.push({ role: "system", content: args.system });
    if (args?.messages) parts.push(...args.messages);
    if (parts.length) out["gen_ai.input.messages"] = messagesText(parts);
    return out;
  },
  response(res) {
    const out: Record<string, AttrValue> = {};
    if (Array.isArray(res?.content)) {
      const text = res.content.filter((b: any) => b?.type === "text").map((b: any) => b.text).join("");
      out["gen_ai.output.messages"] = text || messagesText(res.content);
    }
    if (res?.stop_reason) out["gen_ai.response.finish_reasons"] = String(res.stop_reason);
    if (res?.model) out["gen_ai.response.model"] = String(res.model);
    const u = res?.usage;
    if (u?.input_tokens != null) out["gen_ai.usage.input_tokens"] = u.input_tokens;
    if (u?.output_tokens != null) out["gen_ai.usage.output_tokens"] = u.output_tokens;
    return out;
  },
  chunk(c) {
    const out: { text?: string; usage?: Record<string, AttrValue> } = {};
    if (c?.type === "content_block_delta" && typeof c?.delta?.text === "string") {
      out.text = c.delta.text;
    }
    // Anthropic reports input tokens on message_start and output on message_delta.
    const started = c?.message?.usage?.input_tokens;
    if (started != null) out.usage = { "gen_ai.usage.input_tokens": started };
    if (c?.type === "message_delta" && c?.usage?.output_tokens != null) {
      out.usage = { ...(out.usage ?? {}), "gen_ai.usage.output_tokens": c.usage.output_tokens };
    }
    return out;
  },
};

// ---------------------------------------------------------------- the wrapper

function isAsyncIterable(v: any): boolean {
  return v != null && typeof v[Symbol.asyncIterator] === "function";
}

/**
 * Wrap a streamed response so the span closes when the caller finishes reading — not when the
 * call returns, which is before a single token has arrived.
 *
 * `finally` rather than only the normal path: a caller who `break`s out of the loop, or an
 * error mid-stream, must still close the span or the trace would be permanently incomplete.
 */
async function* traceStream(
  stream: AsyncIterable<any>,
  span: OpenSpan,
  adapter: Adapter,
): AsyncGenerator<any> {
  let text = "";
  let usage: Record<string, AttrValue> = {};
  let failure: unknown;
  try {
    for await (const chunk of stream) {
      const got = adapter.chunk(chunk);
      if (got.text) text += got.text;
      if (got.usage) usage = { ...usage, ...got.usage };
      yield chunk;
    }
  } catch (err) {
    failure = err;
    throw err;
  } finally {
    span.setAttributes({ ...usage, "gen_ai.output.messages": text.slice(0, 8000) });
    span.end(failure);
  }
}

function instrument<T extends object>(client: T, path: string[], adapter: Adapter,
                                      options: SpanOptions = {}): T {
  return proxyPath(client, path, (original) => (...args: any[]) => {
    const span = startSpan(`chat ${args?.[0]?.model ?? adapter.provider}`, {
      ...options,
      operation: "chat",
      attributes: {
        // provider + model are what make the backend classify this as an LLM call rather
        // than a generic step.
        "gen_ai.provider.name": adapter.provider,
        ...adapter.request(args?.[0]),
        ...(options.attributes ?? {}),
      },
    });
    if (!span) return original(...args);        // tracing inactive → zero overhead

    let result: any;
    try {
      result = original(...args);
    } catch (err) {                             // a synchronous throw (bad arguments)
      span.end(err);
      throw err;
    }

    if (!(result instanceof Promise)) {
      // Some SDKs return a stream object directly rather than a promise of one.
      return isAsyncIterable(result) ? traceStream(result, span, adapter) : (span.end(), result);
    }
    return result.then(
      (res: any) => {
        if (isAsyncIterable(res)) return traceStream(res, span, adapter);
        span.setAttributes(adapter.response(res));
        span.end();
        return res;
      },
      (err: unknown) => { span.end(err); throw err; },
    );
  });
}

/**
 * Trace every completion made through an OpenAI client.
 *
 *     const openai = pk.observeOpenAI(new OpenAI());
 *
 * Returns a proxy — the original client is not modified, and unknown methods pass through.
 */
export function observeOpenAI<T extends object>(client: T, options: SpanOptions = {}): T {
  return instrument(client, ["chat", "completions", "create"], OPENAI, options);
}

/**
 * Trace every message created through an Anthropic client.
 *
 *     const anthropic = pk.observeAnthropic(new Anthropic());
 */
export function observeAnthropic<T extends object>(client: T, options: SpanOptions = {}): T {
  return instrument(client, ["messages", "create"], ANTHROPIC, options);
}
