"""Generic LLM streaming over httpx.AsyncClient — provider-agnostic (OpenAI, Anthropic,
any OpenAI-compatible base URL, OpenAI Responses / Open Responses).

`astream(...)` is an async generator yielding {"type":"delta"} tokens, optional
{"type":"node"} stop events, {"type":"tool_call"} when the model asks for a tool, and a
final {"type":"usage"}. Async so a long stream occupies the event loop, not a threadpool
thread.

Messages are provider-agnostic; each provider translates them on the way out:

    {"role": "user",      "content": str}
    {"role": "assistant", "content": str, "tool_calls": [{"id", "name", "args"}]}
    {"role": "tool",      "tool_call_id": str, "name": str, "content": str}

The caller (dispatch) owns the tool loop — it appends the assistant/tool turns above and
calls astream again. Providers disagree on how a tool round is represented, which is
exactly why that shape is normalized here rather than leaking into the dispatcher.
"""
from __future__ import annotations

import asyncio
import json

import httpx

from ..netguard import guard_url


def _mock_reply(user: str, system: str | None) -> str:
    """Canned but context-aware reply for the keyless demo agent."""
    u = (user or "").lower()
    sys = (system or "").lower()
    if not user:
        return "Hi — I'm the AgentMan demo agent. Ask me anything. I run with no API key, so you can try the console instantly."
    if "classify" in sys or "classify" in u:
        return "support_request"
    if "extract" in sys or "json" in sys:
        return '{"summary": "demo extraction", "priority": "normal", "is_demo": true}'
    if "agent" in u and any(k in u for k in ("what", "explain", "define")):
        return ("An AI agent is a program that reads context, decides on an action, and uses tools or model "
                "calls to reach a goal — often looping until the task is done. This reply came from AgentMan's "
                "built-in mock provider, so no API key was needed.")
    if any(k in u for k in ("urgent", "angry", "complaint", "refund", "cancel", "asap")):
        return "This looks urgent — it mentions a time-sensitive or negative signal, so I'd route it to a human. (Demo mock response.)"
    short = " ".join((user or "").split())[:160]
    return (f"Here's a demo answer to: \"{short}\". In a live run this would come from your OpenAI or Anthropic "
            "connection — swap one in from the Connections tab. For now this is AgentMan's keyless mock agent.")


def _mock_tool_args(schema: dict, user: str) -> dict:
    """Fill a tool's required string params with the user's text — enough for the keyless
    demo to make a real, plausible MCP call."""
    props = (schema or {}).get("properties") or {}
    args = {}
    for name in (schema or {}).get("required") or []:
        spec = props.get(name) or {}
        t = spec.get("type", "string")
        if t == "string":
            args[name] = " ".join((user or "demo").split())[:80]
        elif t in ("number", "integer"):
            args[name] = 1
        elif t == "boolean":
            args[name] = True
    return args


async def _stream_mock(system, messages, tools=None):
    """Stream a canned reply token-by-token — a working agent with no credentials.

    With tools attached it calls the first one once, then answers using the result, so the
    whole MCP tool-calling loop is demonstrable offline with no API key.
    """
    user = next((str(m.get("content") or "") for m in reversed(messages) if m.get("role") == "user"), "")
    already_ran = any(m.get("role") == "tool" for m in messages)
    if tools and not already_ran:
        t = tools[0]
        # the three provider tool schemas nest the name/params differently
        fn = t.get("function") or t
        schema = fn.get("parameters") or fn.get("input_schema") or {}
        yield {"type": "tool_call", "call": {"id": "mock-call-1", "name": fn.get("name", ""),
                                             "args": _mock_tool_args(schema, user)}}
        return
    if already_ran:
        out = next((str(m.get("content") or "") for m in reversed(messages) if m.get("role") == "tool"), "")
        reply = (f"The tool returned: {' '.join(out.split())[:200]}. "
                 "(Demo mock agent — it called a real MCP tool, with no API key.)")
    else:
        reply = _mock_reply(user, system)
    spent = 0.0  # cap total artificial delay so concurrent demo runs stay cheap
    for tok in reply.split(" "):
        yield {"type": "delta", "text": tok + " "}
        if spent < 0.6:
            await asyncio.sleep(0.012); spent += 0.012
    ptok = sum(len(str(m.get("content") or "").split()) for m in messages) + len((system or "").split())
    ctok = len(reply.split())
    yield {"type": "usage", "usage": {"prompt_tokens": ptok, "completion_tokens": ctok, "total_tokens": ptok + ctok}}


DEFAULT_BASE = {
    "openai": "https://api.openai.com/v1",
    "openai-responses": "https://api.openai.com/v1",
    "compatible": "http://localhost:11434/v1",
    "anthropic": "https://api.anthropic.com/v1",
}


# Some 2026 models reject sampling params — send temperature only when it's meaningful.
def _maybe_temp(body: dict, temperature: float) -> None:
    if temperature is not None:
        body["temperature"] = temperature


async def _aiter_sse(resp: httpx.Response):
    """Yield parsed `data:` JSON objects from an SSE response (skips [DONE])."""
    async for line in resp.aiter_lines():
        if not line or not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            return
        try:
            yield json.loads(data)
        except json.JSONDecodeError:
            continue


async def astream(*, provider: str, base_url: str, api_key: str, model: str,
                  system: str | None, messages: list[dict], temperature: float = 0.7,
                  max_tokens: int = 1024, tools: list[dict] | None = None):
    provider = (provider or "openai").lower()
    base = (base_url or DEFAULT_BASE.get(provider) or DEFAULT_BASE["openai"]).rstrip("/")

    if provider == "mock":
        async for ev in _stream_mock(system, messages, tools):
            yield ev
        return
    guard_url(base)
    if provider == "anthropic":
        gen = _stream_anthropic(base, api_key, model, system, messages, temperature, max_tokens, tools)
    elif provider == "openai-responses":
        gen = _stream_responses(base, api_key, model, system, messages, temperature, max_tokens, tools)
    else:
        gen = _stream_openai(base, api_key, model, system, messages, temperature, max_tokens, tools)
    async for ev in gen:
        yield ev


def _args(raw: str) -> dict:
    """Tool arguments arrive as a JSON string, streamed in fragments. A model can emit
    invalid JSON; that's a failed tool call, not a failed run, so it degrades to {}."""
    try:
        out = json.loads(raw or "{}")
        return out if isinstance(out, dict) else {}
    except json.JSONDecodeError:
        return {}


def collect_text_sync(**kwargs) -> str:
    """Drive astream to completion and return the concatenated text — for sync callers
    (the LLM-judge assertion, the CLI). Runs its own event loop; never call from within one."""
    async def _run():
        parts = []
        async for ev in astream(**kwargs):
            if ev["type"] == "delta":
                parts.append(ev["text"])
        return "".join(parts)
    return asyncio.run(_run())


def _openai_messages(messages: list[dict]) -> list[dict]:
    out = []
    for m in messages:
        if m.get("role") == "tool":
            out.append({"role": "tool", "tool_call_id": m.get("tool_call_id"),
                        "content": m.get("content", "")})
        elif m.get("tool_calls"):
            out.append({"role": "assistant", "content": m.get("content") or None,
                        "tool_calls": [{"id": c["id"], "type": "function",
                                        "function": {"name": c["name"],
                                                     "arguments": json.dumps(c.get("args") or {})}}
                                       for c in m["tool_calls"]]})
        else:
            out.append({"role": m.get("role", "user"), "content": m.get("content", "")})
    return out


async def _stream_openai(base, api_key, model, system, messages, temperature, max_tokens, tools=None):
    msgs = ([{"role": "system", "content": system}] if system else []) + _openai_messages(messages)
    body = {"model": model, "messages": msgs, "stream": True,
            "temperature": temperature, "max_tokens": max_tokens,
            "stream_options": {"include_usage": True}}
    if tools:
        body["tools"] = tools
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    async with httpx.AsyncClient(timeout=120, follow_redirects=False) as client:
        async with client.stream("POST", f"{base}/chat/completions", json=body, headers=headers) as resp:
            if resp.status_code >= 400:
                raise RuntimeError(f"LLM error {resp.status_code}: {(await resp.aread()).decode()[:400]}")
            # tool_calls stream in fragments keyed by index: the id and name land on the
            # first chunk, then `arguments` arrives a few characters at a time.
            pending: dict[int, dict] = {}
            async for obj in _aiter_sse(resp):
                for choice in obj.get("choices", []):
                    delta = choice.get("delta") or {}
                    if delta.get("content"):
                        yield {"type": "delta", "text": delta["content"]}
                    for tc in delta.get("tool_calls") or []:
                        slot = pending.setdefault(tc.get("index", 0), {"id": "", "name": "", "raw": ""})
                        if tc.get("id"):
                            slot["id"] = tc["id"]
                        fn = tc.get("function") or {}
                        if fn.get("name"):
                            slot["name"] = fn["name"]
                        if fn.get("arguments"):
                            slot["raw"] += fn["arguments"]
                if obj.get("usage"):
                    yield {"type": "usage", "usage": obj["usage"]}
            for slot in pending.values():
                if slot["name"]:
                    yield {"type": "tool_call",
                           "call": {"id": slot["id"], "name": slot["name"], "args": _args(slot["raw"])}}


def _responses_input(messages: list[dict]) -> list[dict]:
    """Responses takes a flat item list: a tool round is a function_call item followed by a
    matching function_call_output item, not assistant/tool roles."""
    items = []
    for m in messages:
        if m.get("role") == "tool":
            items.append({"type": "function_call_output", "call_id": m.get("tool_call_id"),
                          "output": m.get("content", "")})
            continue
        if m.get("content"):
            items.append({"role": "assistant" if m.get("role") == "assistant" else "user",
                          "content": m["content"]})
        for c in m.get("tool_calls") or []:
            items.append({"type": "function_call", "call_id": c["id"], "name": c["name"],
                          "arguments": json.dumps(c.get("args") or {})})
    return items


async def _stream_responses(base, api_key, model, system, messages, temperature, max_tokens, tools=None):
    """OpenAI Responses API / 'Open Responses' (also vLLM, Ollama, HF, OpenRouter)."""
    body = {"model": model, "input": _responses_input(messages), "stream": True,
            "max_output_tokens": max_tokens}
    if tools:
        body["tools"] = tools
    if system:
        body["instructions"] = system
    _maybe_temp(body, temperature)
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    async with httpx.AsyncClient(timeout=120, follow_redirects=False) as client:
        async with client.stream("POST", f"{base}/responses", json=body, headers=headers) as resp:
            if resp.status_code >= 400:
                raise RuntimeError(f"LLM error {resp.status_code}: {(await resp.aread()).decode()[:400]}")
            # `.added` announces the call with EMPTY arguments; `.done` carries the filled-in
            # ones. Both are kept in one slot per call_id so the later, fuller payload wins —
            # taking the first and deduping would report every call with no arguments at all.
            pending: dict[str, dict] = {}
            async for obj in _aiter_sse(resp):
                et = obj.get("type", "")
                if et == "response.output_text.delta" and obj.get("delta"):
                    yield {"type": "delta", "text": obj["delta"]}
                elif et in ("response.output_item.added", "response.output_item.done"):
                    item = obj.get("item") or {}
                    if item.get("type") != "function_call":
                        continue
                    cid = item.get("call_id") or item.get("id") or ""
                    slot = pending.setdefault(cid, {"name": "", "raw": ""})
                    if item.get("name"):
                        slot["name"] = item["name"]
                    if item.get("arguments"):
                        slot["raw"] = item["arguments"]
                    if et.endswith(".done") and slot["name"]:
                        yield {"type": "tool_call",
                               "call": {"id": cid, "name": slot["name"], "args": _args(slot["raw"])}}
                        pending.pop(cid, None)
                elif et in ("response.completed", "response.incomplete"):
                    usage = (obj.get("response") or {}).get("usage")
                    if usage:
                        yield {"type": "usage", "usage": usage}
            for cid, slot in pending.items():
                if slot["name"]:  # announced but never completed — report it rather than lose it
                    yield {"type": "tool_call",
                           "call": {"id": cid, "name": slot["name"], "args": _args(slot["raw"])}}


def _anthropic_messages(messages: list[dict]) -> list[dict]:
    """Anthropic carries a tool round as content blocks: tool_use on the assistant turn, and
    tool_result blocks on the *user* turn. Consecutive results must be merged into one user
    message — a separate message per result is rejected."""
    out: list[dict] = []
    for m in messages:
        role = m.get("role")
        if role == "tool":
            block = {"type": "tool_result", "tool_use_id": m.get("tool_call_id"),
                     "content": m.get("content", "")}
            if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list):
                out[-1]["content"].append(block)
            else:
                out.append({"role": "user", "content": [block]})
        elif m.get("tool_calls"):
            blocks = ([{"type": "text", "text": m["content"]}] if m.get("content") else [])
            blocks += [{"type": "tool_use", "id": c["id"], "name": c["name"],
                        "input": c.get("args") or {}} for c in m["tool_calls"]]
            out.append({"role": "assistant", "content": blocks})
        elif role in ("user", "assistant"):
            out.append({"role": role, "content": m.get("content", "")})
    return out


async def _stream_anthropic(base, api_key, model, system, messages, temperature, max_tokens, tools=None):
    body = {"model": model, "messages": _anthropic_messages(messages), "stream": True,
            "max_tokens": max_tokens}
    if tools:
        body["tools"] = tools
    _maybe_temp(body, temperature)
    if system:
        body["system"] = system
    headers = {"Content-Type": "application/json", "anthropic-version": "2023-06-01"}
    if api_key:
        headers["x-api-key"] = api_key
    async with httpx.AsyncClient(timeout=120, follow_redirects=False) as client:
        async with client.stream("POST", f"{base}/messages", json=body, headers=headers) as resp:
            if resp.status_code >= 400:
                raise RuntimeError(f"LLM error {resp.status_code}: {(await resp.aread()).decode()[:400]}")
            usage = {}
            cur: dict | None = None  # the tool_use block being streamed, if any
            async for obj in _aiter_sse(resp):
                t = obj.get("type")
                if t == "content_block_start":
                    blk = obj.get("content_block") or {}
                    if blk.get("type") == "tool_use":
                        cur = {"id": blk.get("id", ""), "name": blk.get("name", ""), "raw": ""}
                elif t == "content_block_delta":
                    d = obj.get("delta") or {}
                    if d.get("type") == "text_delta" and d.get("text"):
                        yield {"type": "delta", "text": d["text"]}
                    elif d.get("type") == "input_json_delta" and cur is not None:
                        # the tool's input object arrives as JSON text fragments
                        cur["raw"] += d.get("partial_json") or ""
                elif t == "content_block_stop" and cur is not None:
                    yield {"type": "tool_call",
                           "call": {"id": cur["id"], "name": cur["name"], "args": _args(cur["raw"])}}
                    cur = None
                elif t == "message_start":
                    usage = (obj.get("message") or {}).get("usage", {}) or usage
                elif t == "message_delta":
                    if obj.get("usage"):
                        usage = {**usage, **obj["usage"]}
                    stop = (obj.get("delta") or {}).get("stop_reason")
                    if stop and stop not in ("end_turn", "stop_sequence"):
                        yield {"type": "node", "data": {"stop_reason": stop}}
            if cur is not None:
                # Stream ended without a content_block_stop (truncated/aborted): still report
                # the call rather than losing it.
                yield {"type": "tool_call",
                       "call": {"id": cur["id"], "name": cur["name"], "args": _args(cur["raw"])}}
            if usage:
                yield {"type": "usage", "usage": usage}
