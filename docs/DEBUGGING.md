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
  - **DIVERGED** — its input referenced a value that changed (would need a live re-run)
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
- Dataset evaluations are capped to a bounded number of items per run.
- Provider keys are sealed at rest, never logged, and used only server-side.
