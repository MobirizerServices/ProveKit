"""Assertions / evals — check a run's result against a list of assertions. Types:
contains · equals · regex · json_path · json_schema · tool_called · latency_lt · llm_judge.
Mirrors the eval assertions in tools like Reticle/LangSmith."""
from __future__ import annotations

import json
import re

from jsonschema import ValidationError
from jsonschema import validate as js_validate

from ..models import Connection
from .providers import llm

# re.search holds the GIL, so a catastrophic-backtracking pattern (ReDoS) would freeze the
# whole process — and a worker thread can't preempt it. Since stdlib re has no timeout, we
# reject the common nested-quantifier signature and cap the searched text instead. This is a
# heuristic guard; an interruptible engine (the `regex` module's timeout, or RE2) is the
# complete fix if fully-untrusted patterns ever need to run.
_MAX_REGEX_INPUT = 100_000
_NESTED_QUANT = re.compile(r"\([^()]*[*+][^()]*\)\s*[*+{]")


def _regex_search(pattern: str, text: str):
    if len(pattern) > 2000:
        raise ValueError("regex pattern too long")
    if _NESTED_QUANT.search(pattern):
        raise ValueError("regex rejected: nested quantifier (possible ReDoS)")
    return re.search(pattern, text[:_MAX_REGEX_INPUT])


def _text_of(result: dict) -> str:
    if result.get("text"):
        return result["text"]
    out = result.get("output")
    if isinstance(out, str):
        return out
    return json.dumps(out) if out is not None else ""


def get_path(obj, path: str):
    cur = obj
    for part in str(path).split("."):
        if part == "":
            continue
        if isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return None
        elif isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def _llm_judge(db, a: dict, text: str, workspace_id=None):
    conn = db.get(Connection, a.get("connection_id")) if a.get("connection_id") else None
    if conn and workspace_id is not None and conn.workspace_id != workspace_id:
        conn = None  # tenancy: don't judge with another workspace's connection
    if not conn:
        return False, "no judge connection configured"
    cfg = conn.config or {}
    model = a.get("model") or (cfg.get("models") or ["gpt-4o-mini"])[0]
    system = ("You are a strict evaluator. Given CRITERIA and OUTPUT, decide if the output "
              "satisfies the criteria. Reply with exactly PASS or FAIL on the first line, "
              "then a one-sentence reason.")
    user = f"CRITERIA:\n{a.get('criteria', '')}\n\nOUTPUT:\n{text[:4000]}"
    # Sync bridge (asyncio.run): evaluate() runs in a worker thread from async endpoints
    # and directly in the CLI — both have no running loop, so this is safe.
    reply = llm.collect_text_sync(provider=cfg.get("provider", "openai"), base_url=cfg.get("base_url", ""),
                                  api_key=cfg.get("api_key", ""), model=model, system=system,
                                  messages=[{"role": "user", "content": user}], temperature=0, max_tokens=200).strip()
    return reply.upper().startswith("PASS"), reply[:160]


def evaluate(db, assertions: list, run: dict, workspace_id=None) -> list[dict]:
    """run = {result:{text,output,meta}, status, duration_ms, events}."""
    result = run.get("result", {}) or {}
    text = _text_of(result)
    output = result.get("output")
    meta = result.get("meta", {}) or {}
    dur = run.get("duration_ms", 0)
    events = run.get("events") or result.get("events") or []
    out = []
    for a in assertions or []:
        t = a.get("type")
        ok, detail = False, ""
        try:
            if t == "contains":
                ok = str(a.get("value", "")) in text
                detail = f"output {'contains' if ok else 'missing'} “{a.get('value')}”"
            elif t == "equals":
                target = get_path(output, a["path"]) if a.get("path") else text
                ok = str(target) == str(a.get("value"))
                detail = f"{target!r} {'==' if ok else '!='} {a.get('value')!r}"
            elif t == "regex":
                ok = _regex_search(a.get("value", ""), text) is not None
                detail = f"/{a.get('value')}/ {'matched' if ok else 'no match'}"
            elif t == "json_path":
                val = get_path(output, a.get("path", ""))
                if a.get("value", "") != "":
                    ok = str(val) == str(a["value"]); detail = f"{a.get('path')} = {val!r}"
                else:
                    ok = val is not None; detail = f"{a.get('path')} {'exists' if ok else 'missing'} (={val!r})"
            elif t == "json_schema":
                schema = a.get("schema") if isinstance(a.get("schema"), dict) else json.loads(a.get("schema") or "{}")
                try:
                    js_validate(output, schema); ok = True; detail = "matches schema"
                except ValidationError as ve:
                    ok = False; detail = str(ve.message)[:140]
            elif t == "tool_called":
                # Match structured fields only — substring-matching the raw event JSON
                # passed whenever the name appeared anywhere (e.g. inside prompt text).
                name = a.get("value", "")
                called = {meta.get("tool")}
                for e in events:
                    if isinstance(e, dict):
                        called.update(str(e[k]) for k in ("tool", "tool_name", "name") if e.get(k))
                        for tc in e.get("tool_calls") or []:
                            if isinstance(tc, dict):
                                called.add(str(tc.get("name") or (tc.get("function") or {}).get("name")))
                ok = name in {c for c in called if c}
                detail = f"tool '{name}' {'called' if ok else 'not called'}"
            elif t == "latency_lt":
                ok = dur < float(a.get("value", 0)); detail = f"{dur}ms {'<' if ok else '≥'} {a.get('value')}ms"
            elif t == "llm_judge":
                ok, detail = _llm_judge(db, a, text, workspace_id)
            else:
                detail = f"unknown assertion type: {t}"
        except Exception as exc:
            ok, detail = False, f"error: {exc}"[:140]
        out.append({"type": t, "name": a.get("name") or t, "ok": ok, "detail": detail})
    return out
