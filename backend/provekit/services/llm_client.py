"""A thin, dependency-free caller that re-runs an LLM completion against a provider — the
capability behind the playground and replay harness. Normalizes a neutral
{model, messages, params} into each provider's shape and back, over httpx (no heavy SDKs).

Providers: openai | anthropic | openai_compatible (any OpenAI-shaped base_url) | mock (offline).
"""
from __future__ import annotations

import httpx

_TIMEOUT = 60.0


class LLMError(Exception):
    """A provider call failed (auth, rate limit, bad request, upstream error)."""


def _params(params: dict | None) -> dict:
    p = params or {}
    out = {}
    if p.get("temperature") is not None:
        out["temperature"] = float(p["temperature"])
    if p.get("top_p") is not None:
        out["top_p"] = float(p["top_p"])
    out["max_tokens"] = int(p.get("max_tokens") or 512)
    return out


async def complete(provider: str, model: str, messages: list[dict], params: dict | None = None,
                   *, api_key: str = "", base_url: str = "") -> dict:
    """Run a chat completion. Returns {output, usage:{input_tokens,output_tokens}, finish_reason}.
    Raises LLMError on any failure. `messages` is [{role, content}, …]."""
    provider = (provider or "").lower()
    if provider == "mock":
        return _mock(model, messages)
    if provider in ("openai", "openai_compatible"):
        return await _openai(model, messages, params, api_key,
                             base_url or "https://api.openai.com/v1")
    if provider == "anthropic":
        return await _anthropic(model, messages, params, api_key)
    raise LLMError(f"unknown provider '{provider}'")


def _mock(model: str, messages: list[dict]) -> dict:
    """Offline echo model — lets the playground work with no key, and keeps demos/tests hermetic.
    Deterministically transforms the last user message so edits visibly change the output."""
    last = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
    if not last and messages:
        last = messages[-1].get("content", "")
    text = f"[mock:{model}] " + " ".join(str(last).split()[:60]).strip()
    if not text.strip().endswith((".", "!", "?")):
        text += "."
    itok = sum(len(str(m.get("content", "")).split()) for m in messages)
    return {"output": text, "usage": {"input_tokens": itok, "output_tokens": len(text.split())},
            "finish_reason": "stop"}


async def _openai(model, messages, params, api_key, base_url) -> dict:
    if not api_key:
        raise LLMError("missing API key for this connection")
    url = base_url.rstrip("/") + "/chat/completions"
    body = {"model": model, "messages": messages, **_params(params)}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
            r = await c.post(url, json=body, headers={"Authorization": f"Bearer {api_key}"})
    except httpx.HTTPError as e:
        raise LLMError(f"network error: {e}") from e
    if r.status_code >= 400:
        raise LLMError(_err(r))
    data = r.json()
    choice = (data.get("choices") or [{}])[0]
    usage = data.get("usage") or {}
    return {"output": (choice.get("message") or {}).get("content") or "",
            "usage": {"input_tokens": usage.get("prompt_tokens") or 0,
                      "output_tokens": usage.get("completion_tokens") or 0},
            "finish_reason": choice.get("finish_reason") or ""}


async def _anthropic(model, messages, params, api_key) -> dict:
    if not api_key:
        raise LLMError("missing API key for this connection")
    # Anthropic wants system as a top-level field; messages are only user/assistant turns.
    system = "\n\n".join(str(m.get("content", "")) for m in messages if m.get("role") == "system")
    turns = [{"role": m["role"], "content": m.get("content", "")}
             for m in messages if m.get("role") in ("user", "assistant")]
    body = {"model": model, "messages": turns, **_params(params)}
    if system:
        body["system"] = system
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
            r = await c.post("https://api.anthropic.com/v1/messages", json=body,
                             headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"})
    except httpx.HTTPError as e:
        raise LLMError(f"network error: {e}") from e
    if r.status_code >= 400:
        raise LLMError(_err(r))
    data = r.json()
    parts = data.get("content") or []
    text = "".join(p.get("text", "") for p in parts if p.get("type") == "text")
    usage = data.get("usage") or {}
    return {"output": text,
            "usage": {"input_tokens": usage.get("input_tokens") or 0,
                      "output_tokens": usage.get("output_tokens") or 0},
            "finish_reason": data.get("stop_reason") or ""}


async def judge(provider: str, model: str, question: str, expected: str, output: str,
                *, api_key: str = "", base_url: str = "") -> float:
    """Model-graded score in [0,1] for how well `output` matches `expected`. For the mock
    provider it's a deterministic heuristic (no call); for real providers it grades via the model
    and parses the number. Never raises — returns 0.0 on any failure."""
    if (provider or "").lower() == "mock":
        exp = (expected or "").strip().lower()
        out = (output or "").strip().lower()
        if not exp:
            return 1.0 if out else 0.0
        return 1.0 if exp in out else (0.5 if any(w in out for w in exp.split()) else 0.0)
    messages = [
        {"role": "system", "content": "You are a strict grader. Score how well the answer matches "
         "the expected answer, from 0.0 (wrong) to 1.0 (perfect). Reply with ONLY the number."},
        {"role": "user", "content": f"Question:\n{question}\n\nExpected answer:\n{expected}\n\n"
         f"Answer to grade:\n{output}\n\nScore (0.0-1.0):"},
    ]
    try:
        r = await complete(provider, model, messages, {"max_tokens": 8, "temperature": 0},
                           api_key=api_key, base_url=base_url)
    except LLMError:
        return 0.0
    import re
    m = re.search(r"[01](?:\.\d+)?|0?\.\d+", r.get("output", ""))
    if not m:
        return 0.0
    try:
        return max(0.0, min(1.0, float(m.group())))
    except ValueError:
        return 0.0


def _err(r: httpx.Response) -> str:
    """Extract a clean provider error message (both OpenAI and Anthropic nest it under 'error')."""
    try:
        e = r.json().get("error")
        msg = e.get("message") if isinstance(e, dict) else str(e)
        return f"provider error {r.status_code}: {msg}"
    except Exception:
        return f"provider error {r.status_code}"
