"""Generic LLM streaming over httpx.AsyncClient — provider-agnostic (OpenAI, Anthropic,
any OpenAI-compatible base URL, OpenAI Responses / Open Responses).

`astream(...)` is an async generator yielding {"type":"delta"} tokens, optional
{"type":"node"} tool/stop events, and a final {"type":"usage"}. Async so a long stream
occupies the event loop, not a threadpool thread.
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


async def _stream_mock(system, messages):
    """Stream a canned reply token-by-token — a working agent with no credentials."""
    user = next((str(m.get("content") or "") for m in reversed(messages) if m.get("role") == "user"), "")
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
                  max_tokens: int = 1024):
    provider = (provider or "openai").lower()
    base = (base_url or DEFAULT_BASE.get(provider) or DEFAULT_BASE["openai"]).rstrip("/")

    if provider == "mock":
        async for ev in _stream_mock(system, messages):
            yield ev
        return
    guard_url(base)
    if provider == "anthropic":
        gen = _stream_anthropic(base, api_key, model, system, messages, temperature, max_tokens)
    elif provider == "openai-responses":
        gen = _stream_responses(base, api_key, model, system, messages, temperature, max_tokens)
    else:
        gen = _stream_openai(base, api_key, model, system, messages, temperature, max_tokens)
    async for ev in gen:
        yield ev


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


async def _stream_openai(base, api_key, model, system, messages, temperature, max_tokens):
    msgs = ([{"role": "system", "content": system}] if system else []) + messages
    body = {"model": model, "messages": msgs, "stream": True,
            "temperature": temperature, "max_tokens": max_tokens,
            "stream_options": {"include_usage": True}}
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    async with httpx.AsyncClient(timeout=120) as client:
        async with client.stream("POST", f"{base}/chat/completions", json=body, headers=headers) as resp:
            if resp.status_code >= 400:
                raise RuntimeError(f"LLM error {resp.status_code}: {(await resp.aread()).decode()[:400]}")
            async for obj in _aiter_sse(resp):
                for choice in obj.get("choices", []):
                    delta = (choice.get("delta") or {}).get("content")
                    if delta:
                        yield {"type": "delta", "text": delta}
                if obj.get("usage"):
                    yield {"type": "usage", "usage": obj["usage"]}


async def _stream_responses(base, api_key, model, system, messages, temperature, max_tokens):
    """OpenAI Responses API / 'Open Responses' (also vLLM, Ollama, HF, OpenRouter)."""
    input_items = [{"role": ("assistant" if m.get("role") == "assistant" else "user"),
                    "content": m.get("content", "")} for m in messages]
    body = {"model": model, "input": input_items, "stream": True, "max_output_tokens": max_tokens}
    if system:
        body["instructions"] = system
    _maybe_temp(body, temperature)
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    async with httpx.AsyncClient(timeout=120) as client:
        async with client.stream("POST", f"{base}/responses", json=body, headers=headers) as resp:
            if resp.status_code >= 400:
                raise RuntimeError(f"LLM error {resp.status_code}: {(await resp.aread()).decode()[:400]}")
            async for obj in _aiter_sse(resp):
                et = obj.get("type", "")
                if et == "response.output_text.delta" and obj.get("delta"):
                    yield {"type": "delta", "text": obj["delta"]}
                elif et in ("response.function_call_arguments.done", "response.output_item.added"):
                    item = obj.get("item") or {}
                    if item.get("type") == "function_call":
                        yield {"type": "node", "data": {"tool_calls": [{"name": item.get("name")}]}}
                elif et in ("response.completed", "response.incomplete"):
                    usage = (obj.get("response") or {}).get("usage")
                    if usage:
                        yield {"type": "usage", "usage": usage}


async def _stream_anthropic(base, api_key, model, system, messages, temperature, max_tokens):
    conv = [m for m in messages if m.get("role") in ("user", "assistant")]
    body = {"model": model, "messages": conv, "stream": True, "max_tokens": max_tokens}
    _maybe_temp(body, temperature)
    if system:
        body["system"] = system
    headers = {"Content-Type": "application/json", "anthropic-version": "2023-06-01"}
    if api_key:
        headers["x-api-key"] = api_key
    async with httpx.AsyncClient(timeout=120) as client:
        async with client.stream("POST", f"{base}/messages", json=body, headers=headers) as resp:
            if resp.status_code >= 400:
                raise RuntimeError(f"LLM error {resp.status_code}: {(await resp.aread()).decode()[:400]}")
            usage = {}
            async for obj in _aiter_sse(resp):
                t = obj.get("type")
                if t == "content_block_start":
                    blk = obj.get("content_block") or {}
                    if blk.get("type") == "tool_use":  # surface tool calls (tool_called assertions)
                        yield {"type": "node", "data": {"tool_calls": [{"name": blk.get("name")}]}}
                elif t == "content_block_delta":
                    d = obj.get("delta") or {}
                    if d.get("type") == "text_delta" and d.get("text"):
                        yield {"type": "delta", "text": d["text"]}
                elif t == "message_start":
                    usage = (obj.get("message") or {}).get("usage", {}) or usage
                elif t == "message_delta":
                    if obj.get("usage"):
                        usage = {**usage, **obj["usage"]}
                    stop = (obj.get("delta") or {}).get("stop_reason")
                    if stop and stop not in ("end_turn", "stop_sequence"):
                        yield {"type": "node", "data": {"stop_reason": stop}}
            if usage:
                yield {"type": "usage", "usage": usage}
