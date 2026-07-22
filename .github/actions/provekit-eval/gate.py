#!/usr/bin/env python3
"""The body of the provekit-eval action: run pk.evaluate(), diff it against a baseline,
decide whether the build passes, and render the PR comment.

Kept as a file rather than an inline `run:` block so it can be read, linted and fixed
without hunting through YAML escaping. It talks to exactly one ProveKit entry point —
`pk.evaluate(dataset, target, scorers=..., name=...)` — and one read endpoint,
`GET /v1/experiments/{id}` (project-key authed), for the baseline.

It never exits non-zero on a failed gate: the caller still needs to post the comment that
explains *why* it failed. The verdict travels as the `passed` output and action.yml turns
it into a failure at the very end.
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import os
import sys
import traceback
import urllib.error
import urllib.request

MARKER = "<!-- provekit-eval"


def _in(name: str, default: str = "") -> str:
    return (os.environ.get(f"INPUT_{name}") or default).strip()


def _num(raw: str):
    return float(raw) if raw else None


def _out(**pairs) -> None:
    """Write step outputs. Values are single-line by construction — paths and numbers —
    so no heredoc delimiter juggling."""
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as fh:
        for k, v in pairs.items():
            fh.write(f"{k}={v}\n")


# ---- resolving the things the workflow named as strings ----

def _load(spec: str):
    """`pkg.module:attr` or `path/to/file.py:attr` -> the attribute.

    Both forms exist because an eval target in CI is as often a loose script in the repo as
    it is an importable package.
    """
    if ":" not in spec:
        raise ValueError(f"expected 'module:attribute', got {spec!r}")
    where, _, attr = spec.rpartition(":")
    if where.endswith(".py"):
        if not os.path.exists(where):
            raise FileNotFoundError(f"{where} (relative to working-directory {os.getcwd()})")
        name = os.path.splitext(os.path.basename(where))[0]
        s = importlib.util.spec_from_file_location(name, where)
        mod = importlib.util.module_from_spec(s)
        sys.modules[name] = mod
        s.loader.exec_module(mod)
    else:
        mod = importlib.import_module(where)
    try:
        return getattr(mod, attr)
    except AttributeError as exc:
        raise AttributeError(f"{where} has no attribute {attr!r}") from exc


def _parse_scorers(raw: str, registry: dict):
    """Comma/newline-separated scorer names, or `module:fn` for your own.

    Unknown *names* are rejected here rather than passed through: `run_scorers` skips a name
    it doesn't recognise, so a typo would otherwise produce a green gate that scored nothing.
    """
    out, bad = [], []
    for part in raw.replace("\n", ",").split(","):
        part = part.strip()
        if not part:
            continue
        if ":" in part:
            out.append(_load(part))
        elif part in registry:
            out.append(part)
        else:
            bad.append(part)
    if bad:
        raise ValueError(f"unknown scorer(s) {', '.join(bad)}; built-ins are "
                         f"{', '.join(sorted(registry))} (or pass 'module:function')")
    if not out:
        raise ValueError("no scorers given")
    return out


# ---- baseline ----

def _fetch_experiment(endpoint: str, api_key: str, eid: str) -> dict:
    req = urllib.request.Request(
        f"{endpoint.rstrip('/')}/v1/experiments/{eid}",
        headers={"Authorization": f"Bearer {api_key}"})
    with urllib.request.urlopen(req, timeout=60) as r:   # noqa: S310 - fixed https(s) endpoint
        return json.loads(r.read().decode("utf-8"))


def _baseline(endpoint: str, api_key: str) -> tuple[dict | None, str]:
    """(summary, where-it-came-from). Two sources because the project-key API can list
    datasets but not experiments, so 'the previous run' has to be handed to us: either an
    explicit experiment id, or a summary file the last run left behind (cache/artifact)."""
    eid = _in("BASELINE_EXPERIMENT")
    if eid:
        try:
            return _fetch_experiment(endpoint, api_key, eid), f"experiment #{eid}"
        except (urllib.error.URLError, ValueError, TimeoutError) as exc:
            print(f"::warning::could not fetch baseline experiment {eid}: {exc}")
            return None, ""
    path = _in("BASELINE_FILE")
    if path and os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            return data, f"`{path}` (experiment #{data.get('id', '?')})"
        except (OSError, ValueError) as exc:
            print(f"::warning::could not read baseline file {path}: {exc}")
    elif path:
        print(f"::notice::no baseline at {path} — first run, nothing to compare against")
    return None, ""


# ---- rendering ----

def _f(v, nd: int = 3) -> str:
    return "—" if v is None else f"{v:.{nd}f}"


def _fd(d) -> str:
    if d is None:
        return "—"
    return "±0.000" if abs(d) < 5e-4 else f"{d:+.3f}"


def _delta(cur, base):
    return None if cur is None or base is None else cur - base


def _table(summary: dict, base: dict | None) -> str:
    cur_means = summary.get("scorer_means") or {}
    base_means = (base or {}).get("scorer_means") or {}
    stats = summary.get("scorer_stats") or {}
    rows = ["| scorer | baseline | this run | Δ | n | 95% CI |",
            "|---|---|---|---|---|---|"]
    for name in sorted(set(cur_means) | set(base_means)):
        cur, prev = cur_means.get(name), base_means.get(name)
        st = stats.get(name) or {}
        lo, hi = st.get("ci95_low"), st.get("ci95_high")
        ci = "—" if lo is None or hi is None else f"{lo:.3f} – {hi:.3f}"
        rows.append(f"| `{name}` | {_f(prev)} | {_f(cur)} | {_fd(_delta(cur, prev))} | "
                    f"{st.get('n', '—')} | {ci} |")
    rows.append(f"| **mean** | {_f((base or {}).get('mean_score'))} | "
                f"{_f(summary.get('mean_score'))} | "
                f"{_fd(_delta(summary.get('mean_score'), (base or {}).get('mean_score')))} | "
                f"{summary.get('result_count', '—')} | — |")
    return "\n".join(rows)


def _comment(summary: dict, base: dict | None, where: str, verdict: list[str],
             passed: bool, key: str) -> str:
    dataset = _in("DATASET")
    head = "PASS" if passed else "FAIL"
    lines = [f"{MARKER}:{key} -->",
             f"### ProveKit eval — **{head}**",
             "",
             f"`{dataset}` · experiment **#{summary.get('id', '?')}** "
             f"({summary.get('name', '')}) · {summary.get('result_count', 0)} results",
             ""]
    lines.append(_table(summary, base))
    lines.append("")
    if base:
        lines.append(f"Baseline: {where}.")
    else:
        lines.append("No baseline supplied — deltas appear once one is "
                     "(`baseline-experiment` or `baseline-file`).")
    lines += ["", *verdict]
    endpoint = _in("ENDPOINT").rstrip("/")
    if endpoint and summary.get("dataset_id"):
        lines += ["", f"Compare runs in the portal: {endpoint}/datasets"]
    return "\n".join(lines)


def _error_comment(exc: BaseException, key: str) -> str:
    tail = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))[-1500:]
    return "\n".join([f"{MARKER}:{key} -->",
                      "### ProveKit eval — **ERROR**",
                      "",
                      "The evaluation did not complete, so this PR is ungated.",
                      "",
                      "```",
                      tail.strip(),
                      "```"])


# ---- gate ----

def _verdict(summary: dict, base: dict | None) -> tuple[bool, list[str]]:
    """Two independent checks: an absolute floor, and how far the mean may fall against the
    baseline. A team that only sets the floor never notices a slow slide down to it; a team
    that only sets the tolerance never notices a bad first run."""
    threshold, tolerance = _num(_in("THRESHOLD")), _num(_in("MAX_REGRESSION"))
    mean, lines, passed = summary.get("mean_score"), [], True

    if threshold is None and tolerance is None:
        return True, ["No `threshold` or `max-regression` set — reporting only, not gating."]
    if mean is None:
        return False, ["**Nothing was scored** (no results, or no scorer produced a value), "
                       "so the gate cannot pass."]
    if threshold is not None:
        ok = mean >= threshold
        passed &= ok
        lines.append(f"{'✔' if ok else '✘'} mean **{mean:.3f}** "
                     f"{'≥' if ok else '<'} threshold {threshold:.3f}")
    if tolerance is not None:
        d = _delta(mean, (base or {}).get("mean_score"))
        if d is None:
            lines.append("· `max-regression` set but no baseline to compare against — skipped.")
        else:
            ok = d >= -tolerance
            passed &= ok
            lines.append(f"{'✔' if ok else '✘'} mean moved **{d:+.3f}** vs baseline "
                         f"(allowed −{tolerance:.3f})")
    return passed, lines


def main() -> int:
    key = _in("COMMENT_KEY") or _in("DATASET") or "default"
    body_file = os.path.join(os.environ.get("RUNNER_TEMP", "."), "provekit-eval-comment.md")
    summary_file = _in("SUMMARY_FILE", "provekit-eval-summary.json")
    try:
        import provekit as pk
        from provekit import scorers as pk_scorers

        endpoint, api_key = _in("ENDPOINT"), os.environ.get("INPUT_API_KEY", "")
        if not endpoint or not api_key:
            raise RuntimeError("endpoint and api-key are both required")
        os.environ["PROVEKIT_ENDPOINT"], os.environ["PROVEKIT_API_KEY"] = endpoint, api_key
        sys.path.insert(0, os.getcwd())   # so `target` can name a module in the repo

        target = _load(_in("TARGET"))
        scorers = _parse_scorers(_in("SCORERS", "exact_match"), pk_scorers.SCORERS)
        name = _in("EXPERIMENT_NAME") or f"ci {os.environ.get('GITHUB_SHA', '')[:7]}".strip()

        base, where = _baseline(endpoint, api_key)
        summary = pk.evaluate(_in("DATASET"), target, scorers=scorers, name=name)

        with open(summary_file, "w", encoding="utf-8") as fh:
            json.dump(summary, fh, indent=2)
        passed, lines = _verdict(summary, base)
        body = _comment(summary, base, where, lines, passed, key)
        mean = summary.get("mean_score")
        _out(**{"experiment-id": summary.get("id", ""),
                "mean-score": "" if mean is None else f"{mean:.6f}",
                "result-count": summary.get("result_count", 0),
                "passed": "true" if passed else "false",
                "summary-file": os.path.abspath(summary_file),
                "comment-file": body_file})
    except Exception as exc:                      # noqa: BLE001 - the comment is the report
        traceback.print_exc()
        body = _error_comment(exc, key)
        _out(**{"passed": "false", "comment-file": body_file, "mean-score": "",
                "experiment-id": "", "result-count": 0, "summary-file": ""})

    with open(body_file, "w", encoding="utf-8") as fh:
        fh.write(body + "\n")
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as fh:
            fh.write(body + "\n")
    print(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
