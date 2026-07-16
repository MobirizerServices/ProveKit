"""Generic HTTP agent caller — call any agent/API endpoint (like Postman), with optional
SSE streaming. Yields {"type":"delta"} for streamed text/events and {"type":"result"}
for a buffered JSON/text response."""
from __future__ import annotations

import json

import httpx


def run(*, base_url: str, method: str, path: str, headers: dict | None = None,
        body=None, stream: bool = False, timeout: float = 120):
    url = base_url.rstrip("/") + "/" + path.lstrip("/") if path else base_url.rstrip("/")
    method = (method or "POST").upper()
    hdrs = {"Accept": "application/json, text/event-stream", **(headers or {})}

    with httpx.Client(timeout=timeout) as client:
        if stream:
            with client.stream(method, url, json=body if body is not None else None, headers=hdrs) as resp:
                status = resp.status_code
                for line in resp.iter_lines():
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

        resp = client.request(method, url, json=body if body is not None else None, headers=hdrs)
        ctype = resp.headers.get("content-type", "")
        data = resp.json() if ctype.startswith("application/json") else resp.text
        yield {"type": "result", "data": data, "meta": {"status": resp.status_code}}
