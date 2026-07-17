"""Generic HTTP agent caller (async) — call any agent/API endpoint, with optional SSE
streaming. Yields {"type":"delta"} for streamed text/events and {"type":"result"} for a
buffered JSON/text response."""
from __future__ import annotations

import json

import httpx

from ..netguard import guard_url

# Cap a buffered agent response so a hostile/misbehaving endpoint can't OOM the worker.
MAX_RESPONSE_BYTES = 16 * 1024 * 1024


async def arun(*, base_url: str, method: str, path: str, headers: dict | None = None,
               body=None, stream: bool = False, timeout: float = 120):
    url = base_url.rstrip("/") + "/" + path.lstrip("/") if path else base_url.rstrip("/")
    guard_url(url)
    method = (method or "POST").upper()
    hdrs = {"Accept": "application/json, text/event-stream", **(headers or {})}

    # follow_redirects stays False (httpx default) on purpose: guard_url only vetted the
    # initial URL, so a redirect could point at an internal address (SSRF).
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        if stream:
            async with client.stream(method, url, json=body if body is not None else None, headers=hdrs) as resp:
                status = resp.status_code
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    if line.startswith("data:"):
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            yield {"type": "event", "data": json.loads(data)}
                        except json.JSONDecodeError:
                            yield {"type": "delta", "text": data}
                    else:
                        yield {"type": "delta", "text": line}
                yield {"type": "result", "data": None, "meta": {"status": status, "streamed": True}}
            return

        async with client.stream(method, url, json=body if body is not None else None, headers=hdrs) as resp:
            status = resp.status_code
            ctype = resp.headers.get("content-type", "")
            buf = bytearray()
            async for chunk in resp.aiter_bytes():
                buf += chunk
                if len(buf) > MAX_RESPONSE_BYTES:
                    raise ValueError(f"agent response exceeded {MAX_RESPONSE_BYTES} bytes")
            raw = bytes(buf)
        data = json.loads(raw) if ctype.startswith("application/json") and raw else raw.decode("utf-8", "replace")
        yield {"type": "result", "data": data, "meta": {"status": status}}
