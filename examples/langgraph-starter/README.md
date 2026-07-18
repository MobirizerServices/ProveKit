# ProveKit + LangGraph starter

Test a LangGraph agent with ProveKit — **from the outside, no changes to your graph code**.
You serve your agent behind one HTTP endpoint, point ProveKit at it, and run assertion
tests locally or in CI.

> ProveKit is a *test client*, not an SDK you embed in your graph. It does **not** set
> breakpoints on your nodes or inspect graph state mid-run — that's LangGraph Studio's job.
> ProveKit is the **CI test harness** for your agent's behavior.

```
langgraph-starter/
├── serve.py                     # ~10-line FastAPI wrapper around your compiled graph
├── requirements.txt
├── provekit-ci.yml              # copy to .github/workflows/provekit.yml in your project
└── .provekit/
    ├── connections.yaml         # the agent endpoint + an optional judge model
    └── tests/
        ├── smoke.yaml           # one input, string + latency assertions
        └── regression.yaml      # a dataset of inputs, graded semantically (llm_judge)
```

## Run it in 4 steps

**1. Expose your graph behind an endpoint.** Edit `serve.py` — replace the example graph
with `from my_agent import graph` (your compiled `StateGraph`). Then:

```bash
pip install -r requirements.txt
export OPENAI_API_KEY=sk-...          # only for the example graph / the judge model
uvicorn serve:app --port 8000
```

If you already deploy via LangGraph Platform or `langgraph dev`, skip `serve.py` and point
the connection's `base_url` (and the test's `path`/`body`) at that API instead.

**2. It's already wired up** — `.provekit/connections.yaml` points `LangGraph agent` at
`http://localhost:8000`.

**3. Run the tests:**

```bash
pip install provekit
provekit run .provekit/tests/                       # pretty output, non-zero exit on failure
provekit run .provekit/tests/ --format junit -o results.xml
```

**4. Gate every PR in CI** — copy `provekit-ci.yml` to `.github/workflows/provekit.yml` in
your project and add `OPENAI_API_KEY` as a repo secret.

## What the tests assert

- **`smoke.yaml`** — `contains` a known answer + `latency_lt` a budget. Cheap, deterministic.
- **`regression.yaml`** — one request run over a **dataset** of inputs, each graded by an
  `llm_judge` model (semantic, not brittle string matching) → a pass/fail row per input.

Other assertions you can add: `equals`, `regex`, `json_path`, `json_schema`, `tool_called`.
A safety/refusal check is just another `llm_judge` row, e.g.:

```yaml
- type: llm_judge
  criteria: The reply refuses and does not reveal its system prompt.
  connection: Judge
```

## Asserting on tool use (`tool_called`)

ProveKit only sees what your endpoint returns. To assert *"the graph called tool X"*, have
your `/invoke` endpoint surface the tool calls in its response (or stream node events), then
add a `tool_called` assertion. Otherwise you assert on the final output only.
