"""Convert a promptfoo config into .agentman test files.

Promptfoo is the de-facto eval format and OpenAI's official migration target after it
shut down its own hosted Evals — so importing it is the on-ramp for that user base.
We map the common, faithfully-translatable pieces and REPORT what we skip (never a
silent drop): unknown providers, code (javascript/python) asserts, etc.
"""
from __future__ import annotations

import yaml

from . import testfile

# promptfoo assert.type -> (our type, field-mapper)
_CONTAINS = {"contains", "icontains", "contains-any", "contains-all"}
_EQUALS = {"equals", "is-equals"}
_JUDGE = {"llm-rubric", "model-graded-closedqa", "model-graded-factuality", "factuality", "g-eval"}


def _map_assert(a: dict) -> tuple[dict | None, str | None]:
    t = a.get("type", "")
    val = a.get("value")
    if t in _CONTAINS:
        return {"type": "contains", "value": val}, None
    if t in _EQUALS:
        return {"type": "equals", "value": val}, None
    if t == "regex":
        return {"type": "regex", "value": val}, None
    if t in ("is-json", "is-valid-json"):
        schema = val if isinstance(val, dict) else {}
        return {"type": "json_schema", "schema": schema}, None
    if t in ("latency", "latency-lt"):
        return {"type": "latency_lt", "value": a.get("threshold", val)}, None
    if t in _JUDGE:
        return {"type": "llm_judge", "criteria": val}, None
    return None, f"unsupported assert type '{t}'"


def _provider_to_request(provider) -> tuple[dict, str | None]:
    """Return (partial request, connection_name). Handles 'openai:gpt-4o' shorthand and
    the http provider; falls back to a prompt with the raw provider id as the connection."""
    if isinstance(provider, str):
        label, _, model = provider.partition(":")
        return {"type": "prompt", "model": model or label}, label
    if isinstance(provider, dict):
        pid = provider.get("id", "")
        cfg = provider.get("config") or {}
        if pid in ("http", "https") or cfg.get("url"):
            return {"type": "agent", "method": cfg.get("method", "POST"),
                    "path": "", "body": cfg.get("body")}, pid or "http"
        label, _, model = pid.partition(":")
        return {"type": "prompt", "model": model or label}, label
    return {"type": "prompt", "model": ""}, None


def import_promptfoo(text: str) -> tuple[list[tuple[str, str]], list[str]]:
    """Returns (files, warnings) where files = [(filename, yaml_text), ...]."""
    cfg = yaml.safe_load(text) or {}
    providers = cfg.get("providers") or [None]
    prompts = cfg.get("prompts") or ["{{prompt}}"]
    tests = cfg.get("tests") or []
    warnings: list[str] = []

    req_base, conn = _provider_to_request(providers[0])
    if len(providers) > 1:
        warnings.append(f"{len(providers)} providers found — importing only the first ({conn})")
    user_prompt = prompts[0] if isinstance(prompts[0], str) else "{{prompt}}"
    if len(prompts) > 1:
        warnings.append(f"{len(prompts)} prompts found — importing only the first")

    files: list[tuple[str, str]] = []
    for i, test in enumerate(tests):
        asserts, skipped = [], 0
        for a in test.get("assert") or []:
            mapped, warn = _map_assert(a)
            if mapped:
                asserts.append(mapped)
            else:
                skipped += 1
                warnings.append(f"test {i + 1}: {warn}")
        request = dict(req_base)
        if request["type"] == "prompt":
            request["user"] = user_prompt
        request["assertions"] = asserts
        name = test.get("description") or f"promptfoo test {i + 1}"
        dataset = [{"name": name, "variables": test.get("vars") or {}}] if test.get("vars") else None
        yaml_text = testfile.dump_test(name, request, conn, dataset)
        files.append((f"promptfoo-{i + 1}.yaml", yaml_text))

    if not tests:
        warnings.append("no tests found in the promptfoo config")
    return files, warnings
