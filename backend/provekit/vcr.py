"""Replay a captured run against its recorded tool responses.

Portal-side replay re-runs LLM calls and threads the new outputs downstream, but it cannot
re-run tools — ProveKit doesn't own them. So any run whose behaviour depends on a tool result
diverges from what really happened, and #194 made that limit visible (a tainted span is badged
DIVERGED and no longer trusted) rather than silently wrong. Visible is better than wrong; it
is still a gap.

The gap closes on this side of the wire, because the SDK *is* in the process that has the
tools. Register them with `@pk.tool`, call `pk.replay(trace_id, target)`, and every tool call
the target makes is answered from the recording:

    @pk.tool
    def get_weather(city: str) -> str: ...

    report = pk.replay("a1b2...", lambda: my_agent("plan a trip"))
    report.reliable      # False if anything had to fall through to a live call
    report.misses        # tool calls the recording had no answer for

Three modes, which are the three roadmap items this implements:

  recorded  (#54) Serve from the cassette. A miss raises. Deterministic, free, no side
                  effects — safe to run in CI against a production trace.
  live      (#53) Serve from the cassette; on a miss call the real tool. Faithful, but it
                  really does call the tool, so it is opt-in.
  dry-run   (#55) Serve from the cassette; on a miss return a marker instead of calling
                  anything. Shows you what *would* have been executed.

Matching is by (tool name, arguments), falling back to the next unused recording for that
tool in the order it originally ran — the same strategy HTTP VCR libraries use, and the one
that behaves sanely when a tool is called twice with arguments that changed.

SDK module: standard library plus httpx only, and no server imports (see AGENTS.md).
"""
from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field
from functools import wraps

log = logging.getLogger("provekit")

_registry: dict[str, callable] = {}
_state = threading.local()

RECORDED = "recorded"
LIVE = "live"
DRY_RUN = "dry-run"

#: Returned by a dry-run miss. Distinct object so a caller can test for it rather than
#: string-matching, and obviously not a real tool result if it reaches a model.
NOT_EXECUTED = "<provekit: tool not executed (dry-run)>"


class ReplayMiss(RuntimeError):
    """A tool was called that the recording has no answer for, in a mode that forbids
    falling through to the real thing."""


def tool(fn=None, *, name: str | None = None):
    """Register a function as a replayable tool.

    Outside a replay this is a passthrough that also opens a span, so the call is captured —
    which is what makes the *next* replay possible. Inside one, the call is answered from the
    cassette instead of running.
    """
    def _wrap(f):
        tool_name = name or f.__name__
        _registry[tool_name] = f

        @wraps(f)
        def inner(*args, **kwargs):
            session = getattr(_state, "session", None)
            if session is not None:
                return session.dispatch(tool_name, f, args, kwargs)
            return _traced(tool_name, f, args, kwargs)

        inner.__provekit_tool__ = tool_name    # lets a caller confirm registration
        return inner

    return _wrap(fn) if fn is not None else _wrap


def _traced(tool_name: str, f, args, kwargs):
    """Normal (non-replay) execution, wrapped in a span so the call lands in the trace."""
    from . import trace as _trace
    try:
        with _trace.span(tool_name, tool=tool_name, input=_canonical(args, kwargs)):
            return f(*args, **kwargs)
    except Exception:
        # Never let instrumentation change whether the user's tool runs.
        return f(*args, **kwargs)


def _canonical(args: tuple, kwargs: dict) -> str:
    """A stable key for a call's arguments.

    Sorted keys and positional args by index, so the same call keys identically across
    processes. Falls back to repr for anything unserialisable — a key that is merely stable
    is enough; it never has to round-trip.
    """
    try:
        return json.dumps({"args": list(args), "kwargs": kwargs}, sort_keys=True, default=repr)
    except (TypeError, ValueError):
        return repr((args, sorted(kwargs.items())))


@dataclass
class ReplayReport:
    """What a replay actually did — the honest accounting the portal-side path learned to give."""
    trace_id: str
    mode: str
    result: object = None
    hits: int = 0
    misses: list[str] = field(default_factory=list)
    live_calls: list[str] = field(default_factory=list)
    #: Calls answered from a recording made with *different* arguments (sequence fallback).
    #: Served so the replay can continue, but they are not evidence of anything.
    diverged: list[str] = field(default_factory=list)
    unused: list[str] = field(default_factory=list)

    @property
    def reliable(self) -> bool:
        """True only if every tool call was answered by a recording of *that same call*.

        A replay that had to invent a value — by calling the tool for real, by skipping it, or
        by serving a recording whose arguments no longer match — is a hypothesis about the run,
        not a reproduction of it. Same standard the server-side replay applies, and for the
        same reason: the confident answer built on inputs that no longer hold is the exact
        failure this feature exists to expose.
        """
        return not self.misses and not self.live_calls and not self.diverged

    def __repr__(self) -> str:
        return (f"ReplayReport(trace={self.trace_id[:8]}…, mode={self.mode}, hits={self.hits}, "
                f"misses={len(self.misses)}, live={len(self.live_calls)}, "
                f"diverged={len(self.diverged)}, reliable={self.reliable})")


class _Session:
    """Serves recorded responses for the duration of one replay."""

    def __init__(self, entries: list[dict], mode: str, allow: set[str] | None):
        self.mode = mode
        self.allow = allow
        self.report: ReplayReport | None = None
        # by exact (tool, args) key, and by tool name in recorded order for the fallback
        self._by_key: dict[tuple, list[dict]] = {}
        self._by_tool: dict[str, list[dict]] = {}
        for e in entries:
            self._by_key.setdefault((e.get("tool", ""), e.get("input", "")), []).append(e)
            self._by_tool.setdefault(e.get("tool", ""), []).append(e)
        self._used: set[int] = set()

    def _take(self, tool_name: str, key: str) -> tuple[dict | None, bool]:
        """(entry, exact) — `exact` is False when we fell back to sequence order."""
        for e in self._by_key.get((tool_name, key), []):
            if id(e) not in self._used:
                self._used.add(id(e))
                return e, True
        # Arguments changed (or were recorded in a different shape). Falling back to the next
        # unused recording for this tool keeps a replay of an *edited* run useful — but the
        # value is a recording of a call that was made with different arguments, so it is
        # evidence of nothing. It is served and then counted against reliability, never
        # silently as a hit. This is the same mistake server-side replay made before #194:
        # a tool whose input changed would not have returned its recorded result.
        for e in self._by_tool.get(tool_name, []):
            if id(e) not in self._used:
                self._used.add(id(e))
                return e, False
        return None, False

    def dispatch(self, tool_name: str, fn, args, kwargs):
        key = _canonical(args, kwargs)
        entry, exact = self._take(tool_name, key)
        if entry is not None:
            if not exact:
                self.report.diverged.append(f"{tool_name}({key[:120]})")
            self.report.hits += 1
            if entry.get("status") == "failed" and entry.get("error"):
                # The recording is of a failure. Reproducing the run means reproducing that,
                # not quietly succeeding where the original didn't.
                raise RuntimeError(entry["error"])
            return entry.get("output", "")

        label = f"{tool_name}({key[:120]})"
        self.report.misses.append(label)
        if self.mode == RECORDED:
            raise ReplayMiss(
                f"no recorded response for {label}. The replay diverged from the captured run — "
                f"use mode='live' to call the real tool, or mode='dry-run' to see what it would "
                f"have called.")
        if self.mode == DRY_RUN:
            return NOT_EXECUTED
        if self.allow is not None and tool_name not in self.allow:
            raise ReplayMiss(
                f"{tool_name} is not in the replay allowlist, so it was not called. "
                f"Pass allow={{'{tool_name}'}} to permit it.")
        self.report.live_calls.append(label)
        return fn(*args, **kwargs)

    def unused(self) -> list[str]:
        return [f"{e.get('tool', '')}" for group in self._by_tool.values()
                for e in group if id(e) not in self._used]


def fetch_cassette(trace_id: str, *, api_key: str | None = None,
                   endpoint: str | None = None) -> list[dict]:
    """Pull a trace's recorded tool calls from the portal."""
    import os

    import httpx
    from . import trace as _trace
    _trace.configure()
    key = api_key or _trace._api_key or os.environ.get("PROVEKIT_API_KEY")
    base = (endpoint or _trace._endpoint or os.environ.get("PROVEKIT_ENDPOINT") or "").rstrip("/")
    if not key or not base:
        raise RuntimeError("replay needs PROVEKIT_API_KEY and PROVEKIT_ENDPOINT "
                           "(or api_key=/endpoint= arguments)")
    r = httpx.get(f"{base}/v1/traces/{trace_id}/cassette",
                  headers={"Authorization": f"Bearer {key}"}, timeout=15)
    r.raise_for_status()
    return r.json().get("entries") or []


def replay(trace_id: str, target, *, mode: str = RECORDED, allow=None,
           api_key: str | None = None, endpoint: str | None = None,
           cassette: list[dict] | None = None) -> ReplayReport:
    """Run `target()` with its tool calls served from `trace_id`'s recording.

    `target` is a zero-argument callable — usually a lambda closing over the real entrypoint.
    Returns a ReplayReport; `report.result` is whatever the target returned.

    Nested replays are refused rather than silently sharing a cassette, which would make the
    inner run's hits and misses land in the outer run's accounting.
    """
    if mode not in (RECORDED, LIVE, DRY_RUN):
        raise ValueError(f"mode must be one of {RECORDED!r}, {LIVE!r}, {DRY_RUN!r}")
    if getattr(_state, "session", None) is not None:
        raise RuntimeError("pk.replay() is already active on this thread")

    entries = cassette if cassette is not None else fetch_cassette(
        trace_id, api_key=api_key, endpoint=endpoint)
    session = _Session(entries, mode, set(allow) if allow is not None else None)
    report = ReplayReport(trace_id=trace_id, mode=mode)
    session.report = report
    _state.session = session
    try:
        report.result = target()
    finally:
        _state.session = None
        report.unused = session.unused()
    return report


def registered_tools() -> list[str]:
    """Names ProveKit will intercept during a replay."""
    return sorted(_registry)
