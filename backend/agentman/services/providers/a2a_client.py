"""A2A (Agent2Agent) client — talk to any agent that speaks the Linux Foundation A2A
protocol. A2A hit v1.0 with 150+ orgs (AWS/Microsoft/ServiceNow/Salesforce) but the
official inspector is hobby-grade, so a real client is open ground.

Supported: agent-card discovery (v1.0 /.well-known/agent-card.json AND the v0.3
/.well-known/agent.json path), JSON-RPC 2.0 message/send (+ best-effort message/stream).
"""
from __future__ import annotations

import json
import uuid

import httpx

from ..netguard import guard_url

_CARD_PATHS = ["/.well-known/agent-card.json", "/.well-known/agent.json"]  # v1.0, then v0.3


async def fetch_card(base_url: str, headers: dict | None = None, timeout: float = 15) -> dict:
    """Fetch + lightly validate an agent card. Tries the v1.0 path then the v0.3 path."""
    base = base_url.rstrip("/")
    guard_url(base)
    last = None
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        for path in _CARD_PATHS:
            try:
                r = await client.get(base + path, headers=headers or None)
                if r.status_code == 200:
                    card = r.json()
                    if not isinstance(card, dict) or not card.get("name"):
                        raise ValueError("agent card missing 'name'")
                    card["_path"] = path
                    card["_version"] = card.get("protocolVersion") or card.get("version") or "unknown"
                    return card
                last = f"HTTP {r.status_code}"
            except Exception as exc:  # try the next path
                last = str(exc)
    raise RuntimeError(f"no agent card at {base} ({last})")


def _extract_text(result: dict) -> str:
    """Pull text out of an A2A Message or Task result (parts / artifacts / status)."""
    def parts_text(parts):
        return "".join(p.get("text", "") for p in (parts or []) if p.get("kind", "text") == "text")

    if not isinstance(result, dict):
        return ""
    if result.get("parts"):                      # a Message
        return parts_text(result["parts"])
    text = ""
    for art in result.get("artifacts") or []:    # a Task's artifacts
        text += parts_text(art.get("parts"))
    if text:
        return text
    status = result.get("status") or {}
    return parts_text((status.get("message") or {}).get("parts"))


def _endpoint(base_url: str, card: dict | None) -> str:
    # A2A v1.0 puts the JSON-RPC endpoint in the card's `url`.
    return (card or {}).get("url") or base_url.rstrip("/")


async def arun(*, base_url: str, text: str, headers: dict | None = None, stream: bool = False,
               card: dict | None = None, timeout: float = 120):
    """Send one message to an A2A agent; yield unified events (delta/result)."""
    endpoint = _endpoint(base_url, card)
    guard_url(endpoint)
    message = {"messageId": uuid.uuid4().hex, "role": "user",
               "parts": [{"kind": "text", "text": text}]}
    method = "message/stream" if stream else "message/send"
    payload = {"jsonrpc": "2.0", "id": uuid.uuid4().hex, "method": method,
               "params": {"message": message}}
    hdrs = {"Content-Type": "application/json", **(headers or {})}

    # follow_redirects stays False: guard_url only vetted the initial endpoint (SSRF).
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        if stream:
            collected = ""
            async with client.stream("POST", endpoint, json=payload, headers=hdrs) as resp:
                if resp.status_code >= 400:
                    raise RuntimeError(f"A2A error {resp.status_code}: {(await resp.aread()).decode()[:300]}")
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    try:
                        evt = json.loads(line[5:].strip())
                    except json.JSONDecodeError:
                        continue
                    result = evt.get("result", evt)
                    chunk = _extract_text(result)
                    if chunk:
                        collected += chunk
                        yield {"type": "delta", "text": chunk}
            yield {"type": "result", "data": {"text": collected} if collected else None,
                   "meta": {"protocol": "a2a", "streamed": True}}
            return

        resp = await client.post(endpoint, json=payload, headers=hdrs)
        if resp.status_code >= 400:
            raise RuntimeError(f"A2A error {resp.status_code}: {resp.text[:300]}")
        data = resp.json()
        if "error" in data:
            raise RuntimeError(str((data["error"] or {}).get("message", "A2A error")))
        result = data.get("result", data)
        text_out = _extract_text(result)
        if text_out:
            yield {"type": "delta", "text": text_out}
        yield {"type": "result", "data": result, "meta": {"protocol": "a2a"}}
