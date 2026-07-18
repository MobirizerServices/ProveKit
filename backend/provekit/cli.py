"""`provekit` — headless runner for .provekit test files (CI).

    provekit run .provekit/tests/            # run every test file under a dir
    provekit run support-bot.yaml --format junit -o results.xml
    provekit import-promptfoo promptfooconfig.yaml -o .provekit/tests/

Connections resolve from a local file (default: .provekit/connections.yaml, then
~/.provekit/connections.yaml), NEVER from the test files. Secrets in that file may
be written as ${ENV_VAR} and are expanded from the environment at run time.

Exit code is non-zero when any assertion fails or any run errors — so CI gates on it.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from xml.sax.saxutils import escape

import yaml

from .services import assertions as ae
from .services import dispatch, testfile
from .services.promptfoo import import_promptfoo

_ENV_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


# ---- local connection registry (stands in for the DB in CLI mode) ----
class _Conn:
    def __init__(self, config):
        self.config = config


class _Registry:
    """Minimal object graph dispatch/assertions expect from a `db`: `.get(model, id)`."""
    def __init__(self, by_name: dict):
        self._by_name = by_name
        self._ids = {name: i + 1 for i, name in enumerate(by_name)}
        self._by_id = {i: _Conn(by_name[name]) for name, i in self._ids.items()}

    def id_of(self, name: str) -> int | None:
        return self._ids.get(name)

    def get(self, _model, cid):
        return self._by_id.get(cid)


def _expand_env(obj):
    if isinstance(obj, str):
        return _ENV_REF.sub(lambda m: os.environ.get(m.group(1), ""), obj)
    if isinstance(obj, dict):
        return {k: _expand_env(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_expand_env(v) for v in obj]
    return obj


def _load_connections(explicit: str | None) -> _Registry:
    paths = [explicit] if explicit else [".provekit/connections.yaml",
                                         str(Path.home() / ".provekit/connections.yaml")]
    for p in paths:
        if p and Path(p).exists():
            doc = yaml.safe_load(Path(p).read_text()) or {}
            return _Registry(_expand_env(doc.get("connections") or {}))
    return _Registry({})


# ---- running ----
def _run_case(reg, request, variables):
    rd = _collect(reg, request, variables)
    asserts = ae.evaluate(reg, request.get("assertions") or [], rd)
    ok = all(a["ok"] for a in asserts) if asserts else rd["status"] == "completed"
    return {"status": rd["status"], "error": rd["error"], "duration_ms": rd["duration_ms"],
            "text": rd["result"].get("text"), "assertions": asserts, "ok": ok}


def _collect(reg, req, variables):
    # dispatch is async; the CLI is sync, so drive it via the sync bridge (its own loop).
    r = dispatch.run_collect_sync(reg, req, variables)
    return {"result": {"text": r["text"], "output": r["output"], "meta": r["meta"]},
            "status": r["status"], "error": r["error"], "duration_ms": r.get("duration_ms", 0)}


def _resolve_request(doc, reg) -> tuple[dict, str | None]:
    """Build the runnable request from a test doc; returns (request, unresolved_connection)."""
    req = dict(doc["request"])
    name = doc.get("connection")
    cid = reg.id_of(name) if name else None
    if cid:
        req["connection_id"] = cid
    if doc.get("assertions"):
        req["assertions"] = doc["assertions"]
    # llm_judge assertions may name their own judge connection
    for a in req.get("assertions") or []:
        if a.get("type") == "llm_judge" and a.get("connection"):
            a["connection_id"] = reg.id_of(a["connection"])
    return req, (name if name and not cid else None)


def _iter_test_files(paths):
    for p in paths:
        path = Path(p)
        if path.is_dir():
            yield from sorted(path.rglob("*.yaml"))
            yield from sorted(path.rglob("*.yml"))
        elif path.exists():
            yield path
        else:
            print(f"warning: path not found: {p}", file=sys.stderr)


def cmd_run(args) -> int:
    reg = _load_connections(args.connections)
    cli_vars = dict(kv.split("=", 1) for kv in args.env) if args.env else {}
    files = list(_iter_test_files(args.paths))
    if not files:
        print("no .provekit test files found", file=sys.stderr)
        return 2

    suites = []
    for f in files:
        try:
            doc = testfile.load(f.read_text())
        except ValueError as exc:
            suites.append({"file": str(f), "error": f"parse error: {exc}", "cases": []})
            continue
        if doc.get("kind") != "test":
            continue  # flows aren't CI test units
        request, unresolved = _resolve_request(doc, reg)
        suite_name = doc.get("name") or f.stem  # `name` is optional in the format — don't KeyError
        rows = doc.get("dataset") or [{"name": None, "variables": {}}]
        cases = []
        for i, row in enumerate(rows):
            variables = {**cli_vars, **(row.get("variables") or {})}
            res = _run_case(reg, request, variables)
            res["name"] = row.get("name") or (f"row {i + 1}" if len(rows) > 1 else suite_name)
            cases.append(res)
        suites.append({"file": str(f), "name": suite_name, "cases": cases,
                       "error": (f"connection '{unresolved}' not found" if unresolved else None)})

    _render(suites, args.format, args.output)
    failed = sum(1 for s in suites for c in s["cases"] if not c["ok"]) + \
        sum(1 for s in suites if s.get("error"))
    return 1 if failed else 0


# ---- output renderers ----
_G, _R, _Y, _D, _X = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"


def _color(on: bool):
    return ("", "", "", "", "") if not on else (_G, _R, _Y, _D, _X)


def _render(suites, fmt, output):
    if fmt == "json":
        import json
        text = json.dumps({"suites": suites}, indent=2)
    elif fmt == "junit":
        text = _junit(suites)
    else:
        text = _pretty(suites, color=output is None and sys.stdout.isatty())
    if output:
        Path(output).write_text(text)
        print(f"wrote {fmt} report to {output}", file=sys.stderr)
    else:
        print(text)


def _pretty(suites, color: bool) -> str:
    g, r, y, d, x = _color(color)
    lines, total, passed = [], 0, 0
    for s in suites:
        if s.get("error") and not s["cases"]:
            lines.append(f"{r}✕{x} {s['file']} — {s['error']}")
            continue
        lines.append(f"{d}{s['file']}{x}")
        if s.get("error"):
            lines.append(f"  {y}! {s['error']}{x}")
        for c in s["cases"]:
            total += 1; passed += c["ok"]
            mark = f"{g}✓{x}" if c["ok"] else f"{r}✕{x}"
            lines.append(f"  {mark} {c['name']} {d}{c['duration_ms']}ms{x}")
            for a in c["assertions"]:
                am = f"{g}✓{x}" if a["ok"] else f"{r}✕{x}"
                lines.append(f"      {am} {a['type']}: {a['detail']}")
            if c["error"]:
                lines.append(f"      {r}error: {c['error']}{x}")
    head = f"{g if passed == total else r}{passed}/{total} passed{x}"
    lines.append("")
    lines.append(head)
    return "\n".join(lines)


def _junit(suites) -> str:
    out = ['<?xml version="1.0" encoding="UTF-8"?>', "<testsuites>"]
    for s in suites:
        cases = s["cases"]
        fails = sum(1 for c in cases if not c["ok"])
        errs = 1 if s.get("error") and not cases else 0
        out.append(f'  <testsuite name="{escape(s.get("name") or s["file"])}" '
                   f'tests="{len(cases)}" failures="{fails}" errors="{errs}">')
        if errs:
            out.append(f'    <testcase name="{escape(s["file"])}">'
                       f'<error message="{escape(s["error"])}"/></testcase>')
        for c in cases:
            t = (c["duration_ms"] or 0) / 1000
            out.append(f'    <testcase name="{escape(c["name"])}" time="{t:.3f}">')
            if not c["ok"]:
                detail = c["error"] or "; ".join(f"{a['type']}: {a['detail']}"
                                                 for a in c["assertions"] if not a["ok"])
                out.append(f'      <failure message="{escape(detail)}"/>')
            out.append("    </testcase>")
        out.append("  </testsuite>")
    out.append("</testsuites>")
    return "\n".join(out)


def cmd_import_promptfoo(args) -> int:
    docs, warnings = import_promptfoo(Path(args.config).read_text())
    outdir = Path(args.output or ".")
    outdir.mkdir(parents=True, exist_ok=True)
    for name, text in docs:
        (outdir / name).write_text(text)
        print(f"wrote {outdir / name}")
    for w in warnings:  # never drop anything silently
        print(f"warning: {w}", file=sys.stderr)
    print(f"imported {len(docs)} test(s) from {args.config}", file=sys.stderr)
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="provekit", description="Run .provekit agent tests.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="run test files or directories")
    run.add_argument("paths", nargs="+")
    run.add_argument("--connections", help="connections YAML (default: .provekit/connections.yaml)")
    run.add_argument("--env", action="append", metavar="KEY=VAL", help="extra template variables")
    run.add_argument("--format", choices=["pretty", "json", "junit"], default="pretty")
    run.add_argument("-o", "--output", help="write the report to a file instead of stdout")
    run.set_defaults(func=cmd_run)

    imp = sub.add_parser("import-promptfoo", help="convert a promptfoo config to .provekit tests")
    imp.add_argument("config")
    imp.add_argument("-o", "--output", help="output directory (default: cwd)")
    imp.set_defaults(func=cmd_import_promptfoo)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
