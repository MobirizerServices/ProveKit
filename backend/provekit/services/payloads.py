"""Offload large span payloads out of the row.

Every prompt and completion lives inline in `runs.request` / `runs.result`. That is fine until
payloads get big, and then it is the dominant cost in the schema: the trace *list* selects
whole rows, so listing 50 traces drags 50 prompts across the wire to render 50 labels, and the
table that every hot index covers is mostly text nobody is reading.

So past a threshold the payload is written to a blob store and the row keeps a reference:

    {"__ref__": "sha256:...", "bytes": 41233, "preview": "first 200 chars…"}

Three properties that make this safe rather than clever:

- **Content-addressed.** The key is the hash of the content, so storing the same payload twice
  is one object, and a write is idempotent — a retried ingest (#184) cannot produce a second
  copy or a torn object.
- **The preview stays inline.** Search (#17), the trace list and the label never fetch a blob.
  If offload made the list page do N blob reads it would have moved the cost, not removed it.
- **A missing blob degrades to the preview**, loudly. Object stores lose things, and a trace
  that renders "[payload unavailable]" with its first 200 characters is far better than a 500
  — but it must say so rather than presenting the preview as the whole payload.

The default backend is the local filesystem, which is honest for a single-node self-host and
is the same shape S3 would slot into (`put`/`get` by key). Nothing here assumes S3, and
`offload_enabled()` is off by default: a deployment that hasn't chosen a store must not start
scattering its data across two places.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path

from ..config import get_settings

log = logging.getLogger("provekit.payloads")

REF_KEY = "__ref__"
PREVIEW_CHARS = 200


def offload_enabled() -> bool:
    s = get_settings()
    return bool(s.payload_offload_dir) and s.payload_offload_min_bytes > 0


def _root() -> Path:
    return Path(get_settings().payload_offload_dir)


def _path_for(key: str) -> Path:
    # Fan out on the first two hex chars: a single directory with a million entries is slow to
    # list and unpleasant to operate on, for no benefit.
    digest = key.split(":", 1)[-1]
    return _root() / digest[:2] / digest


def is_ref(value) -> bool:
    return isinstance(value, dict) and REF_KEY in value


def put(text: str) -> dict | None:
    """Store `text` and return its reference, or None if it couldn't be stored.

    Returning None rather than raising is deliberate: the caller falls back to storing inline,
    which is the behaviour that existed before this module. An offload store that is down
    should cost disk in the database, not the span.
    """
    if not isinstance(text, str) or not text:
        return None
    body = text.encode("utf-8")
    key = "sha256:" + hashlib.sha256(body).hexdigest()
    path = _path_for(key)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():          # content-addressed: identical content is one object
            tmp = path.with_suffix(".partial")
            with open(tmp, "wb") as fh:
                fh.write(body)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)      # atomic: a reader never sees a half-written blob
    except OSError as e:
        log.warning("payload offload failed (%s); storing inline", e)
        return None
    return {REF_KEY: key, "bytes": len(body), "preview": text[:PREVIEW_CHARS]}


def get(ref: dict) -> str | None:
    """Fetch an offloaded payload. None when the blob is gone."""
    if not is_ref(ref):
        return None
    try:
        return _path_for(ref[REF_KEY]).read_text(encoding="utf-8")
    except (OSError, ValueError):
        log.warning("offloaded payload %s is missing", ref.get(REF_KEY))
        return None


def maybe_offload(value):
    """Replace an over-threshold string with a reference; return anything else unchanged."""
    if not offload_enabled() or not isinstance(value, str):
        return value
    if len(value.encode("utf-8")) < get_settings().payload_offload_min_bytes:
        return value
    return put(value) or value


def resolve(value):
    """Inverse of `maybe_offload`, for a reader.

    A missing blob resolves to the preview with an explicit marker. Silently returning the
    preview would present a 200-character excerpt as the payload — the same class of lie as
    the truncation this codebase already refuses to do quietly (#6).
    """
    if not is_ref(value):
        return value
    body = get(value)
    if body is not None:
        return body
    preview = value.get("preview") or ""
    return f"{preview}\n\n[payload unavailable: {value.get(REF_KEY)} could not be read]"


def offload_row(row: dict) -> dict:
    """Offload the big free-text fields of a Run kwargs dict, in place.

    Runs after redaction, like the search column (#17) — offloading first would write the
    unmasked payload to the blob store, where redaction could never reach it.
    """
    if not offload_enabled():
        return row
    req = row.get("request")
    if isinstance(req, dict) and req.get("input"):
        req["input"] = maybe_offload(req["input"])
    res = row.get("result")
    if isinstance(res, dict) and res.get("text"):
        res["text"] = maybe_offload(res["text"])
    return row


def resolve_row(request: dict | None, result: dict | None) -> tuple[dict, dict]:
    """Inflate a stored row's payloads for a reader that wants the whole thing."""
    req = dict(request or {})
    res = dict(result or {})
    if is_ref(req.get("input")):
        req["input"] = resolve(req["input"])
    if is_ref(res.get("text")):
        res["text"] = resolve(res["text"])
    return req, res


def preview_of(value) -> str:
    """What a list view should show: the preview for a reference, the value otherwise.

    The trace list must never touch the blob store — doing N object reads to render N labels
    would move the cost rather than remove it.
    """
    if is_ref(value):
        return value.get("preview") or ""
    return value if isinstance(value, str) else ""
