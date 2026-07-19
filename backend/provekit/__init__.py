"""ProveKit — drop-in agent tracing. One SDK on the client captures the whole flow.

    import provekit.trace as pk          # the canonical import
    pk.init()                            # or, zero-code: import provekit.auto

    @pk.trace(name="my-agent")           # optional: group one run under a named root
    def run(q): ...

Everything beneath your code — LLM providers, agent frameworks, outbound HTTP — is
captured automatically. `init`, `configure`, and `span` are also re-exported here for
`import provekit as pk` convenience; the `trace` decorator lives on the `provekit.trace`
submodule (a same-named top-level export would shadow that module).
"""
from provekit import scorers
from provekit.eval import evaluate
from provekit.trace import configure, init, span

__all__ = ["init", "configure", "span", "evaluate", "scorers"]
