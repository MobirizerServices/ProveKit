"""`provekit` — the command-line client for your portal.

Everything the portal shows sits behind a key-authed HTTP API, so anything you can click you
should be able to script: page yesterday's failures from a cron job, seed a dataset from a
fixture file, gate a deploy on an evaluation. Until now the only shipped commands were a
smoke test and a diagnostic, which left every one of those jobs to hand-rolled curl.

This is an **API client, not a second server**. It talks to the documented `/v1` endpoints
with a project key and never imports the app or opens the database, so the same command works
against localhost and against a portal three regions away.

    pip install provekit
    export PROVEKIT_API_KEY=pk_...                       # a project key from the portal
    export PROVEKIT_ENDPOINT=https://provekit.your-co.com
    provekit traces list --status failed --since 24h

Every command prints a table for humans and `--json` for machines, and exits non-zero when
the thing you asked for did not happen — so `set -e` in CI means what it says.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys

import httpx

from . import scorers as _scorers

_TIMEOUT = 60


class CliError(Exception):
    """Anything the operator can fix: bad config, a 4xx, an unreachable portal. Caught in
    main() and printed as one line, because a traceback tells a shell user nothing."""


# ---- config + HTTP ----
def _resolve(args) -> tuple[str, dict]:
    """Portal URL + auth header, from flags or the same two env vars the SDK reads."""
    key = getattr(args, "api_key", None) or os.environ.get("PROVEKIT_API_KEY")
    endpoint = getattr(args, "endpoint", None) or os.environ.get("PROVEKIT_ENDPOINT")
    if not key or not endpoint:
        raise CliError("set PROVEKIT_API_KEY and PROVEKIT_ENDPOINT (or pass --api-key / "
                       "--endpoint). Run `provekit doctor` to see which one is missing.")
    return endpoint.rstrip("/"), {"Authorization": f"Bearer {key}"}


def _send(base: str, headers: dict, method: str, path: str, *, params=None, body=None):
    try:
        return httpx.request(method, f"{base}{path}", headers=headers, params=params, json=body,
                             timeout=_TIMEOUT, follow_redirects=False)
    except httpx.HTTPError as exc:
        raise CliError(f"could not reach {base}: {exc}") from exc


def _detail(resp) -> str:
    """The server's own explanation, if it gave one — FastAPI puts it in `detail`."""
    try:
        body = resp.json()
    except ValueError:
        body = None
    if isinstance(body, dict) and body.get("detail"):
        return str(body["detail"])
    return (resp.text or "").strip()[:200]


def _unwrap(resp):
    if resp.status_code >= 400:
        raise CliError(f"{resp.request.method} {resp.request.url.path} → "
                       f"{resp.status_code} {_detail(resp)}".rstrip())
    return resp.json()


def _get(args, path: str, params: dict | None = None):
    base, headers = _resolve(args)
    return _unwrap(_send(base, headers, "GET", path, params=params))


def _post(args, path: str, body: dict):
    base, headers = _resolve(args)
    return _unwrap(_send(base, headers, "POST", path, body=body))


def _write(args, v1_path: str, api_path: str, body: dict):
    """POST a dataset write, tolerating a server too old to accept it on `/v1`.

    `POST /v1/datasets` and `/v1/datasets/{id}/items` are key-authed routes now
    (routers/dataset_writes.py), so against a current server the first attempt succeeds and
    the fallback below is never reached — `test_cli.py` pins that.

    The fallback stays because this CLI talks to *remote* instances it does not control: a
    self-hosted portal a release or two behind still only has the cookie-authed `/api` route,
    and failing there would make `datasets create` look broken rather than merely older.
    """
    base, headers = _resolve(args)
    resp = _send(base, headers, "POST", v1_path, body=body)
    if resp.status_code not in (404, 405):
        return _unwrap(resp)
    resp = _send(base, headers, "POST", api_path, body=body)
    if resp.status_code in (401, 403):
        raise CliError(
            "this portal accepts dataset writes only from a logged-in session, and a project "
            "key is not one. Create the dataset in the portal UI (Datasets → New), then use "
            "`provekit datasets list` and `eval run` from CI.")
    return _unwrap(resp)


# ---- output ----
def _emit(args, payload, text: str) -> int:
    """One place decides human-vs-machine, so every command honours --json identically.

    Flushed, because stdout is block-buffered when piped: without it a `--fail-under` failure
    written to stderr lands *above* the numbers explaining it in a CI log.
    """
    if getattr(args, "as_json", False):
        print(json.dumps(payload, indent=2, default=str), flush=True)
    else:
        print(text, flush=True)
    return 0


def _table(headers: list[str], rows: list[list[str]]) -> str:
    widths = [max([len(h)] + [len(r[i]) for r in rows]) for i, h in enumerate(headers)]
    lines = ["  ".join(h.ljust(w) for h, w in zip(headers, widths)).rstrip()]
    lines += ["  ".join(c.ljust(w) for c, w in zip(row, widths)).rstrip() for row in rows]
    return "\n".join(lines)


def _ms(value) -> str:
    if not value:
        return "-"
    return f"{value / 1000:.2f}s" if value >= 1000 else f"{int(value)}ms"


_UNITS = {"m": 1 / 60, "h": 1.0, "d": 24.0}


def _hours(since: str) -> int:
    """`--since 90m|24h|7d` → whole hours for the API's `window_hours`.

    Rounded UP: `--since 30m` must ask for a window that contains the last 30 minutes, and
    a truncated 0 would ask for none at all.
    """
    text = since.strip().lower()
    unit, number = ("h", text) if text[-1:].isdigit() else (text[-1:], text[:-1])
    try:
        value = float(number)
    except ValueError:
        value = -1.0
    if unit not in _UNITS or value <= 0:
        raise CliError(f"--since {since!r}: expected a duration like 90m, 24h or 7d")
    return max(1, math.ceil(value * _UNITS[unit]))


# ---- traces ----
def _render_traces(rows: list[dict]) -> str:
    if not rows:
        return "No traces matched."
    body = [[(r.get("trace_id") or "")[:16],
             r.get("status") or "-",
             (r.get("label") or "-")[:40],
             _ms(r.get("duration_ms")),
             str(r.get("span_count") or 1),
             str(r.get("tokens") or 0),
             (r.get("created_at") or "")[:19]] for r in rows]
    return _table(["TRACE", "STATUS", "LABEL", "DURATION", "SPANS", "TOKENS", "CREATED"], body)


def cmd_traces_list(args) -> int:
    params: dict = {"limit": args.limit}
    if args.status:
        params["status"] = args.status
    if args.since:
        params["window_hours"] = _hours(args.since)
    rows = _get(args, "/v1/traces", params)
    return _emit(args, rows, _render_traces(rows))


def _render_trace(spans: list[dict]) -> str:
    """The span tree, rebuilt from parent_span_id the same way the portal does."""
    children: dict[str, list[dict]] = {}
    for s in spans:
        children.setdefault(s.get("parent_span_id") or "", []).append(s)

    out: list[str] = []
    seen: set[int] = set()

    def walk(parent: str, depth: int) -> None:
        for s in children.get(parent, []):
            if s.get("id") in seen:      # a malformed parent chain must not spin forever
                continue
            seen.add(s.get("id"))
            mark = "x" if s.get("status") == "failed" else "-"
            out.append(f"{'  ' * depth}{mark} {s.get('label') or '(unnamed)'} "
                       f"[{s.get('type') or 'span'}] {_ms(s.get('duration_ms'))}")
            if s.get("error"):
                out.append(f"{'  ' * depth}    error: {s['error']}")
            walk(s.get("span_id") or "", depth + 1)

    walk("", 0)
    # A trace whose root span never arrived (the process died before it ended) has no child
    # of "" at all. Print those spans flat rather than an empty tree.
    for s in spans:
        if s.get("id") not in seen:
            walk(s.get("parent_span_id") or "", 0)
    return "\n".join(out)


def cmd_traces_get(args) -> int:
    spans = _get(args, f"/v1/traces/{args.trace_id}")
    return _emit(args, spans, _render_trace(spans))


# ---- datasets ----
def _dataset_id(args, ref: str) -> int:
    """Accept a dataset id or its name — a CI script should not have to know the id."""
    if ref.isdigit():
        return int(ref)
    for d in _get(args, "/v1/datasets"):
        if d.get("name") == ref:
            return int(d["id"])
    raise CliError(f"dataset {ref!r} not found")


def cmd_datasets_list(args) -> int:
    rows = _get(args, "/v1/datasets")
    if rows:
        text = _table(["ID", "NAME", "ITEMS", "CREATED"],
                      [[str(d.get("id")), d.get("name") or "-", str(d.get("item_count") or 0),
                        (d.get("created_at") or "")[:19]] for d in rows])
    else:
        text = "No datasets yet. Create one with `provekit datasets create <name>`."
    return _emit(args, rows, text)


def cmd_datasets_create(args) -> int:
    row = _write(args, "/v1/datasets", "/api/datasets",
                 {"name": args.name, "description": args.description})
    return _emit(args, row, f"Created dataset {row.get('id')} — {row.get('name')}")


def _items_from_file(path: str) -> list[dict]:
    """One JSON object per line ({input, expected?, meta?}). JSONL, not a JSON array, so a
    fixture file can be appended to and diffed a line at a time."""
    items = []
    try:
        with open(path, encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, 1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except ValueError as exc:
                    raise CliError(f"{path}:{lineno}: not valid JSON ({exc})") from exc
                if not isinstance(row, dict) or "input" not in row:
                    raise CliError(f"{path}:{lineno}: each line needs an object with an 'input' key")
                items.append({"input": row["input"], "expected": row.get("expected", ""),
                              "meta": row.get("meta") or {}})
    except OSError as exc:
        raise CliError(f"could not read {path}: {exc}") from exc
    if not items:
        raise CliError(f"{path} contained no items")
    return items


def cmd_datasets_add(args) -> int:
    if args.file:
        items = _items_from_file(args.file)
    elif args.input is not None:
        items = [{"input": args.input, "expected": args.expected, "meta": {}}]
    else:
        raise CliError("pass --input <text> or --file <items.jsonl>")

    dsid = _dataset_id(args, args.dataset)
    added = [_write(args, f"/v1/datasets/{dsid}/items", f"/api/datasets/{dsid}/items", item)
             for item in items]
    return _emit(args, added, f"Added {len(added)} item(s) to dataset {dsid}")


# ---- eval ----
def _run_target(command: str, item_input: str, timeout: int) -> str:
    """Feed one item to the target on stdin, take its stdout as the output.

    `pk.evaluate()` already covers "my target is a Python callable"; what nothing covered is
    a target that isn't Python. A subprocess is the CLI-native answer and language-agnostic.
    Run through the shell because the operator typed the command in their own shell and
    expects pipes and $VARS to work; it grants no privilege they did not already have.
    A failing target is a data point, not a crash — the same call pk.evaluate() makes.
    """
    try:
        proc = subprocess.run(command, shell=True, input=item_input, capture_output=True,
                              text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return f"ERROR: target timed out after {timeout}s"
    if proc.returncode != 0:
        return f"ERROR: target exited {proc.returncode}: {(proc.stderr or '').strip()[:200]}"
    return (proc.stdout or "").strip()


def _render_summary(summary: dict) -> str:
    lines = [f"Experiment {summary.get('id')} — {summary.get('name')}",
             f"{summary.get('result_count', 0)} results"]
    means = summary.get("scorer_means") or {}
    for name in sorted(means):
        lines.append(f"  {name}: {means[name]:.3f}")
    mean = summary.get("mean_score")
    lines.append(f"  mean_score: {mean:.3f}" if isinstance(mean, (int, float)) else "  mean_score: -")
    return "\n".join(lines)


def cmd_eval_run(args) -> int:
    dsid = _dataset_id(args, args.dataset)
    items = _get(args, f"/v1/datasets/{dsid}/items")
    if not items:
        raise CliError(f"dataset {args.dataset} has no items to evaluate")

    # argparse's `append` cannot carry a default without appending to it, so the default
    # lives here instead of in the parser.
    scorers = args.scorer or ["exact_match"]
    exp = _post(args, "/v1/experiments", {"name": args.name, "dataset_id": dsid})
    eid = exp["id"]
    for item in items:
        output = _run_target(args.command, item.get("input") or "", args.timeout)
        expected = item.get("expected") or ""
        _post(args, f"/v1/experiments/{eid}/results",
              {"item_id": item.get("id"), "input": item.get("input") or "", "output": output,
               "expected": expected, "scores": _scorers.run_scorers(scorers, output, expected)})

    summary = _get(args, f"/v1/experiments/{eid}")
    _emit(args, summary, _render_summary(summary))
    # The gate: a regression must fail the build, not just be reported in a log nobody reads.
    if args.fail_under is not None:
        mean = summary.get("mean_score")
        if not isinstance(mean, (int, float)) or mean < args.fail_under:
            print(f"provekit: mean_score {mean} is below --fail-under {args.fail_under}",
                  file=sys.stderr)
            return 1
    return 0


# ---- doctor ----
def cmd_doctor(args) -> int:
    """Delegate to the existing implementation so there is one diagnostic, not two."""
    from . import doctor

    report = doctor.run(send=args.send)
    use_color = not args.no_color and sys.stdout.isatty() and not os.environ.get("NO_COLOR")
    print(report.render(use_color))
    return 1 if report.worst == doctor.BAD else 0


# ---- provekit up (#38) ----
#
# Local mode already skips login and lands in a default project; what was still missing is
# *starting* the thing — two terminals running two commands, which is the step people bounce
# off before they ever see a trace.
#
# Deliberately spawns subprocesses rather than importing the server: this CLI's whole contract
# is core deps only (httpx), so `provekit traces list` keeps working in an environment that has
# no server installed. The server extra is checked for, and named, rather than blowing up with
# an ImportError from three frames down.

def _repo_frontend():
    """A checked-out frontend with its dependencies installed, if we're in the repo.

    Returns a Path or None. Imported locally so the CLI's import cost stays where it is.
    """
    import pathlib as _p
    here = _p.Path(__file__).resolve()
    for base in (_p.Path.cwd(), *here.parents[:4]):
        fe = base / "frontend"
        if (fe / "package.json").exists() and (fe / "node_modules").exists():
            return fe
    return None


def cmd_up(args) -> int:
    """Run the API (and the portal, in a checkout) with one command."""
    import shutil
    import signal
    import subprocess
    import time as _t

    try:
        import uvicorn  # noqa: F401
    except ImportError:
        raise CliError(
            "the server isn't installed in this environment. `provekit up` runs the API "
            "locally, which needs the server extra: pip install \"provekit[server]\". "
            "The read-only commands (traces, datasets, eval) work against a remote portal "
            "without it.") from None

    procs: list[tuple[str, subprocess.Popen]] = []

    def _stop(*_a):
        for name, proc in procs:
            if proc.poll() is None:
                proc.terminate()
        for _name, proc in procs:
            try:
                proc.wait(timeout=8)
            except Exception:
                proc.kill()

    api = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "provekit.main:app",
         "--host", args.host, "--port", str(args.port)])
    procs.append(("api", api))

    fe_dir = None if args.no_frontend else _repo_frontend()
    if fe_dir and shutil.which("npm"):
        procs.append(("portal", subprocess.Popen(
            ["npm", "run", "dev", "--", "--port", str(args.frontend_port)], cwd=str(fe_dir))))

    signal.signal(signal.SIGINT, lambda *a: (_stop(), sys.exit(0)))
    signal.signal(signal.SIGTERM, lambda *a: (_stop(), sys.exit(0)))

    # Wait for the API to actually answer before claiming it is up — printing a URL that 404s
    # for another two seconds is how a first run gets written off as broken.
    base = f"http://{'127.0.0.1' if args.host in ('0.0.0.0', '') else args.host}:{args.port}"
    ready = False
    for _ in range(60):
        if api.poll() is not None:
            break
        try:
            if httpx.get(f"{base}/healthz", timeout=1.0).status_code < 500:
                ready = True
                break
        except Exception:
            _t.sleep(0.5)
    if api.poll() is not None:
        _stop()
        raise CliError(f"the API exited immediately (code {api.returncode}). Run it directly to "
                       f"see why: python -m uvicorn provekit.main:app --port {args.port}")

    # flush=True throughout: this process then blocks forever, and Python block-buffers stdout
    # whenever it isn't a TTY — so piped or redirected, these lines would sit unseen in the
    # buffer while uvicorn's own logging (which configures its own handler) streamed past them.
    print(f"  API     {base}" + ("" if ready else "  (still starting)"), flush=True)
    if fe_dir:
        print(f"  Portal  http://localhost:{args.frontend_port}", flush=True)
    else:
        print("  Portal  not started — no built frontend beside this install.", flush=True)
        print("          The API is usable on its own; point the SDK at it with "
              f"PROVEKIT_ENDPOINT={base}", flush=True)
    print("\n  Local mode needs no login. Ctrl-C to stop.", flush=True)

    try:
        while True:
            for name, proc in procs:
                if proc.poll() is not None:
                    print(f"\n{name} exited (code {proc.returncode}); shutting down.", flush=True)
                    _stop()
                    return 1
            _t.sleep(0.5)
    except KeyboardInterrupt:
        _stop()
    return 0


# ---- parser ----
def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--endpoint", help="portal URL (default: $PROVEKIT_ENDPOINT)")
    common.add_argument("--api-key", help="project key (default: $PROVEKIT_API_KEY)")
    common.add_argument("--json", dest="as_json", action="store_true",
                        help="emit raw JSON instead of a table")

    parser = argparse.ArgumentParser(
        prog="provekit",
        description="Read and drive your ProveKit portal from a shell or CI job.")
    groups = parser.add_subparsers(dest="group", required=True)

    traces = groups.add_parser("traces", help="list and inspect captured runs")
    traces_cmds = traces.add_subparsers(dest="action", required=True)
    tl = traces_cmds.add_parser("list", parents=[common], help="recent traces, newest first")
    tl.add_argument("--status", help="filter by status, e.g. failed or completed")
    tl.add_argument("--limit", type=int, default=20, help="how many traces (default 20, max 200)")
    tl.add_argument("--since", help="only the last N: 90m, 24h, 7d")
    tl.set_defaults(func=cmd_traces_list)
    tg = traces_cmds.add_parser("get", parents=[common], help="the full span tree of one trace")
    tg.add_argument("trace_id")
    tg.set_defaults(func=cmd_traces_get)

    datasets = groups.add_parser("datasets", help="evaluation datasets")
    datasets_cmds = datasets.add_subparsers(dest="action", required=True)
    dl = datasets_cmds.add_parser("list", parents=[common], help="every dataset in the project")
    dl.set_defaults(func=cmd_datasets_list)
    dc = datasets_cmds.add_parser("create", parents=[common], help="create an empty dataset")
    dc.add_argument("name")
    dc.add_argument("--description", default="")
    dc.set_defaults(func=cmd_datasets_create)
    da = datasets_cmds.add_parser("add", parents=[common], help="add item(s) to a dataset")
    da.add_argument("dataset", help="dataset id or name")
    da.add_argument("--input", help="the item input")
    da.add_argument("--expected", default="", help="the expected output")
    da.add_argument("--file", help="JSONL of {input, expected?, meta?} — one item per line")
    da.set_defaults(func=cmd_datasets_add)

    ev = groups.add_parser("eval", help="run an offline evaluation")
    ev_cmds = ev.add_subparsers(dest="action", required=True)
    er = ev_cmds.add_parser("run", parents=[common],
                            help="score a command over a dataset and record an experiment")
    er.add_argument("--dataset", required=True, help="dataset id or name")
    er.add_argument("--command", required=True,
                    help="target command; the item input arrives on stdin, output read from stdout")
    er.add_argument("--scorer", action="append", default=None,
                    help=f"repeatable; one of {', '.join(sorted(_scorers.SCORERS))}")
    er.add_argument("--name", default="cli-eval", help="experiment name")
    er.add_argument("--timeout", type=int, default=60, help="per-item target timeout in seconds")
    er.add_argument("--fail-under", type=float, default=None,
                    help="exit 1 if mean_score falls below this — the CI regression gate")
    er.set_defaults(func=cmd_eval_run)

    up = groups.add_parser("up", help="run ProveKit locally (API, plus the portal in a checkout)")
    up.add_argument("--port", type=int, default=8000, help="API port (default 8000)")
    up.add_argument("--host", default="127.0.0.1", help="API bind address (default 127.0.0.1)")
    up.add_argument("--frontend-port", type=int, default=3000, help="portal port (default 3000)")
    up.add_argument("--no-frontend", action="store_true", help="run only the API")
    up.set_defaults(func=cmd_up)

    doc = groups.add_parser("doctor", help="say why no traces are arriving")
    doc.add_argument("--send", action="store_true", help="also send one probe span")
    doc.add_argument("--no-color", action="store_true", help="plain output")
    doc.set_defaults(func=cmd_doctor)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except CliError as exc:
        print(f"provekit: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
