"""The .agentman file format — plain-text, git-diffable tests and flows.

A *test* file bundles one request (prompt | tool | agent), its assertions, and an
optional dataset of input rows — enough to re-run it anywhere, including CI.
A *flow* file carries a visual flow's graph. Connections are referenced BY NAME:
credentials never enter the file; they resolve against the local workspace at
import/run time.

Canonical test shape (YAML, stable field order):

    version: 1
    kind: test
    name: Support bot regression
    connection: OpenAI (prod)
    request:
      type: prompt
      model: gpt-4o-mini
      system: You are a support assistant.
      user: "{{message}}"
    assertions:
      - type: contains
        value: refund
    dataset:
      - name: angry customer
        variables: {message: "URGENT: refund now"}
"""
from __future__ import annotations

import yaml

VERSION = 1
KINDS = ("test", "flow")

# Stable, human-friendly field order per request type.
_REQ_ORDER = {
    "prompt": ["type", "model", "system", "user", "messages", "temperature", "max_tokens"],
    "tool": ["type", "tool", "args"],
    "agent": ["type", "method", "path", "headers", "body", "stream"],
}
_ASSERT_ORDER = ["type", "name", "path", "value", "schema", "criteria", "model"]

# Never serialized: secrets and workspace-local ids.
_STRIP = {"api_key", "connection_id", "assertions", "_k", "provider", "base_url", "url"}


def _ordered(d: dict, order: list[str]) -> dict:
    out = {k: d[k] for k in order if k in d and d[k] not in (None, "", {}, [])}
    out.update({k: v for k, v in d.items() if k not in out and k not in order})
    return out


def _clean_request(request: dict) -> dict:
    req = {k: v for k, v in request.items() if k not in _STRIP}
    return _ordered(req, _REQ_ORDER.get(request.get("type", ""), ["type"]))


def dump_test(name: str, request: dict, connection_name: str | None = None,
              dataset: list[dict] | None = None) -> str:
    doc: dict = {"version": VERSION, "kind": "test", "name": name or "test"}
    if connection_name:
        doc["connection"] = connection_name
    doc["request"] = _clean_request(request)
    asserts = request.get("assertions") or []
    if asserts:
        doc["assertions"] = [_ordered(dict(a), _ASSERT_ORDER) for a in asserts]
    if dataset:
        doc["dataset"] = [{"name": r.get("name") or f"row {i + 1}", "variables": r.get("variables") or {}}
                          for i, r in enumerate(dataset)]
    return yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=100)


def dump_flow(name: str, description: str, nodes: list, edges: list,
              connection_names: dict[int, str] | None = None) -> str:
    """connection_names maps connection_id -> name so flow files stay portable."""
    names = connection_names or {}
    out_nodes = []
    for n in nodes or []:
        node = dict(n)
        cfg = dict(node.get("config") or {})
        cid = cfg.pop("connection_id", None)
        if cid is not None and cid in names:
            cfg["connection"] = names[cid]
        node["config"] = cfg
        out_nodes.append(node)
    doc: dict = {"version": VERSION, "kind": "flow", "name": name or "flow"}
    if description:
        doc["description"] = description
    doc["nodes"] = out_nodes
    doc["edges"] = edges or []
    return yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=100)


def load(text: str) -> dict:
    """Parse + validate an .agentman document. Returns the normalized dict; the caller
    resolves `connection` names to ids against its own workspace."""
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError(f"not valid YAML: {exc}") from exc
    if not isinstance(doc, dict):
        raise ValueError("expected a YAML mapping at the top level")
    if doc.get("version") != VERSION:
        raise ValueError(f"unsupported version {doc.get('version')!r} (expected {VERSION})")
    kind = doc.get("kind")
    if kind not in KINDS:
        raise ValueError(f"unsupported kind {kind!r} (expected one of {KINDS})")
    if kind == "test":
        req = doc.get("request")
        if not isinstance(req, dict) or req.get("type") not in ("prompt", "tool", "agent"):
            raise ValueError("test needs a request with type prompt | tool | agent")
        if "api_key" in req:
            raise ValueError("credentials do not belong in .agentman files — use a connection name")
        for a in doc.get("assertions") or []:
            if not isinstance(a, dict) or not a.get("type"):
                raise ValueError("each assertion needs a type")
        for r in doc.get("dataset") or []:
            if not isinstance(r, dict):
                raise ValueError("each dataset row must be a mapping")
    else:  # flow
        if not isinstance(doc.get("nodes"), list) or not isinstance(doc.get("edges"), list):
            raise ValueError("flow needs nodes and edges lists")
    return doc
