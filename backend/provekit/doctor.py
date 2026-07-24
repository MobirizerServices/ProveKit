"""`provekit doctor` — say why no traces are arriving.

The SDK is fail-open on purpose: a wrong key, an unset endpoint, a missing extra, and a
firewalled portal all degrade to a silent no-op so your agent never breaks. That is the right
call in production and the worst possible first-run experience, because every one of those
failures looks exactly like "working". This walks the same path the SDK takes and reports the
first thing that would stop a span reaching the portal, with the fix.

Every check is read-only apart from `--send`, which posts one probe span.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import urllib.error
import urllib.request
from . import trace as _trace
from urllib.parse import urlparse

OK, WARN, BAD = "ok", "warn", "bad"
_MARK = {OK: "PASS", WARN: "WARN", BAD: "FAIL"}

# A probe trace id that is obviously not a real run, so a doctor call can be recognised in
# the portal and ignored.
_PROBE_TRACE = "d0c70000000000000000000000000001"


class Report:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str, str]] = []

    def add(self, state: str, name: str, detail: str, fix: str = "") -> None:
        self.rows.append((state, name, detail, fix))

    @property
    def worst(self) -> str:
        states = {s for s, *_ in self.rows}
        return BAD if BAD in states else (WARN if WARN in states else OK)

    def render(self, use_color: bool) -> str:
        def paint(state: str, text: str) -> str:
            if not use_color:
                return text
            code = {OK: "32", WARN: "33", BAD: "31"}[state]
            return f"\033[{code}m{text}\033[0m"

        out = ["", "ProveKit doctor", "=" * 15, ""]
        for state, name, detail, fix in self.rows:
            out.append(f"  {paint(state, _MARK[state])}  {name}")
            if detail:
                out.append(f"        {detail}")
            if fix:
                out.append(f"        → {fix}")
        out.append("")
        if self.worst == OK:
            out.append("Everything checks out. If traces still aren't appearing, confirm the")
            out.append("project key belongs to the project you're looking at in the portal.")
        elif self.worst == WARN:
            out.append("Tracing will work, but something above will limit what you capture.")
        else:
            out.append("Tracing is NOT active. Fix the FAIL lines above, in order.")
        out.append("")
        return "\n".join(out)


def _installed(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def check_config(rep: Report) -> tuple[str | None, str | None]:
    key = os.environ.get("PROVEKIT_API_KEY")
    endpoint = os.environ.get("PROVEKIT_ENDPOINT")

    if not key:
        rep.add(BAD, "PROVEKIT_API_KEY", "not set",
                "Create a project key in the portal (API keys) and export PROVEKIT_API_KEY.")
    elif not key.startswith(("pk_", "agm_")):
        # Not fatal — a legacy or custom key may not carry the prefix — but a pasted URL or
        # a shell-mangled value is a common and otherwise invisible mistake.
        rep.add(WARN, "PROVEKIT_API_KEY", f"set, but doesn't look like a project key ({key[:6]}…)",
                "Project keys start with 'pk_'. Check you didn't paste something else.")
    else:
        rep.add(OK, "PROVEKIT_API_KEY", f"set ({key[:6]}…{key[-4:]})")

    if not endpoint:
        rep.add(BAD, "PROVEKIT_ENDPOINT", "not set",
                "Export your portal's base URL, e.g. PROVEKIT_ENDPOINT=https://provekit.your-co.com")
    else:
        parsed = urlparse(endpoint)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            rep.add(BAD, "PROVEKIT_ENDPOINT", f"{endpoint!r} is not a valid URL",
                    "Use the scheme and host only, e.g. https://provekit.your-co.com")
            endpoint = None
        elif parsed.path.rstrip("/").endswith("/v1/traces"):
            # The SDK appends /v1/traces itself, so this silently produces a 404 path.
            rep.add(BAD, "PROVEKIT_ENDPOINT", f"{endpoint!r} already ends in /v1/traces",
                    "Set the base URL only — the SDK appends /v1/traces itself.")
            endpoint = None
        else:
            rep.add(OK, "PROVEKIT_ENDPOINT", endpoint)
    return key, endpoint


def check_packages(rep: Report) -> bool:
    """The [trace] extra. Without the OTel SDK, configure() returns False and stays silent."""
    if not _installed("opentelemetry.sdk"):
        rep.add(BAD, "opentelemetry-sdk", "not installed — tracing can never start",
                'pip install "provekit[trace]"')
        return False
    rep.add(OK, "opentelemetry-sdk", "installed")
    return True


# (import that means the user is using it, instrumentor module, extra that provides it)
#
# This table is the single source of truth for "what ProveKit can auto-instrument". The CLI
# walks it against the local environment (`local_coverage`); the portal renders it as a
# catalogue (`coverage_catalog`) — see frontend/components/EmptyState.tsx, whose copy of the
# list is pinned to this one by tests/test_onboarding.py.
# What ProveKit can auto-instrument. DERIVED from provekit.trace, which is where the
# instrumentors are actually registered — not a second copy.
#
# It was a second copy, and it drifted: the runtime instrumented 24 libraries while this list
# advertised 10, so the product under-reported itself by more than half and nothing caught it.
# A catalogue that can disagree with the code it describes is worse than no catalogue, because
# it is quoted in comparisons and believed.
_COVERAGE = [(lib, mod, extra) for lib, mod, extra in _trace.catalogue()]


def coverage_catalog() -> list[dict[str, str]]:
    """The catalogue itself, with no reference to the local environment.

    The portal needs this list but can never compute the *local* answer: the libraries live in
    the user's virtualenv, on a machine the server has never seen. Showing the catalogue and
    saying so is honest; inferring "you aren't instrumenting langchain" from the absence of
    langchain spans would not be — a project that simply doesn't use langchain looks identical.
    """
    return [{"library": lib, "instrumentor": inst, "extra": extra}
            for lib, inst, extra in _COVERAGE]


def local_coverage() -> dict[str, list]:
    """Walk the catalogue against *this* interpreter's site-packages.

    `missing` is the interesting half: a library you clearly use whose instrumentor is absent,
    i.e. calls that will happen and produce no span at all.
    """
    return {
        "instrumented": [lib for lib, inst, _ in _COVERAGE
                         if _installed(lib) and _installed(inst)],
        "missing": [{"library": lib, "extra": extra} for lib, inst, extra in _COVERAGE
                    if _installed(lib) and not _installed(inst)],
    }


def check_coverage(rep: Report) -> None:
    """Libraries present whose instrumentor is not — the spans you'd expect but won't get."""
    local = local_coverage()
    missing = [(m["library"], m["extra"]) for m in local["missing"]]
    covered = local["instrumented"]

    if covered:
        rep.add(OK, "Instrumentation", "auto-instrumenting " + ", ".join(sorted(covered)))
    if missing:
        extras = sorted({e for _, e in missing})
        rep.add(WARN, "Instrumentation gap",
                "installed but not instrumented: " + ", ".join(sorted(lib for lib, _ in missing)),
                f'Calls to these won\'t appear as spans. pip install "{extras[0]}"')
    if not covered and not missing:
        rep.add(WARN, "Instrumentation", "no supported LLM library detected",
                "Spans from pk.trace/pk.span still work; provider calls won't auto-capture.")


def check_reachable(rep: Report, endpoint: str, key: str | None, send: bool) -> None:
    """Can we actually reach the ingest endpoint, and does the key authenticate?

    Without --send this posts an empty OTLP body: enough to exercise routing and auth without
    putting a fake span in the user's project.
    """
    url = endpoint.rstrip("/") + "/v1/traces"
    body = _probe_payload() if send else {"resourceSpans": []}
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json",
                 **({"Authorization": f"Bearer {key}"} if key else {})})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            code = resp.status
    except urllib.error.HTTPError as exc:
        code = exc.code
    except urllib.error.URLError as exc:
        rep.add(BAD, "Portal reachable", f"{url} — {exc.reason}",
                "Check the URL, that the portal is running, and that egress isn't blocked.")
        return
    except Exception as exc:
        rep.add(BAD, "Portal reachable", f"{url} — {exc}")
        return

    if code in (401, 403):
        rep.add(BAD, "Ingest auth", f"{url} rejected the key ({code})",
                "The key is wrong, revoked, or belongs to another deployment. Mint a new one.")
    elif code == 404:
        rep.add(BAD, "Portal reachable", f"{url} returned 404",
                "That host is reachable but isn't a ProveKit backend. Check PROVEKIT_ENDPOINT.")
    elif code == 429:
        rep.add(WARN, "Ingest auth", "rate-limited (429) — the key works",
                "This project is at its ingest limit; spans may be dropped.")
    elif 200 <= code < 300:
        rep.add(OK, "Portal reachable", f"{url} accepted the request ({code})")
        if send:
            rep.add(OK, "Probe span", f"sent — look for trace {_PROBE_TRACE[:8]}… in the portal")
    else:
        rep.add(WARN, "Portal reachable", f"{url} returned {code}")


def _probe_payload() -> dict:
    return {"resourceSpans": [{"scopeSpans": [{"spans": [{
        "name": "provekit.doctor", "traceId": _PROBE_TRACE, "spanId": "d0c7000000000001",
        "parentSpanId": "", "startTimeUnixNano": "1000000000",
        "endTimeUnixNano": "1000001000", "status": {"code": 1},
        "attributes": [{"key": "gen_ai.operation.name", "value": {"stringValue": "invoke_agent"}}],
    }]}]}]}


def run(send: bool = False) -> Report:
    rep = Report()
    key, endpoint = check_config(rep)
    has_otel = check_packages(rep)
    if has_otel:
        check_coverage(rep)
    if endpoint:
        check_reachable(rep, endpoint, key, send)
    else:
        rep.add(WARN, "Portal reachable", "skipped — no usable endpoint to test")
    return rep


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="provekit doctor",
        description="Diagnose why traces aren't reaching your ProveKit portal.")
    ap.add_argument("--send", action="store_true",
                    help="also send one probe span (writes to your project)")
    ap.add_argument("--no-color", action="store_true", help="plain output")
    args = ap.parse_args()

    rep = run(send=args.send)
    use_color = not args.no_color and sys.stdout.isatty() and not os.environ.get("NO_COLOR")
    print(rep.render(use_color))
    # Non-zero on a real failure so CI and setup scripts can gate on it.
    return 1 if rep.worst == BAD else 0


if __name__ == "__main__":
    raise SystemExit(main())
