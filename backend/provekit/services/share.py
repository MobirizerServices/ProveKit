"""Shareable trace links: a stateless, HMAC-signed token that names one (workspace, trace),
what that link is allowed to show, and the issue-tracker handoff built from it.

No storage — the token carries the identifiers and a signature over them, so a public
read endpoint can verify it without a login. Signed with the app secret (namespaced so a
share token can never be mistaken for a session), so links can't be forged or edited.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import time
from dataclasses import dataclass
from urllib.parse import quote, urlparse

DEFAULT_TTL_DAYS = 30


def _share_key() -> bytes:
    from .auth import _secret
    return hashlib.sha256(b"share:" + _secret()).digest()


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


# ---- what a share link is allowed to show (#70) ----
#
# A share link leaves the company; the trace behind it should not have to. Prompts and
# completions are the most sensitive thing ProveKit stores and services/redact.py only masks
# the patterns it recognises, so "share" used to mean "hand over everything redaction missed".
#
# The token itself carries what to withhold — it is signed, so the recipient cannot widen their
# own grant by editing the link, and no table has to remember it. The withheld fields are then
# stripped from the rows *on the server*, before the response body exists. Hiding them in the
# client would leave every prompt one devtools tab away, which is not redaction at all.

#: Field names a share link can withhold. `input`/`output` are the payloads themselves,
#: `logs` the per-span log events (free text from the user's own code), `error` the exception
#: message (stack traces and DB errors quote data), `label` the span names (often a customer
#: id or a routing decision).
MASKABLE_FIELDS = ("input", "output", "error", "logs", "label")

#: What a reader sees in place of withheld content. Deliberately visible: a shared trace that
#: silently rendered an empty input would read as "the model was called with nothing".
WITHHELD = "[withheld from this share link]"


@dataclass(frozen=True)
class ShareMask:
    """Fields to withhold, optionally on named spans only.

    `spans` empty means the mask applies to every span in the trace — the safe reading, so a
    mask can never be widened into nothing by a span id that no longer exists.
    """
    fields: tuple[str, ...] = ()
    spans: tuple[str, ...] = ()

    @property
    def active(self) -> bool:
        return bool(self.fields)

    def covers(self, span_id: str) -> bool:
        return not self.spans or span_id in self.spans


NO_MASK = ShareMask()


def normalize_mask(fields=None, spans=None) -> ShareMask:
    """Validate a requested mask. Raises ValueError on an unknown field name rather than
    dropping it — a caller that asked to withhold `promt` must not be told the share is safe."""
    names = []
    for f in fields or ():
        f = str(f).strip().lower()
        if not f:
            continue
        if f not in MASKABLE_FIELDS:
            raise ValueError(f"unknown mask field {f!r}; choose from {', '.join(MASKABLE_FIELDS)}")
        if f not in names:
            names.append(f)
    if not names:
        return NO_MASK
    # Span ids are opaque hex from the exporter; the separators below are the only characters
    # that could confuse the encoding, so a span id containing one is rejected outright.
    ids = []
    for s in spans or ():
        s = str(s).strip()
        if not s:
            continue
        if any(c in s for c in ":,+"):
            raise ValueError(f"invalid span id {s!r}")
        if s not in ids:
            ids.append(s)
    return ShareMask(tuple(sorted(names)), tuple(sorted(ids)))


def make_share_token(ws_id: int, trace_id: str, ttl_days: int = DEFAULT_TTL_DAYS,
                     mask: ShareMask | None = None) -> str:
    """A signed link that expires. The payload carries an absolute expiry (epoch seconds);
    ttl_days<=0 mints a non-expiring link. `mask` rides along in the signed payload, so the
    link and the redaction it was granted under cannot be separated."""
    exp = 0 if ttl_days <= 0 else int(time.time()) + ttl_days * 86400
    raw = f"{ws_id}:{trace_id}:{exp}"
    if mask and mask.active:
        # Appended only when there is a mask, so an ordinary link is byte-identical to the ones
        # minted before this existed and every token already in the wild still verifies.
        raw += ":" + "+".join(mask.fields) + ":" + ",".join(mask.spans)
    payload = _b64(raw.encode())
    sig = _b64(hmac.new(_share_key(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{sig}"


def _parse(token: str) -> tuple[int, str, ShareMask] | None:
    try:
        payload, sig = token.split(".", 1)
        expected = _b64(hmac.new(_share_key(), payload.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(expected, sig):
            return None
        parts = _unb64(payload).decode().split(":")
        # New tokens are ws:trace:exp[:fields:spans]; tolerate legacy ws:trace (no expiry).
        ws_id, trace_id = parts[0], parts[1]
        exp = int(parts[2]) if len(parts) > 2 else 0
        if exp and time.time() > exp:
            return None    # expired
        fields = tuple(f for f in (parts[3].split("+") if len(parts) > 3 and parts[3] else []))
        if any(f not in MASKABLE_FIELDS for f in fields):
            # A field this build doesn't know how to strip. Signed, so it came from a newer (or
            # tampered-with) ProveKit — refuse the token rather than serve the payload it was
            # explicitly told to withhold.
            return None
        spans = tuple(s for s in (parts[4].split(",") if len(parts) > 4 and parts[4] else []) if s)
        return int(ws_id), trace_id, ShareMask(fields, spans)
    except (ValueError, TypeError, IndexError):
        return None


def verify_share_token(token: str, *, allow_masked: bool = False) -> tuple[int, str] | None:
    """Return (workspace_id, trace_id) for an authentic, unexpired token, else None.

    A masked token resolves only for a caller that says it will apply the mask. Readers that
    predate masking get None — refusing to serve a link is the only failure mode here that
    doesn't hand a stranger the prompts its author asked to withhold.
    """
    parsed = _parse(token)
    if parsed is None:
        return None
    ws_id, trace_id, mask = parsed
    if mask.active and not allow_masked:
        return None
    return ws_id, trace_id


def share_mask(token: str) -> ShareMask:
    """The mask a token was signed with (empty for an unmasked, invalid or expired token)."""
    parsed = _parse(token)
    return parsed[2] if parsed else NO_MASK


def _mask_request(request, out: set[str]) -> dict:
    """Drop the prompt, keep the call's shape (provider/model/operation) — a reader has to be
    able to tell which model was called even when they may not see what it was told."""
    req = dict(request or {})
    if req.get("input"):
        req["input"] = WITHHELD
        out.add("input")
    return req


def _mask_result(result, fields: tuple[str, ...], out: set[str]) -> dict:
    res = dict(result or {})
    meta = dict(res.get("meta") or {})
    if "output" in fields:
        # `text` is the completion; `output` the structured form of the same thing. Usage,
        # timing and params stay — they are counters, and they are what makes a masked trace
        # still worth sharing with a vendor debugging your latency.
        if res.get("text"):
            res["text"] = WITHHELD
            out.add("output")
        if res.get("output"):
            res["output"] = WITHHELD
            out.add("output")
    if "logs" in fields and meta.get("events"):
        meta["events"] = []
        out.add("logs")
    res["meta"] = meta
    return res


def apply_mask(rows: list[dict], mask: ShareMask) -> list[dict]:
    """Strip the withheld fields from span rows, and record on each row what was removed.

    Rows are copied, never mutated: the caller's list may be the same objects a cached or
    authenticated read path is about to serve.
    """
    if not mask.active:
        return rows
    out = []
    for row in rows:
        if not mask.covers(row.get("span_id") or ""):
            out.append(row)
            continue
        r = dict(row)
        removed: set[str] = set()
        if "input" in mask.fields:
            r["request"] = _mask_request(r.get("request"), removed)
        if "output" in mask.fields or "logs" in mask.fields:
            r["result"] = _mask_result(r.get("result"), mask.fields, removed)
        if "error" in mask.fields and r.get("error"):
            r["error"] = WITHHELD
            removed.add("error")
        if "label" in mask.fields and r.get("label"):
            r["label"] = WITHHELD
            removed.add("label")
        # Only what was actually removed: badging a span that had no input as "input withheld"
        # would make the reader hunt for content that never existed.
        r["withheld"] = sorted(removed)
        out.append(r)
    return out


def mask_span_rows(rows: list[dict], token: str) -> list[dict]:
    """Apply whatever mask `token` was signed with. This is the call a public read route makes
    on its way out — one line, so the masking cannot be forgotten in a route that grew."""
    return apply_mask(rows, share_mask(token))


def share_url(token: str) -> str:
    from ..config import get_settings
    return f"{get_settings().web_base_url.rstrip('/')}/shared/{token}"


# ---- handoff to an issue tracker (#69) ----
#
# A prefilled "new issue" URL, not an API call: ProveKit holds no tracker credential, stores no
# OAuth grant and makes no outbound request, so there is nothing here to leak or to rotate. The
# user's browser opens the link already logged in as themselves, which is also the right author
# for the issue. The cost is that the body must fit in a URL, hence the cap below.

#: Trackers whose prefill parameters are known. Anything else goes through `template`.
TRACKERS = ("github", "gitlab")

#: GitHub rejects very long request lines and proxies vary; keep the body well inside that.
BODY_CAP = 4000


def _repo_base(repo: str) -> str:
    """Normalize `owner/name` or a full project URL to an https base, or raise.

    Validated because the result is handed to the browser to open: a `javascript:` or
    `data:` "repo" would otherwise turn a support button into a script the user clicks.
    """
    repo = (repo or "").strip().rstrip("/")
    if not repo:
        raise ValueError("a repository is required")
    if "://" in repo:
        u = urlparse(repo)
        if u.scheme not in ("http", "https") or not u.hostname:
            raise ValueError("repository must be an http(s) URL or owner/name")
        base = f"{u.scheme}://{u.netloc}{u.path.rstrip('/')}"
    else:
        if repo.count("/") != 1 or any(c in repo for c in " ?#&"):
            raise ValueError("repository must look like owner/name")
        base = f"https://github.com/{repo}"
    return base[:-4] if base.endswith(".git") else base


def issue_context(rows: list[dict]) -> dict:
    """Summarise a trace for a bug report, from the rows a reader is actually allowed to see.

    Deliberately fed the MASKED rows: an issue is another place the trace leaves the company,
    and a withheld error message that reappears in the issue body was never withheld.
    """
    root = next((r for r in rows if not r.get("parent_span_id")), rows[0] if rows else {})
    failed = next((r for r in rows if r.get("status") == "failed"), None)
    model = next(((r.get("request") or {}).get("model") for r in rows
                  if (r.get("request") or {}).get("model")), "")
    return {
        "trace_id": root.get("trace_id") or "",
        "label": root.get("label") or "trace",
        "status": (failed or root).get("status") or "",
        "duration_ms": root.get("duration_ms") or 0,
        "span_count": len(rows),
        "model": model or "",
        "failed_label": (failed or {}).get("label") or "",
        "error": (failed or {}).get("error") or "",
    }


def issue_draft(ctx: dict, url: str, mask: ShareMask = NO_MASK) -> tuple[str, str]:
    """(title, body) for a new issue: what broke, on which model, and a link to the evidence."""
    what = ctx.get("failed_label") or ctx.get("label") or "trace"
    title = f"[ProveKit] {what} failed" if ctx.get("status") == "failed" else f"[ProveKit] {what}"
    lines = [f"Shared trace: {url}", ""]
    facts = [("Trace", f"`{ctx.get('trace_id', '')}`"), ("Status", ctx.get("status") or "—"),
             ("Model", ctx.get("model") or "—"), ("Spans", str(ctx.get("span_count", 0))),
             ("Duration", f"{ctx.get('duration_ms', 0)} ms")]
    lines += ["| | |", "|---|---|"] + [f"| {k} | {v} |" for k, v in facts] + [""]
    if ctx.get("failed_label"):
        lines += [f"**Failing span:** `{ctx['failed_label']}`", ""]
    if ctx.get("error"):
        lines += ["```", str(ctx["error"])[:1200], "```", ""]
    if mask.active:
        # Says so in the issue itself: whoever picks this up needs to know the link is partial
        # before they conclude the model was called with an empty prompt.
        lines.append(f"_Shared read-only. Withheld from this link: {', '.join(mask.fields)}._")
    return title[:200], "\n".join(lines)[:BODY_CAP]


def issue_url(tracker: str, repo: str, title: str, body: str, template: str = "") -> str:
    """A prefilled "new issue" URL. `template` (with {title}/{body} placeholders, already
    url-encoded on substitution) covers Linear, Jira and anything else a team uses — its
    prefill parameters are theirs to name, and guessing them would produce a link that
    silently drops the report."""
    t, b = quote(title, safe=""), quote(body, safe="")
    if template:
        u = urlparse(template)
        if u.scheme not in ("http", "https") or not u.hostname:
            raise ValueError("template must be an http(s) URL")
        return template.replace("{title}", t).replace("{body}", b)
    tracker = (tracker or "github").strip().lower()
    if tracker not in TRACKERS:
        raise ValueError(f"tracker must be one of {', '.join(TRACKERS)} (or pass a template)")
    base = _repo_base(repo)
    if tracker == "gitlab":
        return f"{base}/-/issues/new?issue[title]={t}&issue[description]={b}"
    return f"{base}/issues/new?title={t}&body={b}"
