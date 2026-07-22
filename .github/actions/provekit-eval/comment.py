#!/usr/bin/env python3
"""Post (or update) the eval comment on the pull request.

One sticky comment per gate, not one per push: a hidden `<!-- provekit-eval:KEY -->` marker
identifies the comment this action owns, so a ten-commit PR ends with one comment showing
the current deltas instead of ten stale ones. `KEY` defaults to the dataset, so two gates on
different datasets keep separate comments.

Standard library only — this runs before any of the workflow's own dependencies exist, and
the GitHub REST API is two calls.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

API = os.environ.get("GITHUB_API_URL", "https://api.github.com")


def _call(method: str, url: str, token: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json",
        "User-Agent": "provekit-eval-action"})
    with urllib.request.urlopen(req, timeout=30) as r:   # noqa: S310 - GITHUB_API_URL
        return json.loads(r.read().decode("utf-8") or "{}")


def _pr_number() -> int | None:
    path = os.environ.get("GITHUB_EVENT_PATH")
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            event = json.load(fh)
        for key in ("pull_request", "issue"):
            if isinstance(event.get(key), dict) and event[key].get("number"):
                return int(event[key]["number"])
    ref = os.environ.get("GITHUB_REF", "")       # refs/pull/123/merge
    parts = ref.split("/")
    return int(parts[2]) if len(parts) > 2 and parts[1] == "pull" and parts[2].isdigit() else None


def _find(repo: str, pr: int, token: str, marker: str) -> int | None:
    page = 1
    while page <= 10:
        rows = _call("GET", f"{API}/repos/{repo}/issues/{pr}/comments?per_page=100&page={page}",
                     token)
        if not rows:
            return None
        for c in rows:
            if marker in (c.get("body") or ""):
                return c["id"]
        page += 1
    return None


def main() -> int:
    body_file = os.environ.get("COMMENT_FILE", "")
    if not body_file or not os.path.exists(body_file):
        print("::warning::no eval comment body was produced; skipping PR comment")
        return 0
    with open(body_file, encoding="utf-8") as fh:
        body = fh.read()

    token, repo = os.environ.get("GITHUB_TOKEN", ""), os.environ.get("GITHUB_REPOSITORY", "")
    pr = _pr_number()
    if not token or not repo or not pr:
        print("::notice::not a pull request (or no token) — the eval report is in the job "
              "summary only")
        return 0

    marker = f"<!-- provekit-eval:{os.environ.get('COMMENT_KEY', 'default')} -->"
    try:
        existing = _find(repo, pr, token, marker)
        if existing:
            _call("PATCH", f"{API}/repos/{repo}/issues/comments/{existing}", token,
                  {"body": body})
            print(f"updated comment {existing} on #{pr}")
        else:
            _call("POST", f"{API}/repos/{repo}/issues/{pr}/comments", token, {"body": body})
            print(f"created comment on #{pr}")
    except urllib.error.HTTPError as exc:
        # A read-only token (fork PR) or a missing `pull-requests: write` permission must not
        # turn a passing eval into a failing job — the gate's verdict is decided elsewhere.
        print(f"::warning::could not post the PR comment ({exc.code} {exc.reason}). Grant "
              f"`permissions: pull-requests: write`, or read the job summary instead.",
              file=sys.stderr)
    except Exception as exc:      # noqa: BLE001 - commenting is best-effort, always
        print(f"::warning::could not reach the GitHub API: {exc!r}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
