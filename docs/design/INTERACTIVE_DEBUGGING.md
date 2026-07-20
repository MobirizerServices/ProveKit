# Design: Interactive Debugging — edit-and-re-run with real data

**Status:** proposal for review · **Author:** (draft) · **Scope:** turn ProveKit's trace view
from a read-only log viewer into an interactive debugger where you edit a captured run's
prompt/variables and re-run it against real data.

---

## 1. Goal & non-goals

**Goal.** From any captured trace, a user can:
- open an LLM call, **edit** its messages / model / params / template variables, and **re-run**
  it with real data, seeing the new output **diffed** against the original;
- (later) re-run the **whole agent flow** from a chosen step, with recorded outputs for the
  un-edited steps and live calls past the edit — framework-agnostic.

**Non-goals (for now).** Owning a runtime (we are not building LangGraph). Training/fine-tuning.
Replaying side-effecting production tools against live systems (see §5.3 — we replay recorded
tool outputs, we do not re-hit customer databases).

---

## 2. Background: how the field does it (competitive scan)

Two distinct things get called "re-run":

- **Pattern A — Prompt playground (single LLM call).** ~9/10 tools (LangSmith, Langfuse, Arize
  Phoenix, Braintrust, Weave, Humanloop, PromptLayer, Helicone, Portkey). Universal and cheap;
  debugs one call in isolation — the agent loop never executes.
- **Pattern B — Whole-agent replay / time-travel.** Essentially **LangGraph-only**, because it
  needs a resumable serialized checkpoint (`get_state_history` → `update_state` → resume, plus
  `interrupt`/`Command(resume)`). Tools that only observe read-only spans structurally cannot do it.

**The gap:** nobody does **framework-agnostic agent replay**. ProveKit already captures the full
nested tree with every call's inputs/outputs, which lets us approximate Pattern B *from the trace*
— the wedge no competitor can reach from read-only spans.

**Table-stakes** (to not be behind): span→playground, edit prompt/model/params, BYO key,
side-by-side compare, versioned prompt save, dataset→experiment.

---

## 3. Phased plan

| Phase | What | Value | Risk |
|------|------|-------|------|
| **1. Prompt Playground** | Edit + re-run a single captured LLM call, diff output | Table-stakes; ProveKit ~80% there | Low |
| **2. Replay Harness** | Re-run the flow from step N; recorded before the edit, live after | The differentiator — no one has it | High (design depth) |
| **3. Polish** | Prompt versions, A/B/C variants, AI-suggested edits, edited-prompt→experiment | Parity + delight | Low |

Ship 1 first (it's the foundation and a standalone win), prove the provider-call + key plumbing,
then build 2 on top.

---

## 4. Phase 1 — Prompt Playground (MVP)

### 4.1 What seeds it (all already captured)
From a selected LLM span (`Run`): `request.model`, `request.provider`, `request.input`
(messages — `parseMessages()` already normalizes these in `TraceDetail.tsx`), and
`result.meta.params` (`temperature` / `top_p` / `max_tokens`). The original `result.text` is the
baseline to diff against. **No new capture work** — this is why Phase 1 is cheap.

### 4.2 Provider connections (BYO key, sealed)
Re-run needs to call a provider, which ProveKit has never done. Add per-project provider keys,
encrypted at rest.

- **New table `provider_connections`**: `id, workspace_id, provider ('openai'|'anthropic'),
  label, key_sealed (text), created_at, last_used_at`.
- **Sealing:** add `seal(plaintext)->str` / `unseal(token)->str` to `services/sealing.py`
  (Fernet is already wired via `SECRET_KEY`). The plaintext key is written once, never returned
  to the client (list responses show only `provider` + a masked suffix, e.g. `sk-…4f2a`).
- **Settings UI:** a "Model connections" card in project settings (mirrors the existing
  `AlertsPanel` pattern) — add key, list, delete.

### 4.3 Backend
```
POST /api/playground/run          # cookie/key auth, workspace-scoped
  body: { provider, model, messages:[{role,content}], params:{temperature,top_p,max_tokens},
          from_span_id? }          # from_span_id links the run back to its origin span
  → { output, usage:{input_tokens,output_tokens}, latency_ms, cost_est, finish_reason }

POST /api/connections   { provider, label, key }      # store (seals server-side)
GET  /api/connections                                  # [{id, provider, label, masked, last_used_at}]
DELETE /api/connections/{id}
```
- **Provider-call layer** `services/llm_client.py` — a thin normalizer over OpenAI + Anthropic
  (async `httpx`, no heavy SDKs; matches the "core is tiny" ethos). Maps our neutral
  `{messages, model, params}` to each provider's shape and back.
- **Guardrails:** per-project rate limit (reuse `services/limits.py`); hard cap on
  `max_tokens`; a monthly playground-spend ceiling with a 402 when exceeded; the sealed key is
  read, used, and never logged (add to redaction denylist).
- **Optional capture:** persist each playground run as a `Run` of a new type `playground`
  (parent = the origin span's trace) so re-runs show up in history and can be compared later.
  Off by default to avoid polluting real traces; toggle per run.

### 4.4 Frontend UX
A third mode on the trace detail, next to **Flow / Waterfall**: **Playground** (enabled when an
LLM span is selected). Or an "Edit & re-run" button in the LLM span inspector that opens it.

```
┌ research-orchestrator › analyze (llm)                          [Flow] [Waterfall] [Playground] ┐
│ MODEL  [ gpt-4o ▼ ]     TEMP [0.7]  TOP_P [1.0]  MAX_TOKENS [512]      connection: openai ▼   │
│ ┌ MESSAGES (editable) ───────────────────┐   ┌ VARIABLES (7) ──────────────────────────────┐ │
│ │ system: You are a research analyst…     │   │ topic        [ pricing        ]              │ │
│ │ user:   Analyze these docs for {{topic}}│   │ doc_count    [ 3              ]              │ │
│ │         {{docs}}                        │   │ …                                            │ │
│ └─────────────────────────────────────────┘   └──────────────────────────────────────────────┘ │
│                                                              [ ▶ Run ]  (⌘↵)                    │
│ ┌ ORIGINAL ───────────────────┐   ┌ NEW ───────────────────────────┐                          │
│ │ The evidence is broadly…     │   │ The evidence is positive, with │  ✎ diff  · 3.1s→2.4s      │
│ │ 800→220 tok · $0.004         │   │ 3 caveats… 780→240 tok · $0.004 │                          │
│ └──────────────────────────────┘   └─────────────────────────────────┘                         │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```
- **Variables** (the "change value online" ask): detect `{{name}}` templates in the messages and
  surface them as fields, Coach-Studio-style; edits re-render the prompt before running. If no
  templates, this panel is hidden and you edit messages directly.
- **Diff**: word-level highlight between original and new output; show token/cost/latency deltas.
- Reuses the existing chat-transcript renderer (`Transcript`) for message display.

### 4.5 Phase-1 acceptance
Open an LLM span → edit a message or a `{{variable}}` → Run → see a real new completion diffed
against the original, with token/cost/latency, using a project-scoped sealed key. Works for any
customer regardless of framework.

---

## 5. Phase 2 — Trace Replay Harness (the differentiator)

### 5.1 Concept
Pick any node in the flow and **“Fork & replay from here.”** For every span **before** the fork
point, ProveKit serves the **recorded** output straight from the trace (zero live calls, zero
cost). At and **after** the fork, it makes **live** calls with your key using your edited
prompt/variables. Result: a new trace **branch** shown beside the original in the graph (a fork
tree, like LangGraph Studio) — the real multi-step flow, re-run with your change, without owning
the runtime or requiring a checkpointer.

### 5.2 Two ways to drive the re-run
- **(a) Reconstructed loop (no customer work).** ProveKit replays the agent loop *from the
  trace’s structure*: it walks the recorded span tree, and past the fork point re-issues the LLM
  call live; tool-call spans are matched by name+args and their **recorded outputs replayed**
  unless the args changed (then flagged as "diverged — needs a live tool"). Best-effort;
  framework-agnostic; the novel bit.
- **(b) Replay webhook (opt-in, exact).** The customer registers a `replay_url`; ProveKit POSTs
  `{trace_id, fork_span_id, overrides:{prompt,vars}}` and the customer’s harness re-runs their
  real agent with those overrides and streams a new trace back. Exact and side-effect-honest,
  but requires ~20 lines of customer glue. Offer both; (a) for instant value, (b) for fidelity.

### 5.3 Hard problems (and how we bound them)
- **Determinism / divergence.** Once a step’s inputs change, downstream recorded outputs may no
  longer apply. Policy: replay recorded outputs only while inputs match the trace **byte-for-byte**;
  the first diverging step switches to **live** and everything after it is live too. Show a clear
  "replayed / live / diverged" badge per node.
- **Side-effecting tools.** Never re-hit a customer’s write APIs. Default: **replay recorded tool
  outputs**; live tool calls only via the opt-in webhook (b), where the customer owns safety.
- **Cost.** Only steps at/after the fork cost money; show an estimate before running.

### 5.4 Data model
- `replay_runs`: `id, workspace_id, origin_trace_id, fork_span_id, overrides (json), mode
  ('reconstructed'|'webhook'), new_trace_id, status, created_at`.
- The new branch is stored as normal `Run` rows under a fresh `trace_id`, tagged
  `meta.replay_of = origin_trace_id` so the UI can render the fork tree and diff branches.

### 5.5 UX
Right-click / node action **“Fork & replay from here”** → the Playground panel opens seeded from
that span → edit → **Replay** → the graph shows the original and the new branch side by side,
each node badged replayed / live / diverged; the inspector diffs any node across branches.

---

## 6. Phase 3 — Polish
- **Prompt versions:** save an edited prompt as a named version (a `prompts` table:
  `workspace_id, name, template, model, params, version, created_at`); "restore to code" copy.
- **Variants:** run 2–4 edited variants at once, columns side-by-side (Phoenix-style A/B/C/D).
- **AI-suggested edits:** given a low feedback score + the trace, propose a prompt edit
  (Braintrust "Loop" analogue).
- **Edited prompt → dataset → experiment:** push an edited prompt into the existing
  datasets/experiments flow to score it against a golden set.

---

## 7. New surface summary

**Backend**
- `services/sealing.py` — add `seal()/unseal()`.
- `services/llm_client.py` — new; normalized OpenAI/Anthropic caller (async httpx).
- `models.py` — `provider_connections`, `replay_runs`, (Phase 3) `prompts`; `Run.type` gains
  `playground`; `meta.replay_of`.
- `routers/playground.py` — `/playground/run`, `/connections` CRUD, (Phase 2) `/replay`.
- Alembic migration for the new tables.
- Optional dep extra `provekit[server]` already has httpx; no new heavy deps.

**Frontend**
- `components/Playground.tsx` — the editable panel + diff.
- `components/ModelConnections.tsx` — settings card (BYO key).
- `TraceDetail.tsx` — third view mode / "Edit & re-run" action on LLM spans.
- `lib/api.ts` — `playgroundRun`, `connections` CRUD, (Phase 2) `replay`.

---

## 8. Security & cost model
- Provider keys **sealed at rest** (Fernet via `SECRET_KEY`), never returned to the browser,
  never logged, added to the redaction denylist. Used only server-side for re-runs.
- Playground/replay calls are **workspace-scoped** and rate-limited; a per-project monthly spend
  cap returns 402 when exceeded; every run records `cost_est`.
- Live tool calls are **off** by default (recorded outputs replayed); only the opt-in webhook
  path can touch customer systems, and that’s the customer’s harness, not ProveKit.

---

## 9. Milestones (rough)
1. **M1 — Connections + provider-call layer** (seal/unseal, `provider_connections`,
   `llm_client.py`, settings UI). Foundation; testable in isolation.
2. **M2 — Prompt Playground** (endpoint + `Playground.tsx` + diff + variables). ← first user-visible win.
3. **M3 — Replay Harness (reconstructed mode)** + fork-tree UI.
4. **M4 — Replay webhook + Phase-3 polish.**

---

## 10. Open questions
1. **Providers at launch:** OpenAI + Anthropic only, or also a generic OpenAI-compatible base-URL
   (covers Azure/OpenRouter/local)? (Recommend: both — the base-URL option is nearly free.)
2. **Key storage:** per-project (proposed) vs per-user? Per-project matches the tenancy model.
3. **Spend cap default** and whether to require it before the first run.
4. **Persist playground runs** as `Run`s by default, or keep them ephemeral until saved?
5. **Phase-2 default mode:** ship reconstructed replay first (no customer work) and add the
   webhook later — agreed?
