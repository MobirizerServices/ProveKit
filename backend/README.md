# ProveKit

**One decorator. The whole agent flow.** Add one `@pk.trace` at your agent's entrypoint and
review every run — the model calls, tools, and steps — as a nested flow in your ProveKit
portal. OpenAI/Anthropic calls capture themselves. Open source, self-hostable, no framework
lock-in.

## Install

```bash
pip install "provekit[trace]"
```

## Use

```python
import provekit.trace as pk

# .env
#   PROVEKIT_API_KEY=pk_...        (create a project + key in the portal)
#   PROVEKIT_ENDPOINT=https://your-provekit-host

@pk.trace(name="support-agent")
def run_agent(question: str) -> str:
    docs = retrieve(question)          # wrap sub-steps with `with pk.span("retrieve"):`
    return chat(question, docs)        # the OpenAI/Anthropic call captures itself
```

Run your agent, open **Traces** in the portal, and every run shows up as a nested waterfall
with per-span input, output, and token usage.

It's OpenTelemetry under the hood, so your data is portable and nothing is locked in — but
you never have to touch OTel. Fail-open by design: if the key/endpoint are unset or the
portal is unreachable, your app runs completely unaffected.

## Run the portal (self-host)

The web app + ingest server ship in the same package:

```bash
pip install "provekit[server]"
uvicorn provekit.main:app --port 8100
```

See the [repo](https://github.com/MobirizerServices/ProveKit) for Docker/compose and the
full [tracing guide](https://github.com/MobirizerServices/ProveKit/blob/main/docs/TRACING.md).

- Repository: https://github.com/MobirizerServices/ProveKit
- License: MIT
