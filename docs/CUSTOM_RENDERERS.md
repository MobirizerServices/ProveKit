# Custom span renderers

ProveKit renders a span generically: input, output, error, plus the parameters it recognised.
That is right for a model call and wrong for *your* span. A retrieval is a ranked document
list. A simulation step is a state diff. A game turn is a board. Rendered as a JSON blob in a
`<pre>`, all three are technically complete and practically unreadable.

A **span renderer** is a small React component you register against a span label namespace.
When a span matches, it renders in place of the default input/output view — in the flow
inspector's **Output** tab and in the expanded waterfall row. Everything else about the span
(Raw, Node, Logs, notes, re-run) is untouched.

Implementation: [`frontend/components/spanRenderers.tsx`](../frontend/components/spanRenderers.tsx).

---

## The key: the span label's leading segment

A renderer is keyed on the **first segment of the span label**, lowercased — everything up to
the first `.`, `:`, `/` or space:

| label | key |
| --- | --- |
| `retrieval.query` | `retrieval` |
| `retrieval:kb_search` | `retrieval` |
| `sim.step` | `sim` |
| `retrieve` | `retrieve` |
| `chat gpt-4o` | `chat` |

The label is what you passed to `pk.span("retrieval.query")` (or the OTel span name), so the
key is under your control from your own code, with no portal configuration.

### Why not `span.type`, or a metadata field?

Both were considered and both are worse today:

- **`span.type`** (`agent` / `llm` / `tool` / `step`) is assigned by ProveKit's classifier in
  `services/otel.py`, not by you. Four values total, and every retrieval in the world lands in
  the same bucket as every other tool call. Too coarse to key on.
- **A custom metadata field** (say `result.meta.pk_renderer`) would be the nicest contract, and
  is where this should go if ingest ever grows an attribute passthrough. It does not work
  today: `map_span()` builds `result.meta` from a fixed whitelist — `provider`, `model`,
  `usage`, `params`, `finish_reason`, `events`, `tool`, `session_id`, `truncation`, `start_ns`,
  `price_version` — so an arbitrary attribute you set on the span is dropped at ingest, and a
  registry keyed on it would never fire once.

**What that cost:** this feature ships without any change to the schema or the ingest mapper,
so the key had to be a field that is already stored. The label is the only team-controlled one.
Namespace yours (`yourteam.thing`) so two teams' renderers can't collide.

Two consequences worth knowing:

- A redacted share link can withhold `label` (`services/share.py`). Those spans have no key and
  render with the default view — deliberately: a reader who wasn't shown the label shouldn't be
  handed a domain view inferred from it.
- If a span carries a model attribute it is classified `llm` and its label becomes
  `"<operation> <model>"`, not the span name. Don't set `gen_ai.request.model` /
  `embedding.model_name` on a span whose name you want to key on.

---

## The contract

```ts
interface SpanRenderer {
  key: string;                              // label namespace, lowercase
  title: string;                            // shown above your view
  match?: (span: TraceSpan) => boolean;     // optional extra narrowing
  render: (props: { span: TraceSpan }) => React.ReactNode;   // null = decline
}

registerSpanRenderer(r: SpanRenderer): () => void   // returns an unregister fn
unregisterSpanRenderer(key: string): void
listSpanRenderers(): SpanRenderer[]
```

Resolution, in order:

1. Compute the key from `span.label`. No label → default view.
2. Look the key up. Nothing registered → default view.
3. Call `match(span)` if present. False → default view.
4. Call `render({ span })`. Returns `null` → default view, silently.
5. Otherwise your node renders, under a strip showing `title` and a **Show raw** toggle that
   reveals the default view underneath. The captured payload is never hidden from the reader.

`render` runs during the parent's render, so it must be pure. If you need hooks, state or
effects, return an element — `return <MyView span={span} />` — and put them in there.

### Falling back is total

A debugging tool that dies on the span you are debugging is worse than a plain one, so every
failure mode ends at the default view:

| what happens | result |
| --- | --- |
| no renderer for the key | default view |
| `match()` throws | default view; renderer disabled for the session |
| `render()` throws | default view + a one-line note; renderer disabled |
| a component *inside* your returned tree throws | error boundary catches it → default view + note; renderer disabled |
| `render()` returns `null` | default view, no note (a decline is not a failure) |

A renderer that has thrown is marked failed and skipped for the rest of the page session, so a
broken renderer can't throw once per row on a 400-span trace. The failure is logged to the
console with the renderer key. The boundary is keyed per span, so a crash on one node doesn't
latch for the next.

**Not covered** — the same limits React error boundaries always have: a throw inside an event
handler, a `setTimeout`, or an unawaited promise is not caught. Wrap your own handlers.

---

## Registering one

Renderers live in the frontend bundle, so registration is code, not configuration.

**Ship it with the app** (the usual way) — add a module-scope call at the bottom of
`frontend/components/spanRenderers.tsx`, next to the built-in example:

```tsx
registerSpanRenderer({
  key: "sim",
  title: "Simulation state",
  match: (s) => !!s.result?.text?.startsWith("{"),
  render: ({ span }) => <SimState span={span} />,
});
```

**Register at runtime** from any client component (useful when the renderer lives in a page or
a feature module that isn't always loaded):

```tsx
useEffect(() => registerSpanRenderer(myRenderer), []);   // returns the unregister fn
```

Views already on screen re-resolve when the registry changes, so a renderer registered after
mount appears without a reload.

To drop a renderer you don't want — including the built-in one:

```tsx
unregisterSpanRenderer("retrieval");
```

---

## Worked example: retrieval

Registered by default. Any span whose label starts with `retrieval` and whose output parses as
a document list renders as a ranked result list — rank, source, a relative score bar, and the
chunk text — instead of one long JSON string.

The renderer (abridged from `spanRenderers.tsx`):

```tsx
export const retrievalRenderer: SpanRenderer = {
  key: "retrieval",
  title: "Retrieval",
  // Declining here is what makes the fallback silent: the namespace is ours, this payload isn't.
  match: (s) => parseDocuments(s.result?.text ?? s.result?.output) != null,
  render: (p) => <RetrievalView {...p} />,
};
```

`parseDocuments` accepts a bare array or `{documents|results|chunks: [...]}`, where each item is
a string or an object with `text` / `content` / `page_content` / `chunk`, plus optional `id`,
`source` (or `metadata.source`) and `score` / `distance`. Anything else returns `null` — which
is how the renderer declines a span it can't improve on. Score bars are scaled to the top score
*within that span*, because retrieval scores are only comparable inside one query.

To light it up, name the span in the `retrieval` namespace and put the documents on the span's
output attribute:

```python
import json, provekit as pk

with pk.span("retrieval.query") as s:
    docs = search(question)                      # [{"id": ..., "score": ..., "text": ...}, ...]
    if s:
        s.set_attribute("gen_ai.input.messages", question)
        s.set_attribute("gen_ai.output.messages", json.dumps({"documents": docs}))
```

Note the payload ceiling: `services/otel.py` truncates a stored field at 8000 characters and
records the cut in `result.meta.truncation`. A renderer sees the stored text, so send the
fields you want rendered, not the whole corpus.

---

## Checklist for a good renderer

- **Decline rather than guess.** Return `null` the moment the payload isn't the shape you
  expect. The default view is a fine outcome; a half-parsed domain view is not.
- **Don't hide the failure state.** If the span failed, say so — the default view renders the
  error block, and yours should too if it replaces it.
- **Stay cheap.** `render` can be called for every expanded row of a large trace.
- **Keep the terminal-dark palette.** Use the CSS variables (`--panel`, `--border`, `--muted`,
  `--blue`, `--red`) rather than literal colours, so light/dark and future themes follow.
- **Never mutate the span.** It is shared with the flow graph, the compare view, and the
  playground.
