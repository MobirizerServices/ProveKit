# Interactive debugging

ProveKit isn't just a log viewer — you can open any captured run, **edit the prompt or variables
with real data, and re-run it**, then compare outputs, replay the whole flow, or score an edit
against a dataset.

This guide covers the four things you can do. For the design/architecture, see
[design/INTERACTIVE_DEBUGGING.md](design/INTERACTIVE_DEBUGGING.md).

---

## 1. Add a model connection (one-time)

Re-running a call means calling a provider, so add a key first — **Settings → Model connections**:

- **OpenAI** / **Anthropic** — paste an API key.
- **OpenAI-compatible** — a key plus a base URL (Azure, OpenRouter, a local server, …).
- **Mock (no key)** — a keyless offline model that echoes the prompt. Great for trying the
  playground before wiring a real key.

Keys are stored **encrypted** and never returned to the browser — only a masked hint (`…a1b2`) is
shown. You can add several per project (e.g. prod vs staging).

---

## 2. Prompt playground — edit & re-run one call

On a trace, click an **LLM** node, then **▶ Edit & re-run**. The playground opens seeded from the
captured call:

- Edit the **messages**, **model**, **temperature**, **max tokens**.
- Any **`{{variable}}`** in the prompt becomes an editable field.
- Pick a **connection** (or Mock) and press **▶ Run**.

The **new output is diffed against the original**, with token counts, estimated cost, and latency.
Each run is kept as a column, so you can tweak and **A/B** successive edits.

- **💾 Save version** stores the edited prompt under a name (auto-versioned); **Load version…**
  restores it later.

---

## 3. Replay flow — re-run the whole trace from a step

**⑂ Replay flow** forks the entire trace at the selected span and produces a **new branch** you can
compare against the original. Two modes:

- **Reconstructed** (default, works for any framework) — re-runs the forked call live with your
  edit, then **threads its new output into downstream calls that consumed it**, re-running those
  live too. Steps before the fork are copied as-is; unrelated steps replay their recorded output.
  Every node in the branch is badged:
  - **LIVE** — re-executed with your edit
  - **SAME** — unchanged (before the fork)
  - **RECORDED** — replayed from the original (nothing upstream changed for it)
  - **DIVERGED** — its input referenced a value that changed, so its recorded output is no
    longer evidence of anything. Divergence **propagates**: any span reading a diverged span's
    output is diverged too, and a diverged LLM call is *not* re-run, because answering from
    inputs that no longer hold would spend your budget to produce a confidently wrong result.

A replay containing any diverged span is a **hypothesis, not a reproduction** — the response
carries `reliable: false` with a `fidelity` breakdown, and the trace view says so at the top.
ProveKit cannot re-run your tools (it doesn't own them); **webhook** mode is the exact re-run.
- **Webhook** (exact) — ProveKit POSTs the fork override to your project's **replay endpoint** and
  ingests the real re-run your agent returns. Set the URL in **Settings → Replay webhook**.

### Webhook contract
ProveKit sends:
```json
POST <your replay_url>
{ "origin_trace_id": "…", "fork_span_id": "…",
  "overrides": { "model": "…", "messages": [ { "role": "user", "content": "…" } ], "params": { … } } }
```
Your endpoint re-runs your agent with those overrides and returns an **OTLP
ExportTraceServiceRequest** (the same shape the SDK exports) — ProveKit ingests it as the new
branch. Internal/private URLs are refused in hosted mode (SSRF protection); use a reachable host.

---

## 4. Evaluate an edit over a dataset

In the playground, use **🧪 Run over dataset**: pick a dataset and ProveKit runs your edited prompt
over every item (substituting `{{input}}` / `{{expected}}` per item), scores the output against the
expected value with the built-in scorers (`exact_match`, `contains`), and saves a real
**experiment** you can open from the Datasets page. This turns a promising prompt edit into a
measured regression check in one click.

---

## Guardrails

- Re-runs are **rate-limited** per project and capped at a hard max-tokens ceiling.
- A per-project **monthly spend cap** (`PLAYGROUND_MONTHLY_USD_CAP`, default $25; 0 disables) —
  playground/reconstructed-replay/eval calls estimate their cost and a 402 is returned once the
  month's total is reached. (Webhook replays run on your own infra with your keys, so they don't
  count toward this.)
- Dataset evaluations are capped to a bounded number of items per run.
- Provider keys are sealed at rest, never logged, and used only server-side.

---

## Rejections and what to do about them

Every rejection ProveKit returns is meant to name the **fix**, not just the failure — the text in
`detail` should be enough to act on without reading the source. The wording lives in one module
(`backend/provekit/services/errors.py`) so the same cause always reads the same way, and so a
message can carry a link back to this page.

| Status | You'll see | What to do |
|---|---|---|
| **422** | *"This run has no model to call…"* | Pass `connection_id` from `GET /api/connections`, or `provider: "mock"` to use the keyless offline model. |
| **422** | *"A provider API key is required for 'openai'…"* | ProveKit calls providers with **your** credentials and ships none of its own. Add the key under **Settings → Model connections**, or use Mock. |
| **422** | *"An OpenAI-compatible connection needs base_url…"* | Give the API **root** (`https://openrouter.ai/api/v1`, `http://localhost:11434/v1`). ProveKit appends `/chat/completions` itself — including it is the usual mistake. |
| **404** | *"No model connection with that id in the current project…"* | Connections are per project. Check `GET /api/connections` and the `X-Project-Id` header; a connection from another project is reported as **missing**, not forbidden, so ids can't be probed across tenants. The same rule applies to saved prompts, API keys and alerts. |
| **422** | *"A replay can edit at most 8 spans at once…"* | Each `llm` edit is a live provider call, so one request is capped. Drop the edits that don't affect the output you're testing. |
| **422** | *"Span … appears in two edits…"* | Two edits of one span have no defined order, so one would be dropped silently. Merge them into a single edit. |
| **422** | *"edit kind must be 'llm' … or 'tool' …"* | `llm` replaces the prompt and re-runs the call; `tool` replaces recorded tool **arguments** only — ProveKit never executes your tools. |
| **404** | *"Replay failed: origin trace not found…"* / *"fork span not in trace"* | Take `origin_trace_id` and `fork_span_id` from `GET /api/traces/{trace_id}`; a replay can only fork a span belonging to the trace it names. |
| **404** | *"no replay webhook configured for this project"* | Set the URL under **Settings → Replay webhook**, or use `mode: "reconstructed"`. |
| **502** | *"The model provider rejected this call: …"* | The provider's own words are kept verbatim. Check the model name and the connection's key; retry if it's a rate limit or an outage. |
| **429** | *"Too many playground runs — wait a minute."* | The per-project burst limit on live re-runs. `Retry-After` says how long. |
| **402** | *"Monthly playground spend cap of $… reached for this project."* | Raise or disable `PLAYGROUND_MONTHLY_USD_CAP` (0 = off), or wait for the calendar month to roll over. Webhook replays run on your own infra and don't count. |
