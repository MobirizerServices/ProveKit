"""Scorers — pure functions that grade an output against an expected value, returning a
float in [0, 1]. Deliberately dependency-free so the SAME module runs in the evaluation
SDK (client-side, in pk.evaluate) and on the server. Pass scorers to pk.evaluate() by name
(e.g. "exact_match") or as your own `fn(output, expected) -> float`.

Beyond the text scorers, three families grade things a final string can't express — the path
an agent took, whether an answer is grounded in what was retrieved, and what the run cost.
They all keep the same `fn(output, expected) -> float` signature, so they resolve through the
same registry; what changes is that `output` may be a JSON payload rather than prose:

    {"answer": "...", "question": "...", "context": ["chunk", ...],
     "spans": [ ...the trace's spans... ], "cost_usd": 0.004, "latency_ms": 1830}

Every key is optional, `pk.evaluate` already json-dumps a non-string target result, and the
list `GET /api/traces/{trace_id}` returns is accepted as the payload directly. A scorer that
finds nothing it can grade returns None and is *omitted* from the result rather than scored
0.0 — see run_scorers.
"""
from __future__ import annotations

import json
import re
from datetime import datetime


def exact_match(output: str, expected: str) -> float:
    """1.0 if output equals expected (trimmed), else 0.0."""
    return 1.0 if (output or "").strip() == (expected or "").strip() else 0.0


def contains(output: str, expected: str) -> float:
    """1.0 if expected appears in output (case-insensitive), else 0.0."""
    return 1.0 if expected and expected.lower() in (output or "").lower() else 0.0


def regex_match(output: str, expected: str) -> float:
    """1.0 if the expected regex matches output, else 0.0. (expected is the pattern.)"""
    try:
        return 1.0 if expected and re.search(expected, output or "") else 0.0
    except re.error:
        return 0.0


def json_valid(output: str, expected: str = "") -> float:
    """1.0 if output parses as JSON, else 0.0 (expected is ignored)."""
    try:
        json.loads(output)
        return 1.0
    except (ValueError, TypeError):
        return 0.0


# ------------------------------------------------------------------ payload plumbing

def _dict(v) -> dict:
    return v if isinstance(v, dict) else {}


def _payload(output):
    """The structured value behind an output, or None when there isn't one.

    Scorers are handed a string (pk.evaluate json-dumps anything else), so a structured
    payload arrives as JSON text. A dict/list is accepted as-is too, so a caller already
    holding a trace can score it without a round trip through json."""
    if isinstance(output, (dict, list)):
        return output
    if not isinstance(output, str):
        return None
    try:
        v = json.loads(output)
    except (ValueError, TypeError):
        return None
    return v if isinstance(v, (dict, list)) else None


#: Payload keys that may carry the captured spans, most explicit first.
_SPAN_KEYS = ("spans", "trajectory", "trace", "steps")


def _spans(output) -> list[dict]:
    """The raw (unordered) spans in an output payload. A bare list is taken to be the span
    list itself — that is exactly what `GET /api/traces/{trace_id}` returns."""
    p = _payload(output)
    raw = p if isinstance(p, list) else None
    if raw is None:
        for k in _SPAN_KEYS:
            v = _dict(p).get(k)
            if isinstance(v, list):
                raw = v
                break
    return [s for s in (raw or []) if isinstance(s, dict)]


def _meta(span: dict) -> dict:
    return _dict(_dict(span.get("result")).get("meta"))


def _epoch(v) -> float | None:
    """A sortable start time from an epoch number (any unit) or an ISO-8601 string; None when
    `v` isn't a time. Units are deliberately not normalised: only the relative order inside
    one trace matters, and one trace's spans all come from one capture path."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if not isinstance(v, str) or not v.strip():
        return None
    s = v.strip()
    try:
        return float(s)                      # start_ns is stored as a string (services/otel.py)
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _start_key(span: dict, index: int) -> tuple:
    """Sort key for one span: its start time, falling back to arrival position. Spans that
    carry no time at all sort after those that do (leading `1`), so one timeless span can't
    jump to the front of a trace that is otherwise properly ordered."""
    for v in (span.get("start_ns"), _meta(span).get("start_ns"), span.get("startTimeUnixNano"),
              span.get("started_at"), span.get("created_at"), span.get("timestamp")):
        t = _epoch(v)
        if t is not None:
            return (0, t, index)
    return (1, 0.0, index)


def _span_id(span: dict) -> str:
    return str(span.get("span_id") or span.get("spanId") or "")


def _parent_id(span: dict) -> str:
    return str(span.get("parent_span_id") or span.get("parentSpanId") or "")


def trajectory(output) -> list[dict]:
    """*The* trajectory a trajectory scorer grades: a pre-order walk of the span tree with
    siblings in start order — the same top-to-bottom reading as the portal's waterfall.

    Two properties of real captures decide this definition (roadmap #3/#4). Spans arrive out
    of order, so ordering is by start time and never by position in the array. And the root
    may never arrive, so any span whose parent is absent from the set is *promoted* to a root
    instead of being dropped — that is what keeps a partial tree scoreable."""
    spans = _spans(output)
    if not spans:
        return []
    first_index: dict[str, int] = {}
    for i, s in enumerate(spans):
        sid = _span_id(s)
        if sid and sid not in first_index:
            first_index[sid] = i
    roots: list[int] = []
    children: dict[int, list[int]] = {}
    for i, s in enumerate(spans):
        parent = first_index.get(_parent_id(s))
        if parent is None or parent == i:
            roots.append(i)
        else:
            children.setdefault(parent, []).append(i)

    def key(i: int) -> tuple:
        return _start_key(spans[i], i)

    out: list[dict] = []
    seen: set[int] = set()
    stack = sorted(roots, key=key, reverse=True)
    while stack:
        i = stack.pop()
        seen.add(i)
        out.append(spans[i])
        stack.extend(sorted(children.get(i, []), key=key, reverse=True))
    # Spans a malformed parent cycle made unreachable from any root still belong to the run,
    # so they follow in start order rather than disappearing.
    out.extend(spans[i] for i in sorted(set(range(len(spans))) - seen, key=key))
    return out


# ------------------------------------------------------------------ trajectory scorers

def _tool_name(span: dict) -> str:
    """The tool this span called, or "" if it isn't a tool call. Prefers the captured
    gen_ai.tool.name (services/otel.py parks it at result.meta.tool) and accepts a plain
    {"tool": ...} so a hand-written trajectory works without faking OTel shapes."""
    for v in (_meta(span).get("tool"), span.get("tool"), span.get("tool_name")):
        if isinstance(v, str) and v.strip():
            return v.strip()
    if str(span.get("type") or "").lower() == "tool":
        # A tool span whose name wasn't on the attributes: the label is what the portal shows.
        return str(span.get("label") or span.get("name") or "").strip()
    return ""


def _tool_args(span: dict) -> str:
    """A normalised form of a call's arguments, for spotting a repeat. JSON with sorted keys,
    so {"a":1,"b":2} and {"b":2,"a":1} are one call and not two."""
    for v in (span.get("args"), span.get("input"), _dict(span.get("request")).get("input")):
        if v is None or v == "":
            continue
        if isinstance(v, str):
            try:
                v = json.loads(v)            # request.input is stored as text (services/otel.py)
            except (ValueError, TypeError):
                return " ".join(v.split())
        try:
            return json.dumps(v, sort_keys=True, default=str)
        except (TypeError, ValueError):
            return str(v)
    return ""


def _tool_calls(output) -> list[tuple[str, str]]:
    """(tool, normalised args) for each tool call, in trajectory order."""
    return [(_tool_name(s), _tool_args(s)) for s in trajectory(output) if _tool_name(s)]


def _config(expected) -> dict:
    """Per-scorer configuration, when `expected` is a JSON object.

    run_scorers hands *every* scorer the same `expected`, so a bare "12" can only configure
    one of them — and these scorers are meant to run together. A JSON object therefore carries
    a key per scorer ({"tools": [...], "max_steps": 12, "max_cost_usd": 0.02}) and each picks
    out its own; a bare string still works when only one of them is in play."""
    v = _payload(expected)
    return v if isinstance(v, dict) else {}


def _name_list(expected, *keys) -> list[str]:
    """Tool names from `expected`: a config object's first present key, a JSON array, or a
    comma-separated string."""
    v = _payload(expected)
    if isinstance(v, dict):
        v = next((v[k] for k in keys if v.get(k)), None)
    if isinstance(v, str):
        return [p.strip() for p in v.split(",") if p.strip()]
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    if v is not None:            # a JSON scalar that isn't a tool list configures nothing
        return []
    return [p.strip() for p in str(expected or "").split(",") if p.strip()]


def _budget(expected, *keys) -> float | None:
    """A numeric ceiling from a config object's first present key, or from `expected` itself."""
    cfg = _config(expected)
    if cfg:
        return next((n for n in (_number(cfg.get(k)) for k in keys) if n is not None), None)
    return _number(expected)


def _number(value) -> float | None:
    """A float from a number or a numeric string, else None. Booleans are rejected on purpose:
    bool is an int in Python, so a JSON `true` would otherwise read as a budget of 1."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def expected_tools_used(output, expected) -> float | None:
    """Share of the tools named in `expected` that the trajectory actually called — 1.0 when
    all of them were. `expected` is "search,summarize", a JSON array, or a config object's
    "tools" (see _config). Order and extra tools
    are ignored here (tool_order and step_budget grade those). None when the output carries
    no trajectory at all."""
    want = _name_list(expected, "tools", "expected_tools_used")
    if not want:
        return 0.0
    if not _spans(output):
        return None
    used = {n.lower() for n, _ in _tool_calls(output)}
    return sum(1.0 for w in want if w.lower() in used) / len(want)


#: Both sequences are truncated to this before the O(n·m) order comparison. A trajectory long
#: enough to hit it has already failed any sane step budget.
_MAX_SEQ = 500


def _lcs(a: list[str], b: list[str]) -> int:
    """Length of the longest common subsequence — how much of `a` appears in `b`, in order."""
    a, b = a[:_MAX_SEQ], b[:_MAX_SEQ]
    prev = [0] * (len(b) + 1)
    for x in a:
        cur = [0]
        for j, y in enumerate(b):
            cur.append(prev[j] + 1 if x == y else max(cur[j], prev[j + 1]))
        prev = cur
    return prev[-1]


def tool_order(output, expected) -> float | None:
    """How much of the expected tool *order* the run followed: the longest subsequence of
    the expected list that appears in order among the calls actually made, over its length —
    from `expected`'s "tool_order", else its "tools", else `expected` itself. 1.0
    exactly when every expected tool was called in the expected order. Unrelated calls in
    between cost nothing — a detour is a budget question, not an ordering one. None when the
    output carries no trajectory."""
    want = [w.lower() for w in _name_list(expected, "tool_order", "tools")]
    if not want:
        return 0.0
    if not _spans(output):
        return None
    got = [n.lower() for n, _ in _tool_calls(output)]
    return _lcs(want, got) / len(want)


def no_repeat(output, expected: str = "") -> float | None:
    """Loop detector: 1.0 when no tool was called twice with the *same* arguments, degrading
    to unique/total (five identical calls in a row → 0.2). Same tool with different arguments
    is normal work, not a loop, and scores clean. `expected` is ignored. A trajectory with no
    tool calls scores 1.0 — nothing looped. None when there's no trajectory."""
    if not _spans(output):
        return None
    calls = _tool_calls(output)
    if not calls:
        return 1.0
    return len(set(calls)) / len(calls)


def step_budget(output, expected) -> float | None:
    """Did the run stay inside a step budget? The maximum comes from `expected`'s "max_steps"
    or from `expected` itself ("12"). 1.0 at or under it, then budget/steps — twice the budget scores 0.5. A step is
    any span in the trajectory that isn't an `agent` wrapper: the LLM calls, tool calls and
    explicit steps the agent actually took, nested ones included. None when there's no
    trajectory; 0.0 when `expected` isn't a positive number, as with the other scorers whose
    configuration is unusable."""
    budget = _budget(expected, "max_steps", "step_budget")
    if budget is None or budget <= 0:
        return 0.0
    spans = trajectory(output)
    if not spans:
        return None
    steps = sum(1 for s in spans if str(s.get("type") or "").lower() != "agent")
    return 1.0 if steps <= budget else budget / steps


# ------------------------------------------------------------------ RAG scorers
#
# Faithfulness / context relevance / answer relevance are model-graded questions. This module
# is client-side and must never import a server module (AGENTS.md), so it builds no provider
# client of its own: a host that HAS one installs it with set_judge(), and without one the
# scorers fall back to the lexical estimate documented on each. That is the degrade — a
# missing API key costs precision, it does not fail the eval run.

_judge = None


def set_judge(fn) -> None:
    """Install the model-graded backend for the RAG scorers: `fn(prompt) -> float in [0,1]`,
    or None when it can't grade (no key, provider error). The portal's equivalent client is
    services/llm_client.judge. Pass None to remove it and go back to the lexical estimate."""
    global _judge
    _judge = fn


def _ask(prompt: str) -> float | None:
    """Grade with the installed judge, or None if there isn't one / it couldn't grade. A
    judge that raises must never fail an eval run, so everything is swallowed."""
    if _judge is None:
        return None
    try:
        v = _judge(prompt)
    except Exception:
        return None
    n = _number(v)
    return None if n is None else max(0.0, min(1.0, n))


_WORD = re.compile(r"[a-z0-9]+")
#: Function words carry no evidence, so they'd inflate every overlap toward 1.0.
_STOP = frozenset("""a an and are as at be but by for from had has have how in into is it its
of on or that the their there this to was were what when where which who why will with you
your""".split())
_SENTENCE = re.compile(r"[^.!?\n]+")
#: Share of a claim's content words that must appear in the evidence to count as supported.
#: Tuned to be generous — the lexical estimate should flag an invented sentence, not punish a
#: paraphrase of a real one.
_SUPPORT = 0.6


def _words(text: str) -> set[str]:
    return {w for w in _WORD.findall(str(text or "").lower()) if len(w) > 1 and w not in _STOP}


def _covered(claim: str, evidence: set[str]) -> float:
    """Share of the claim's content words present in the evidence; 1.0 for an empty claim."""
    cw = _words(claim)
    return 1.0 if not cw else len(cw & evidence) / len(cw)


def _flatten(v) -> list[str]:
    """Retrieved chunks as text. A chunk may be a string, or a dict from a vector store —
    take its text-ish field rather than json-dumping the metadata into the comparison."""
    if v is None or v == "":
        return []
    if isinstance(v, str):
        return [v]
    if isinstance(v, dict):
        for k in ("text", "content", "page_content", "chunk", "document", "body"):
            if isinstance(v.get(k), str) and v[k].strip():
                return [v[k]]
        return [json.dumps(v, default=str)]
    if isinstance(v, list):
        return [c for item in v for c in _flatten(item)]
    return [str(v)]


#: A tool span whose name mentions one of these is treated as the retrieval step.
_RETRIEVAL = ("retriev", "search", "lookup", "vector", "index", "query", "rag", "embed")


def _contexts(output) -> list[str]:
    """The retrieved chunks to grade against. Explicit payload keys first; failing that, the
    output text of the trajectory's retrieval spans — which is where a captured RAG agent's
    chunks actually live, so a plain trace can be scored with no extra plumbing."""
    p = _dict(_payload(output))
    for k in ("context", "contexts", "retrieved", "retrieved_context", "documents", "chunks"):
        chunks = [c for c in _flatten(p.get(k)) if c.strip()]
        if chunks:
            return chunks
    out = []
    for s in trajectory(output):
        name = _tool_name(s).lower()
        if name and any(t in name for t in _RETRIEVAL):
            text = _dict(s.get("result")).get("text") or s.get("output")
            out.extend(c for c in _flatten(text) if c.strip())
    return out


def _root(output) -> dict:
    """The span the run's own input and output hang off — the first root in trajectory order,
    which for a trace whose real root never arrived is the earliest promoted orphan."""
    spans = trajectory(output)
    return spans[0] if spans else {}


def _answer(output) -> str:
    """The answer under test: an explicit payload key, else the root span's captured output.
    There is no plain-prose case — every RAG scorer bails before this when the output carries
    neither retrieved context nor a question, both of which need a payload."""
    for k in ("answer", "output", "response", "completion", "text"):
        v = _dict(_payload(output)).get(k)
        if isinstance(v, str) and v.strip():
            return v
    return str(_dict(_root(output).get("result")).get("text") or "")


def _question(output) -> str:
    """The question asked: an explicit payload key, else the root span's captured input."""
    p = _dict(_payload(output))
    for k in ("question", "query", "input", "prompt"):
        v = p.get(k)
        if isinstance(v, str) and v.strip():
            return v
    return str(_dict(_root(output).get("request")).get("input") or "")


def faithfulness(output, expected: str = "") -> float | None:
    """Is the answer supported by the retrieved context? Share of the answer's sentences that
    the context supports. With a judge installed the model grades it; otherwise the estimate
    is lexical — a sentence counts as supported when ≥60% of its content words appear in the
    context, which catches an invented sentence among grounded ones. `expected` is ignored.
    None when the payload carries no retrieved context: unanswerable, not a failure."""
    ctx, ans = _contexts(output), _answer(output)
    if not ctx:
        return None
    if not ans.strip():
        return 0.0
    graded = _ask("Does the ANSWER stay strictly within the CONTEXT? Reply with only a number "
                  f"from 0.0 (unsupported) to 1.0 (fully supported).\n\nCONTEXT:\n"
                  f"{chr(10).join(ctx)}\n\nANSWER:\n{ans}")
    if graded is not None:
        return graded
    evidence = _words(" ".join(ctx))
    claims = [c for c in (s.strip() for s in _SENTENCE.findall(ans)) if _words(c)]
    if not claims:
        return 1.0                      # nothing assertable ("Yes.") can't be unfaithful
    return sum(1.0 for c in claims if _covered(c, evidence) >= _SUPPORT) / len(claims)


def context_relevance(output, expected: str = "") -> float | None:
    """Was the retrieval any good? Share of retrieved chunks that are relevant to the
    question. With a judge installed the model grades it; otherwise a chunk counts as
    relevant when ≥60% of the question's content words appear in it. `expected` is ignored.
    None without both a question and retrieved context."""
    ctx, q = _contexts(output), _question(output)
    if not ctx or not _words(q):
        return None
    graded = _ask("What share of the CONTEXT passages are relevant to the QUESTION? Reply with "
                  f"only a number from 0.0 to 1.0.\n\nQUESTION:\n{q}\n\nCONTEXT:\n"
                  f"{chr(10).join(ctx)}")
    if graded is not None:
        return graded
    return sum(1.0 for c in ctx if _covered(q, _words(c)) >= _SUPPORT) / len(ctx)


def answer_relevance(output, expected: str = "") -> float | None:
    """Did the answer address the question that was asked (regardless of whether it's right —
    exact_match and llm_judge grade correctness)? With a judge installed the model grades it;
    otherwise it's the share of the question's content words the answer picks up. `expected`
    is ignored. None when the payload carries no question."""
    q, ans = _question(output), _answer(output)
    if not _words(q):
        return None
    if not ans.strip():
        return 0.0
    graded = _ask("Does the ANSWER address the QUESTION? Reply with only a number from 0.0 "
                  f"(off topic) to 1.0 (directly answers).\n\nQUESTION:\n{q}\n\nANSWER:\n{ans}")
    return graded if graded is not None else _covered(q, _words(ans))


# ------------------------------------------------------------------ cost & latency axes
#
# Quality alone can't decide anything: "3% better for 4x the cost" is the actual call. These
# score a run against a budget rather than reporting the raw figure, because the registry's
# contract is a mean of floats in [0, 1] — and a ratio keeps 4x the cost visible as 0.25
# instead of clipping every over-budget run to the same 0.0.

def _sum_over_spans(output, keys: tuple[str, ...]) -> float | None:
    """Total of a numeric field across the spans, looking on the span and in result.meta.
    None when no span carries it — absent is not zero."""
    total, found = 0.0, False
    for s in trajectory(output):
        meta = _meta(s)
        for k in keys:
            n = _number(s.get(k) if s.get(k) is not None else meta.get(k))
            if n is not None:
                total += n
                found = True
                break
    return total if found else None


def _payload_number(output, keys: tuple[str, ...]) -> float | None:
    p = _dict(_payload(output))
    for k in keys:
        n = _number(p.get(k))
        if n is not None:
            return n
    return None


def _cost_usd(output) -> float | None:
    """What the run cost, in USD. Explicit payload total first, else the per-span costs. Not
    priced from tokens here: the price tables are versioned and server-side
    (services/pricing.py), and this module can't import them."""
    total = _payload_number(output, ("cost_usd", "cost", "total_cost_usd"))
    # Not `or`: a genuinely free run reports 0.0, which must not fall through to the spans.
    return total if total is not None else _sum_over_spans(output, ("cost_usd", "cost"))


def _latency_ms(output) -> float | None:
    """Wall-clock duration. Explicit payload value first, else the trajectory's roots: one
    root's duration covers its whole subtree, and for a partial tree (missing root, promoted
    orphans) the fragments are summed — an estimate, and the only one available."""
    n = _payload_number(output, ("latency_ms", "duration_ms", "latency"))
    if n is not None:
        return n
    spans = trajectory(output)
    if not spans:
        return None
    ids = {_span_id(s) for s in spans if _span_id(s)}
    roots = [s for s in spans if _parent_id(s) not in ids]
    return float(sum(_number(s.get("duration_ms")) or 0.0 for s in roots)) if roots else None


def _tokens(output) -> float | None:
    """Total tokens (input + output) across the spans — the cost proxy that needs no price
    table, so it works on any captured trace."""
    n = _payload_number(output, ("tokens", "total_tokens"))
    if n is not None:
        return n
    total, found = 0.0, False
    for s in trajectory(output):
        usage = _dict(_meta(s).get("usage")) or _dict(s.get("usage"))
        for k in ("input_tokens", "output_tokens", "prompt_tokens", "completion_tokens"):
            v = _number(usage.get(k))
            if v is not None:
                total += v
                found = True
    return total if found else None


def _within(value: float | None, budget: float | None) -> float | None:
    """1.0 at or under budget, then budget/value — 4x the budget scores 0.25. None when the
    output doesn't carry the figure; 0.0 when the budget itself is unusable."""
    if budget is None or budget <= 0:
        return 0.0
    if value is None:
        return None
    return 1.0 if value <= budget else budget / value


def cost_budget(output, expected) -> float | None:
    """Did the run stay inside a cost budget? The ceiling in USD comes from `expected`'s
    "max_cost_usd" or from `expected` itself ("0.02"); cost comes from the payload's cost_usd,
    as a total or per span. None when nothing priced the run — use token_budget, which needs
    no price table."""
    return _within(_cost_usd(output), _budget(expected, "max_cost_usd", "cost_budget"))


def latency_budget(output, expected) -> float | None:
    """Did the run stay inside a latency budget? The ceiling in milliseconds comes from
    `expected`'s "max_latency_ms" or from `expected` itself."""
    return _within(_latency_ms(output), _budget(expected, "max_latency_ms", "latency_budget"))


def token_budget(output, expected) -> float | None:
    """Did the run stay inside a token budget? The ceiling in total tokens (input + output,
    summed over the trajectory) comes from `expected`'s "max_tokens" or from `expected`."""
    return _within(_tokens(output), _budget(expected, "max_tokens", "token_budget"))


# The named registry pk.evaluate() and the portal resolve string scorer names against.
def session_turns(output) -> list[dict]:
    """Normalise a multi-turn output into [{input, output}, …] (#44).

    Accepts a captured session (a list of span dicts sharing a session_id, as
    `GET /api/traces` returns them), an already-shaped list of turns, or a JSON string of
    either. Returns [] when there is no conversation to score — so a session scorer reports
    "not applicable" rather than zero on a single-turn run, which would drag an experiment's
    mean with a judgement it never made.
    """
    import json as _json

    if isinstance(output, str):
        try:
            output = _json.loads(output)
        except ValueError:
            return []
    if isinstance(output, dict):
        output = output.get("turns") or output.get("session") or []
    if not isinstance(output, list) or not output:
        return []
    turns = []
    for item in output:
        if not isinstance(item, dict):
            continue
        if "input" in item or "output" in item:
            turns.append({"input": str(item.get("input") or ""),
                          "output": str(item.get("output") or "")})
            continue
        # A captured span: request.input / result.text, the shape the read API returns.
        req, res = item.get("request") or {}, item.get("result") or {}
        if isinstance(req, dict) or isinstance(res, dict):
            turns.append({"input": str((req or {}).get("input") or ""),
                          "output": str((res or {}).get("text") or "")})
    return [t for t in turns if t["input"] or t["output"]]


def session_complete(output, expected) -> float | None:
    """Did every turn produce an answer?

    The most common multi-turn failure is not a wrong answer but a turn that returned nothing
    — a tool timeout, a truncated stream — which single-turn scoring over the final output
    cannot see at all, because the last turn may be perfectly fine.
    """
    turns = session_turns(output)
    if not turns:
        return None
    answered = sum(1 for t in turns if t["output"].strip())
    return answered / len(turns)


def session_no_repeat(output, expected) -> float | None:
    """Did the assistant repeat itself across turns?

    A loop is the characteristic multi-turn failure — the agent restating the same answer while
    the user rephrases — and it is invisible to any scorer that only sees the final output.
    """
    turns = session_turns(output)
    if len(turns) < 2:
        return None
    seen, repeats = set(), 0
    for t in turns:
        norm = " ".join(t["output"].lower().split())
        if norm and norm in seen:
            repeats += 1
        seen.add(norm)
    return 1.0 - (repeats / len(turns))


def session_expected_covered(output, expected) -> float | None:
    """Share of the expected points that appear somewhere in the conversation.

    Scored over the WHOLE session rather than the final turn: in a multi-turn exchange the
    answer is often assembled across turns, so requiring it all in the last one would fail a
    conversation that actually succeeded.
    """
    turns = session_turns(output)
    if not turns:
        return None
    wants = [w.strip().lower() for w in str(expected or "").split("|") if w.strip()]
    if not wants:
        return None
    hay = " ".join(t["output"].lower() for t in turns)
    return sum(1 for w in wants if w in hay) / len(wants)


SCORERS = {
    # Multi-turn / session scorers (#44). Each returns None on a single-turn
    # run, so an inapplicable row is omitted rather than scored zero.
    "session_complete": session_complete,
    "session_no_repeat": session_no_repeat,
    "session_expected_covered": session_expected_covered,
    "exact_match": exact_match,
    "contains": contains,
    "regex_match": regex_match,
    "json_valid": json_valid,
    # trajectory — grade the path, not just the answer
    "expected_tools_used": expected_tools_used,
    "tool_order": tool_order,
    "no_repeat": no_repeat,
    "step_budget": step_budget,
    # RAG
    "faithfulness": faithfulness,
    "context_relevance": context_relevance,
    "answer_relevance": answer_relevance,
    # the trade-off axes
    "cost_budget": cost_budget,
    "latency_budget": latency_budget,
    "token_budget": token_budget,
}


def run_scorers(scorers, output: str, expected: str) -> dict[str, float]:
    """Apply each scorer (a name or a callable) to (output, expected) → {name: score}.
    Unknown names are skipped; a scorer that raises contributes 0.0.

    A scorer may also return None for "not applicable to this row" — a trajectory scorer on an
    output with no spans, a cost scorer on a run nothing priced. Its key is then omitted, not
    set to 0.0: an ungradeable row is not a failed one, and scoring it zero would drag the
    experiment mean by exactly as much as a genuine failure while looking identical to one."""
    out: dict[str, float] = {}
    for s in scorers or []:
        if callable(s):
            name, fn = getattr(s, "__name__", "scorer"), s
        else:
            name, fn = s, SCORERS.get(s)
        if fn is None:
            continue
        try:
            v = fn(output, expected)
            if v is None:
                continue
            out[name] = float(v)
        except Exception:
            out[name] = 0.0
    return out
