"""The two things a ProveKit CI gate needs from your repo: a target and (optionally) a
scorer. Both are plain functions — the action imports them by `module:function`.

Deliberately offline: the "agent" here is a lookup table, so the example workflow runs
against your portal without an LLM key and the gate's behaviour is the only variable. Swap
`answer()` for your real entrypoint and nothing else changes.

    uses: MobirizerServices/ProveKit/.github/actions/provekit-eval@main
    with:
      target: examples/ci/eval_target.py:answer
      scorers: contains,examples/ci/eval_target.py:not_empty
"""
from __future__ import annotations

FACTS = {
    "what is provekit?": "ProveKit is drop-in tracing for AI agents.",
    "how do i install the sdk?": "Run pip install provekit[trace].",
    "which port does the backend use?": "The backend runs on port 8000 in local dev.",
}


def answer(question: str) -> str:
    """Called once per dataset item with that item's `input`; whatever it returns is the
    output that gets scored. Raising is allowed — pk.evaluate records the failure as a
    result instead of aborting the run, so one bad item can't hide the other 99."""
    return FACTS.get(question.strip().lower(), "I don't know.")


def not_empty(output: str, expected: str) -> float:
    """A custom scorer: any `fn(output, expected) -> float` in [0, 1]. Useful next to
    `contains`, which can't tell an empty answer from a wrong one."""
    return 1.0 if (output or "").strip() else 0.0
