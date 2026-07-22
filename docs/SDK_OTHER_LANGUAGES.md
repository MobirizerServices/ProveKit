# Go and Java — stock OpenTelemetry, no SDK

There is no ProveKit SDK for Go or Java, and you don't need one. Ingest is an OTLP endpoint:
any OpenTelemetry exporter that can reach it, in any language, produces the same nested flow in
the portal as the Python decorator does.

What you *do* need is the right attributes. ProveKit decides whether a span is an **agent**,
**llm**, **tool**, or **step** from its `gen_ai.*` attributes alone — span kind is ignored, and
the span name is only a fallback label. A Go service that opens a span called `openai.chat` and
sets nothing else lands as a generic step with no model, no tokens, and no cost. The same span
with four attributes lands as an LLM call.

```
  your Go / Java service ──▶ OTLP/JSON POST ──▶ /v1/traces ──▶ classified by gen_ai.* attributes
```

## The endpoint

| | |
|---|---|
| Path | `POST ${PROVEKIT_ENDPOINT}/v1/traces` |
| Body | OTLP `ExportTraceServiceRequest` as **JSON** |
| Content-Type | `application/json` |
| Auth | `Authorization: Bearer <project key>` |
| Success | `200` with `{"partialSuccess":{}}` |

The key is a `pk_` project key from the portal (**Project keys**, shown once), or the workspace
ingest key from `POST /api/workspace/ingest-key`. Either resolves to one project; a key that
matches neither gets `403 {"detail":"Invalid ingest key"}`.

`PROVEKIT_ENDPOINT` is your instance's origin — `http://localhost:8000` running from source,
`http://localhost:8100` under Docker Compose, `https://your-domain` when hosted. There is no
default hosted endpoint.

Other responses worth handling in your exporter's retry policy: `429` when the project exceeds
`INGEST_RATE_PER_MIN` (default 600), `503` with `Retry-After` when the ingest spool is backed
up, and `402` when the account is over `MONTHLY_SPAN_QUOTA`. Retries are safe — spans are
deduplicated on `(trace_id, span_id)`, so replaying a whole batch never doubles a row.

## JSON only, today

**Ingest parses the body as JSON. A protobuf body is not rejected — it is accepted and
dropped:**

```
POST /v1/traces  (Content-Type: application/x-protobuf)
→ 200 {"partialSuccess":{"rejectedSpans":0,"errorMessage":"invalid JSON"}}
```

`rejectedSpans: 0` means a standard exporter treats that as a successful export and moves on.
This is the failure everyone hits first, because protobuf is what the Go and Java exporters
send:

- **Go** — `otlptracehttp` posts protobuf and has no JSON encoding option.
- **Java** — autoconfigure's `otel.exporter.otlp.protocol` takes `grpc` and `http/protobuf`;
  `http/json` is not a first-class exporter option.

So neither language talks to ProveKit directly with the stock exporter. Two ways round it, both
below: run an **OpenTelemetry Collector** that re-encodes to JSON (recommended — it is one
config file and your application code stays stock), or **write a small JSON exporter** in your
service (Go example below; this is exactly what ProveKit's own Python SDK does in
`backend/provekit/trace.py`).

> gRPC and protobuf ingest is roadmap **#94**. Until it ships, `http/protobuf` and `grpc`
> exporters must terminate at a collector.

## The attributes that drive classification

Classification is a first-match ladder, evaluated in this order:

| # | Condition | Becomes | Operation |
|---|---|---|---|
| 1 | `gen_ai.tool.name` is set | **tool** | `execute_tool` |
| 2 | `gen_ai.operation.name` == `invoke_agent` | **agent** | `invoke_agent` |
| 3 | a **model** or **provider** attribute is set | **llm** | `gen_ai.operation.name`, else `chat` |
| 4 | anything else | **step** | `gen_ai.operation.name`, else the span name |

Two consequences worth internalising:

- **`gen_ai.tool.name` wins.** Set it on a span that also names a model and you get a tool, not
  an LLM call. Keep tool wrappers and model calls on separate spans.
- **Messages alone don't make an LLM call.** A span with `gen_ai.input.messages` but no model
  and no provider is a *step*. This is deliberate — it keeps retrieval and prompt-assembly
  spans out of the model-call metrics — but it means `gen_ai.request.model` is the single
  attribute you must not forget.

Everything else is extracted by first-non-empty across three dialects. Emit the **current**
column; the others exist so spans from existing instrumentation land correctly too.

| What ProveKit reads | current `gen_ai.*` (emit this) | legacy | OpenInference |
|---|---|---|---|
| model | `gen_ai.request.model` → `gen_ai.response.model` | `gen_ai.model` | `llm.model_name` |
| provider | `gen_ai.provider.name` | `gen_ai.system` | `llm.provider` |
| input | `gen_ai.input.messages` | `gen_ai.prompt` | `input.value`, `llm.input_messages` |
| output | `gen_ai.output.messages` | `gen_ai.completion` | `output.value`, `llm.output_messages` |
| input tokens | `gen_ai.usage.input_tokens` | `gen_ai.usage.prompt_tokens` | `llm.token_count.prompt` |
| output tokens | `gen_ai.usage.output_tokens` | `gen_ai.usage.completion_tokens` | `llm.token_count.completion` |
| tool name | `gen_ai.tool.name` | — | — |
| session / thread | `session.id`, `gen_ai.conversation.id` | `session_id` | `thread.id` |
| finish reason | `gen_ai.response.finish_reasons` (or `…finish_reason`) | — | `llm.response.finish_reason` |
| params | `gen_ai.request.temperature`, `gen_ai.request.top_p`, `gen_ai.request.max_tokens` | — | — |

Notes on the edges:

- **Message values are stringified.** ProveKit JSON-encodes whatever it finds, so a JSON
  string (`[{"role":"user","content":"…"}]`) and a structured value both render. Input is
  truncated at 8000 characters, the span label at 200.
- **Cost is derived, never sent.** The portal prices `model × input tokens × output tokens`
  against a table of known model prefixes (`frontend/lib/cost.ts`). Send the model name your
  provider uses — `gpt-4o-mini`, `claude-sonnet-4-…` — and the tokens; an unrecognised model
  shows tokens but no cost estimate rather than a wrong number.
- **Status** comes from the OTel span status: code `2` (ERROR) marks the run failed and the
  status description becomes its error message. Everything else is `completed`.
- **Tree shape** comes from `traceId` / `spanId` / `parentSpanId`, hex-encoded per the OTLP
  JSON spec. Set your parent context correctly and the portal rebuilds the flow; ProveKit does
  no re-parenting of its own.
- **Span events** are kept with their `log.level` and `log.logger` attributes, so a Go
  `slog`/Java `Logback` bridge that writes events onto the active span shows up on the span.
- Redaction (`REDACT_PII`, or the per-project toggle) runs over OTLP-ingested spans too, before
  storage.

## Go

### 1. Export to a collector

Application code stays stock `go.opentelemetry.io/otel`:

```go
import (
    "go.opentelemetry.io/otel"
    "go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracehttp"
    "go.opentelemetry.io/otel/sdk/resource"
    sdktrace "go.opentelemetry.io/otel/sdk/trace"
    semconv "go.opentelemetry.io/otel/semconv/v1.26.0"
)

func initTracing(ctx context.Context) (func(context.Context) error, error) {
    exp, err := otlptracehttp.New(ctx,
        otlptracehttp.WithEndpoint("localhost:4318"), // the collector, not ProveKit
        otlptracehttp.WithInsecure(),
    )
    if err != nil {
        return nil, err
    }
    tp := sdktrace.NewTracerProvider(
        sdktrace.WithBatcher(exp),
        sdktrace.WithResource(resource.NewWithAttributes(
            semconv.SchemaURL, semconv.ServiceName("billing-agent"))),
    )
    otel.SetTracerProvider(tp)
    return tp.Shutdown, nil
}
```

Collector config — the `otlphttp` exporter's `encoding: json` is the whole trick:

```yaml
receivers:
  otlp:
    protocols:
      http:  { endpoint: 0.0.0.0:4318 }
      grpc:  { endpoint: 0.0.0.0:4317 }

processors:
  batch:

exporters:
  otlphttp/provekit:
    traces_endpoint: http://localhost:8000/v1/traces   # 8100 under Docker Compose
    encoding: json
    headers:
      Authorization: "Bearer ${env:PROVEKIT_API_KEY}"

service:
  pipelines:
    traces:
      receivers:  [otlp]
      processors: [batch]
      exporters:  [otlphttp/provekit]
```

`traces_endpoint` is the explicit form; plain `endpoint:` also works and has `/v1/traces`
appended to it.

### 2. Or export JSON directly

If you'd rather not run a collector, replace the exporter with ~40 lines. Ingest accepts this
identically to the body ProveKit's own SDK sends — the one difference is that the Go snippet
below encodes `intValue` as a JSON string where the Python SDK uses a number, and
`services/otel.py` parses both:

```go
type pkExporter struct {
    url, key string
    client   *http.Client
}

func otlpValue(v attribute.Value) map[string]any {
    switch v.Type() {
    case attribute.BOOL:
        return map[string]any{"boolValue": v.AsBool()}
    case attribute.INT64:
        // int64 travels as a *string* in OTLP/JSON (proto3 JSON mapping).
        return map[string]any{"intValue": strconv.FormatInt(v.AsInt64(), 10)}
    case attribute.FLOAT64:
        return map[string]any{"doubleValue": v.AsFloat64()}
    case attribute.STRINGSLICE:
        vals := make([]any, 0, len(v.AsStringSlice()))
        for _, s := range v.AsStringSlice() {
            vals = append(vals, map[string]any{"stringValue": s})
        }
        return map[string]any{"arrayValue": map[string]any{"values": vals}}
    default:
        return map[string]any{"stringValue": v.Emit()}
    }
}

func (e *pkExporter) ExportSpans(ctx context.Context, spans []sdktrace.ReadOnlySpan) error {
    out := make([]map[string]any, 0, len(spans))
    for _, s := range spans {
        attrs := make([]map[string]any, 0, len(s.Attributes()))
        for _, kv := range s.Attributes() {
            attrs = append(attrs, map[string]any{"key": string(kv.Key), "value": otlpValue(kv.Value)})
        }
        code := 1
        if s.Status().Code == codes.Error {
            code = 2
        }
        span := map[string]any{
            "name":              s.Name(),
            "traceId":           s.SpanContext().TraceID().String(), // hex
            "spanId":            s.SpanContext().SpanID().String(),
            "startTimeUnixNano": strconv.FormatInt(s.StartTime().UnixNano(), 10),
            "endTimeUnixNano":   strconv.FormatInt(s.EndTime().UnixNano(), 10),
            "status":            map[string]any{"code": code, "message": s.Status().Description},
            "attributes":        attrs,
        }
        if p := s.Parent(); p.HasSpanID() {
            span["parentSpanId"] = p.SpanID().String()
        }
        out = append(out, span)
    }
    body, err := json.Marshal(map[string]any{"resourceSpans": []any{
        map[string]any{"scopeSpans": []any{map[string]any{"spans": out}}}}})
    if err != nil {
        return err
    }
    req, err := http.NewRequestWithContext(ctx, http.MethodPost, e.url, bytes.NewReader(body))
    if err != nil {
        return err
    }
    req.Header.Set("Content-Type", "application/json")
    req.Header.Set("Authorization", "Bearer "+e.key)
    resp, err := e.client.Do(req)
    if err != nil {
        return err
    }
    defer resp.Body.Close()
    if resp.StatusCode >= 400 {
        // 429/503 are retryable; 403 means the key is wrong.
        return fmt.Errorf("provekit ingest: HTTP %d", resp.StatusCode)
    }
    return nil
}

func (e *pkExporter) Shutdown(context.Context) error { return nil }
```

Hand it to `sdktrace.WithBatcher(&pkExporter{url: endpoint + "/v1/traces", key: apiKey, client: http.DefaultClient})`.

### 3. One LLM span

```go
tracer := otel.Tracer("billing-agent")

ctx, span := tracer.Start(ctx, "chat gpt-4o-mini", trace.WithSpanKind(trace.SpanKindClient))
defer span.End()

span.SetAttributes(
    attribute.String("gen_ai.operation.name", "chat"),
    attribute.String("gen_ai.provider.name", "openai"),
    attribute.String("gen_ai.request.model", "gpt-4o-mini"),   // ← without this it's a "step"
    attribute.Float64("gen_ai.request.temperature", 0.2),
    attribute.Int("gen_ai.request.max_tokens", 512),
    attribute.String("gen_ai.input.messages", string(promptJSON)),
    attribute.String("gen_ai.conversation.id", conversationID), // groups multi-turn runs
)

resp, err := client.Chat(ctx, req)
if err != nil {
    span.RecordError(err)
    span.SetStatus(codes.Error, err.Error())   // → the run shows as failed, with this message
    return err
}

span.SetAttributes(
    attribute.String("gen_ai.output.messages", string(answerJSON)),
    attribute.Int("gen_ai.usage.input_tokens", resp.Usage.PromptTokens),
    attribute.Int("gen_ai.usage.output_tokens", resp.Usage.CompletionTokens),
    attribute.StringSlice("gen_ai.response.finish_reasons", []string{resp.FinishReason}),
)
```

Wrap the whole request in a parent span with `gen_ai.operation.name = invoke_agent` and every
model call, tool call and step beneath it nests under one agent run — the same tree the Python
decorator produces.

## Java

### 1. Autoconfigure, pointed at a collector

Use the same collector config as above. Nothing in your build changes; the SDK is configured
entirely by environment:

```bash
OTEL_SERVICE_NAME=billing-agent
OTEL_TRACES_EXPORTER=otlp
OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318   # the collector
OTEL_METRICS_EXPORTER=none
OTEL_LOGS_EXPORTER=none
```

With the Java agent that is `-javaagent:opentelemetry-javaagent.jar`; with the SDK it is
`AutoConfiguredOpenTelemetrySdk.initialize()` plus
`io.opentelemetry:opentelemetry-sdk-extension-autoconfigure` on the classpath.

If you terminate at ProveKit through some other JSON-capable hop, the auth header travels in
`OTEL_EXPORTER_OTLP_HEADERS` — percent-encode the space:

```bash
OTEL_EXPORTER_OTLP_HEADERS=Authorization=Bearer%20pk_your_key
```

Or build the exporter in code, still protobuf, still collector-bound:

```java
SdkTracerProvider tracerProvider = SdkTracerProvider.builder()
    .addSpanProcessor(BatchSpanProcessor.builder(
        OtlpHttpSpanExporter.builder()
            .setEndpoint("http://localhost:4318/v1/traces")
            .build()).build())
    .setResource(Resource.getDefault().toBuilder()
        .put(ServiceAttributes.SERVICE_NAME, "billing-agent").build())
    .build();
```

### 2. One LLM span

```java
Tracer tracer = GlobalOpenTelemetry.getTracer("billing-agent");

Span span = tracer.spanBuilder("chat gpt-4o-mini")
    .setSpanKind(SpanKind.CLIENT)
    .startSpan();

try (Scope scope = span.makeCurrent()) {
    span.setAttribute("gen_ai.operation.name", "chat");
    span.setAttribute("gen_ai.provider.name", "openai");
    span.setAttribute("gen_ai.request.model", "gpt-4o-mini");   // ← without this it's a "step"
    span.setAttribute("gen_ai.request.temperature", 0.2);
    span.setAttribute("gen_ai.request.max_tokens", 512L);
    span.setAttribute("gen_ai.input.messages", promptJson);
    span.setAttribute("gen_ai.conversation.id", conversationId);

    ChatResponse resp = client.chat(request);

    span.setAttribute("gen_ai.output.messages", answerJson);
    span.setAttribute("gen_ai.usage.input_tokens", resp.usage().inputTokens());    // long
    span.setAttribute("gen_ai.usage.output_tokens", resp.usage().outputTokens());
    span.setAttribute(AttributeKey.stringArrayKey("gen_ai.response.finish_reasons"),
                      List.of(resp.finishReason()));
} catch (Exception e) {
    span.recordException(e);
    span.setStatus(StatusCode.ERROR, e.getMessage());
    throw e;
} finally {
    span.end();
}
```

Token counts must be `long` (or an explicit `AttributeKey.longKey(...)`) — a `String` token
count is stored as a string and never reaches the token or cost totals.

A tool call is the same pattern with `gen_ai.tool.name` set and no model attributes; an agent
root is `gen_ai.operation.name = "invoke_agent"`.

## Verifying it landed

Post one span by hand first — it isolates the endpoint and key from your exporter's encoding:

```bash
curl -sS -X POST "$PROVEKIT_ENDPOINT/v1/traces" \
  -H "Authorization: Bearer $PROVEKIT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"resourceSpans":[{"scopeSpans":[{"spans":[{
        "name":"chat gpt-4o-mini",
        "traceId":"5b8efff798038103d269b633813fc60c",
        "spanId":"eee19b7ec3c1b174",
        "startTimeUnixNano":"1700000000000000000",
        "endTimeUnixNano":"1700000000842000000",
        "status":{"code":1},
        "attributes":[
          {"key":"gen_ai.operation.name","value":{"stringValue":"chat"}},
          {"key":"gen_ai.provider.name","value":{"stringValue":"openai"}},
          {"key":"gen_ai.request.model","value":{"stringValue":"gpt-4o-mini"}},
          {"key":"gen_ai.input.messages","value":{"stringValue":"[{\"role\":\"user\",\"content\":\"hi\"}]"}},
          {"key":"gen_ai.output.messages","value":{"stringValue":"[{\"role\":\"assistant\",\"content\":\"hello\"}]"}},
          {"key":"gen_ai.usage.input_tokens","value":{"intValue":"31"}},
          {"key":"gen_ai.usage.output_tokens","value":{"intValue":"9"}}
        ]}]}]}]}'
```

`{"partialSuccess":{}}` means it was stored. Read it back with the same key:

```bash
curl -sS "$PROVEKIT_ENDPOINT/v1/traces/5b8efff798038103d269b633813fc60c" \
  -H "Authorization: Bearer $PROVEKIT_API_KEY"
```

Then open **Traces** in the portal. That span becomes an **llm** run labelled
`chat gpt-4o-mini`, 842 ms, with the messages, 31/9 tokens, and a cost estimate.

Reading the result:

| Symptom | Cause |
|---|---|
| `{"partialSuccess":{"rejectedSpans":0,"errorMessage":"invalid JSON"}}` | the body isn't JSON — your exporter is sending protobuf |
| `403 Invalid ingest key` | wrong or revoked key |
| Spans land as **step**, no model | `gen_ai.request.model` / `gen_ai.provider.name` missing |
| LLM spans show tokens but no cost | model name isn't in the pricing table — expected, not an error |
| Spans arrive flat, not nested | `parentSpanId` missing; the context isn't propagating across your call boundary |
| `429` / `503` | rate limit or ingest backpressure — retry; duplicates are deduped |

`pip install provekit && provekit-doctor --send` is a language-agnostic check of the key and
endpoint if you want to rule those out without touching your service.

## Untested here

The endpoint behaviour, the classification ladder, the attribute names, and the `curl` example
above were exercised against this repo's ingest code. The following were not, and are written
from the upstream OpenTelemetry contracts:

- The Go and Java snippets are illustrative — neither is compiled or run by this repo's CI.
- The collector `otlphttp` `encoding: json` pipeline has not been run end-to-end against a
  ProveKit instance here. If your collector version predates the `encoding` option, upgrade it
  or use the direct JSON exporter.
- Exporter capabilities move: re-check whether your Go/Java SDK version has gained an OTLP/JSON
  option before assuming the collector hop is still required.
