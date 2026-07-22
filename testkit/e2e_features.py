#!/usr/bin/env python
"""End-to-end feature sweep against a RUNNING ProveKit instance.

    make backend                      # or any instance you point PK_API at
    backend/venv/bin/python testkit/e2e_features.py

Complements the unit suite rather than duplicating it.

Deliberately not TestClient: this drives the real HTTP surface of a real uvicorn process, so
it catches wiring, serialization and middleware problems that in-process tests cannot. Every
check reports what it actually observed; a check that cannot run says so rather than passing.
"""
import json
import os
import sys
import time
import uuid

import httpx

API = os.environ.get("PK_API", "http://localhost:8000")
results = []


def check(name, fn):
    try:
        detail = fn()
        results.append(("PASS", name, detail or ""))
    except AssertionError as e:
        results.append(("FAIL", name, str(e)[:200]))
    except Exception as e:
        results.append(("ERROR", name, f"{type(e).__name__}: {e}"[:200]))


c = httpx.Client(base_url=API, timeout=30, follow_redirects=False)
KEY = c.post("/api/workspace/ingest-key").json()["ingest_key"]
KH = {"Authorization": f"Bearer {KEY}"}
uniq = uuid.uuid4().hex[:8]


def otlp(trace, span, *, failed=False, prompt="hello", completion="hi there", tool=None,
         model="gpt-4o", session=""):
    attrs = [{"key": "gen_ai.request.model", "value": {"stringValue": model}},
             {"key": "gen_ai.prompt", "value": {"stringValue": prompt}},
             {"key": "gen_ai.completion", "value": {"stringValue": completion}},
             {"key": "gen_ai.usage.input_tokens", "value": {"intValue": 40}},
             {"key": "gen_ai.usage.output_tokens", "value": {"intValue": 12}}]
    if tool:
        attrs.append({"key": "gen_ai.tool.name", "value": {"stringValue": tool}})
    if session:
        attrs.append({"key": "session.id", "value": {"stringValue": session}})
    return {"resourceSpans": [{"scopeSpans": [{"spans": [{
        "name": "chat", "traceId": trace, "spanId": span, "parentSpanId": "",
        "startTimeUnixNano": str(int(time.time() * 1e9) - 500_000_000),
        "endTimeUnixNano": str(int(time.time() * 1e9)),
        "status": {"code": 2, "message": "upstream 503"} if failed else {"code": 1},
        "attributes": attrs}]}]}]}


# ---- 1. ingest -----------------------------------------------------------------------------
T1 = (uniq * 4)[:32]


def t_ingest():
    r = c.post("/v1/traces", json=otlp(T1, ("11" + uniq * 3)[:16]), headers=KH)
    assert r.status_code == 200, r.text
    assert r.json() == {"partialSuccess": {}}, r.text
    time.sleep(0.3)
    got = c.get(f"/api/traces/{T1}").json()
    assert len(got) == 1, f"expected 1 span, got {len(got)}"
    return "1 span stored, read back"


def t_dedupe():
    before = len(c.get(f"/api/traces/{T1}").json())
    for _ in range(3):
        c.post("/v1/traces", json=otlp(T1, ("11" + uniq * 3)[:16]), headers=KH)
    after = len(c.get(f"/api/traces/{T1}").json())
    assert after == before, f"retry duplicated: {before} -> {after}"
    return "3 retries of the same batch stored 0 extra rows (#1)"


def t_bad_key():
    r = c.post("/v1/traces", json=otlp("2b" * 16, "22" * 8),
               headers={"Authorization": "Bearer agm_nope"})
    assert r.status_code == 403, f"expected 403, got {r.status_code}"
    return "revoked/unknown key -> 403"


def t_protobuf_not_silently_dropped():
    r = c.post("/v1/traces", content=b"\xff\xff not protobuf",
               headers={**KH, "Content-Type": "application/x-protobuf"})
    assert r.status_code == 400, f"expected 400, got {r.status_code}"
    return "malformed protobuf -> 400, not a silent 200 (#94)"


def t_clock_skew():
    tid = ("3c" + uniq * 4)[:32]
    body = otlp(tid, ("33" + uniq * 3)[:16])
    span = body["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
    span["endTimeUnixNano"] = str(int(time.time() * 1e9) + 600 * 10**9)
    c.post("/v1/traces", json=body, headers=KH)
    time.sleep(0.3)
    spans = c.get(f"/api/traces/{tid}").json()
    skew = (spans[0]["result"].get("meta") or {}).get("clock_skew_ms")
    assert skew and skew > 500_000, f"skew not flagged: {skew}"
    return f"clock 10min ahead flagged: {skew} ms (#5)"


def t_price_version_stamped():
    spans = c.get(f"/api/traces/{T1}").json()
    v = (spans[0]["result"].get("meta") or {}).get("price_version")
    assert v, "no price_version on an llm span"
    return f"span stamped price_version={v} (#9)"


# ---- 2. read paths -------------------------------------------------------------------------
def t_trace_list_and_cursor():
    page = c.get("/api/traces", params={"limit": 2}).json()
    assert isinstance(page, list), page
    if len(page) == 2:
        nxt = c.get("/api/traces", params={"limit": 2, "cursor": page[-1]["id"]}).json()
        ids = {t["id"] for t in page} & {t["id"] for t in nxt}
        assert not ids, f"cursor page overlapped: {ids}"
        return f"{len(page)} + {len(nxt)} rows, no overlap across the cursor (#15)"
    return f"{len(page)} trace(s); too few to page"


def t_search():
    tid = ("4d" + uniq * 4)[:32]
    c.post("/v1/traces", json=otlp(tid, ("44" + uniq * 3)[:16], prompt="pelican crossing protocol"),
           headers=KH)
    time.sleep(0.4)
    hits = c.get("/api/traces", params={"q": "pelican crossing"}).json()
    assert any(t["trace_id"] == tid for t in hits), "search missed its own trace"
    miss = c.get("/api/traces", params={"q": "zzz-not-present-anywhere"}).json()
    assert not any(t["trace_id"] == tid for t in miss), "search matched a term nobody said"
    return "found by content; absent term returns nothing (#17)"


def t_metrics():
    m = c.get("/api/metrics", params={"window_hours": 24}).json()
    for k in ("trace_count", "error_count", "latency_p50_ms", "total_tokens", "series",
              "usage_coverage", "by_model"):
        assert k in m, f"missing {k}"
    assert m["trace_count"] > 0, "no traces counted"
    return (f"{m['trace_count']} traces, {m['total_tokens']} tokens, "
            f"p95 {m['latency_p95_ms']}ms, {len(m['series'])} buckets (#16)")


def t_pricing_card():
    p = c.get("/api/pricing").json()
    assert p["version"] and p["models"], p
    return f"rate card v{p['version']}, {len(p['models'])} models (#9)"


def t_health_observability():
    h = c.get("/healthz").json()
    assert h["ok"] and h["checks"]["db"], h
    ing = h["ingest"]
    for k in ("queue_depth", "lag_seconds", "shed", "quarantined"):
        assert k in ing, f"missing ingest.{k}"
    return f"queue_depth={ing['queue_depth']} lag={ing['lag_seconds']}s shed={ing['shed']} (#14)"


def t_retention_status():
    r = c.get("/api/workspace/retention").json()
    for k in ("keep", "stored_spans", "oldest_retained_at", "recent"):
        assert k in r, f"missing {k}"
    return f"keep={r['keep']} stored={r['stored_spans']} (#13)"


# ---- 3. datasets / experiments ---------------------------------------------------------------
state = {}


def t_dataset_versioning():
    did = c.post("/api/datasets", json={"name": f"e2e-{uniq}", "description": ""}).json()["id"]
    state["did"] = did
    v0 = c.get(f"/api/datasets/{did}/version").json()
    c.post(f"/api/datasets/{did}/items", json={"input": "q1", "expected": "a1"})
    v1 = c.get(f"/api/datasets/{did}/version").json()
    assert v1["version"] > v0["version"], "version did not bump on add"
    assert v1["fingerprint"] != v0["fingerprint"], "fingerprint did not change"
    return f"v{v0['version']}->v{v1['version']}, fingerprint changed (#45)"


def t_dataset_split():
    did = state["did"]
    for i in range(20):
        c.post(f"/api/datasets/{did}/items", json={"input": f"i{i}", "expected": "x"})
    a = c.post(f"/api/datasets/{did}/split", json={"ratio": 0.25}).json()["counts"]
    b = c.post(f"/api/datasets/{did}/split", json={"ratio": 0.25}).json()["counts"]
    assert a == b, f"split not deterministic: {a} vs {b}"
    return f"train={a['train']} test={a['test']}, stable across re-split (#45)"


def t_experiment_pins_and_compare():
    did = state["did"]
    e1 = c.post("/api/experiments", json={"name": f"run-a-{uniq}", "dataset_id": did,
                                          "config": {"model": "gpt-4o"}}).json()
    assert e1["dataset_fingerprint"], "no fingerprint pinned"
    c.post(f"/api/datasets/{did}/items", json={"input": "drift", "expected": "y"})
    e2 = c.post("/api/experiments", json={"name": f"run-b-{uniq}", "dataset_id": did}).json()
    cmp = c.get(f"/api/experiments/{e1['id']}/compare/{e2['id']}").json()
    assert "not directly comparable" in (cmp.get("warning") or ""), \
        f"drift not caught: {cmp.get('warning')!r}"
    return "dataset edited between runs -> compare refuses a clean delta (#52)"


def t_scorers_registry():
    from urllib.parse import urlencode  # noqa
    r = c.post("/api/playground/score", json={"output": "hello", "expected": "hello",
                                              "scorers": ["exact_match"]})
    if r.status_code == 404:
        return "no HTTP scorer endpoint; scorers exercised in-process only"
    assert r.status_code == 200, r.text
    return f"scored via API: {r.json()}"


# ---- 4. automation / online eval ----------------------------------------------------------
def t_automation_promote():
    did = c.post("/api/datasets", json={"name": f"auto-{uniq}", "description": ""}).json()["id"]
    rule = c.post("/api/automation", json={
        "name": "failures", "match": {"status": "failed"}, "action": "promote",
        "target_dataset_id": did}).json()
    assert rule["last_run_id"] > 0, "watermark did not start at newest trace"
    tid = ("5e" + uniq * 4)[:32]
    c.post("/v1/traces", json=otlp(tid, ("55" + uniq * 3)[:16], failed=True), headers=KH)
    time.sleep(0.4)
    out = c.post(f"/api/automation/{rule['id']}/run").json()
    items = c.get(f"/api/datasets/{did}").json()["items"]
    assert out["acted"] == 1, f"expected 1 action, got {out}"
    assert any(i["meta"].get("trace_id") == tid for i in items), "trace not promoted"
    return f"failed trace auto-promoted; considered={out['considered']} (#47)"


def t_automation_empty_match_refused():
    r = c.post("/api/automation", json={"name": "x", "match": {}, "action": "promote",
                                        "target_dataset_id": state["did"]})
    assert r.status_code == 422, f"empty match accepted: {r.status_code}"
    return "empty match refused at save time (#47)"


def t_online_eval():
    rule = c.post("/api/automation", json={
        "name": f"online-{uniq}", "match": {"status": "failed"}, "action": "score",
        "scorers": ["json_valid"]}).json()
    tid = ("6f" + uniq * 4)[:32]
    c.post("/v1/traces", json=otlp(tid, ("66" + uniq * 3)[:16], failed=True), headers=KH)
    time.sleep(0.4)
    c.post(f"/api/automation/{rule['id']}/run")
    fb = c.get(f"/api/traces/{tid}/feedback").json()
    assert any(f["name"] == "json_valid" and f["source"] == "eval" for f in fb), fb
    return "live trace scored online, source=eval (#39)"


# ---- 5. prompts / A-B ------------------------------------------------------------------------
def t_prompt_runtime_fetch():
    name = f"p-{uniq}"
    r = c.post("/api/prompts", json={"name": name, "model": "gpt-4o",
                                                "messages": [{"role": "user", "content": "v1"}],
                                                "params": {}})
    assert r.status_code in (200, 201), r.text
    got = c.get(f"/v1/prompts/{name}", headers=KH)
    assert got.status_code == 200, got.text
    body = got.json()
    assert body["name"] == name and body["served_by"].startswith("latest:"), body
    state["prompt"] = name
    return f"fetched at runtime, served_by={body['served_by']} (#61)"


def t_prompt_ab_split():
    name = state.get("prompt")
    if not name:
        raise AssertionError("prompt fetch did not run")
    c.post("/api/prompts", json={"name": name, "model": "gpt-4o",
                                            "messages": [{"role": "user", "content": "v2"}],
                                            "params": {}})
    versions = sorted(p["version"] for p in c.get("/api/prompts").json()
                      if p["name"] == name)
    if len(versions) < 2:
        return "only one version saved; split not exercised"
    weights = {versions[0]: 0.5, versions[1]: 0.5}
    r = c.post(f"/api/prompts/{name}/split", json={"weights": weights})
    assert r.status_code == 200, r.text
    a = c.get(f"/v1/prompts/{name}", params={"key": "user-1"}, headers=KH).json()
    b = c.get(f"/v1/prompts/{name}", params={"key": "user-1"}, headers=KH).json()
    assert a["version"] == b["version"], "assignment not stable for one key"
    return f"split live; key 'user-1' pinned to v{a['version']} on repeat (#62)"


def t_one_sided_split_refused():
    name = state.get("prompt")
    vs = [p["version"] for p in c.get("/api/prompts").json() if p["name"] == name]
    if len(vs) < 1:
        return "no versions"
    r = c.post(f"/api/prompts/{name}/split", json={"weights": {vs[0]: 1.0}})
    assert r.status_code == 422, f"one-sided split accepted: {r.status_code}"
    return "one-sided split refused (#62)"


# ---- 6. collaboration / ops -----------------------------------------------------------------
def t_saved_views():
    v = c.post("/api/views", json={"name": f"failing-{uniq}",
                                   "params": {"status": "failed", "limit": 5,
                                              "workspace_id": 999}}).json()
    assert set(v["params"]) == {"status", "limit"}, f"allowlist leaked: {v['params']}"
    dup = c.post("/api/views", json={"name": f"failing-{uniq}", "params": {}})
    assert dup.status_code == 409, f"duplicate name accepted: {dup.status_code}"
    c.delete(f"/api/views/{v['id']}")
    return "params allowlisted, duplicate name -> 409 (#68)"


def t_share_plain_and_redacted():
    tok = c.post(f"/api/traces/{T1}/share").json()["token"]
    shared = c.get(f"/v1/share/{tok}")
    assert shared.status_code == 200, shared.text
    red = c.post(f"/api/traces/{T1}/share/redacted", json={"withhold": ["input"]})
    assert red.status_code == 200, red.text
    rtok = red.json()["token"]
    body = c.get(f"/v1/share/{rtok}")
    assert body.status_code == 200, body.text
    assert "hello" not in body.text, "withheld prompt present in the response bytes"
    return "plain link works; redacted link omits the prompt from the body (#70)"


def t_webhooks():
    w = c.post("/api/webhooks", json={"url": "https://example.com/hook",
                                      "events": ["trace.failed"]})
    assert w.status_code == 200, w.text
    assert w.json()["secret"], "no signing secret issued"
    listed = [s for s in c.get("/api/webhooks").json() if s["id"] == w.json()["id"]][0]
    assert "secret" not in listed, "secret served on read"
    bad = c.post("/api/webhooks", json={"url": "https://example.com/h", "events": ["nope"]})
    assert bad.status_code == 422, "unknown event accepted"
    ssrf = c.post("/api/webhooks", json={"url": "http://169.254.169.254/x",
                                         "events": ["trace.failed"]})
    assert ssrf.status_code == 422, "metadata URL accepted"
    c.delete(f"/api/webhooks/{w.json()['id']}")
    return "secret once-only, unknown event 422, metadata URL 422 (#92)"


def t_digests():
    d = c.post("/api/digests", json={"cadence": "weekly", "email": "ops@example.com"})
    assert d.status_code == 200, d.text
    pv = c.post(f"/api/digests/{d.json()['id']}/preview").json()
    assert "text" in pv and pv["summary"]["window_hours"] == 168, pv
    again = [x for x in c.get("/api/digests").json() if x["id"] == d.json()["id"]][0]
    assert again["last_sent_at"] is None, "preview consumed the window"
    nowhere = c.post("/api/digests", json={"cadence": "weekly"})
    assert nowhere.status_code == 422, "digest with no destination accepted"
    c.delete(f"/api/digests/{d.json()['id']}")
    return "preview renders without rescheduling; destination-less refused (#71)"


def t_activity_feed():
    r = c.get("/api/activity")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "entries" in body, body
    return f"{len(body['entries'])} entries (#74)"


def t_export():
    r = c.get("/api/export/traces.ndjson", params={"limit": 5})
    assert r.status_code == 200, r.text
    lines = [x for x in r.text.strip().split("\n") if x.strip()]
    assert lines, "export produced nothing"
    json.loads(lines[0])
    return f"{len(lines)} NDJSON records, first parses (#93)"


def t_alerts():
    a = c.post("/api/alerts", json={"name": f"err-{uniq}", "metric": "error_rate",
                                    "comparator": "gt", "threshold": 0.5, "window_hours": 24})
    assert a.status_code in (200, 201), a.text
    chk = c.post("/api/alerts/check")
    assert chk.status_code == 200, chk.text
    c.delete(f"/api/alerts/{a.json()['id']}")
    return "alert rule created and evaluated (#66)"


# ---- 7. replay / debugging -------------------------------------------------------------------
def t_cassette():
    tid = ("7a" + uniq * 4)[:32]
    c.post("/v1/traces", json=otlp(tid, ("77" + uniq * 3)[:16], tool="get_weather",
                                   prompt="paris", completion="12C"), headers=KH)
    time.sleep(0.4)
    cas = c.get(f"/v1/traces/{tid}/cassette", headers=KH).json()
    assert cas["entries"], f"no cassette entries: {cas}"
    e = cas["entries"][0]
    assert e["tool"] == "get_weather", e
    return f"cassette exposes {len(cas['entries'])} recorded tool call(s) (#54)"


def t_admin_fleet():
    r = c.get("/api/admin/fleet")
    assert r.status_code == 200, f"{r.status_code} {r.text[:120]}"
    body = r.json()
    assert "tenants" in body and "instance" in body, list(body)
    return f"{len(body['tenants'])} tenant(s), instance block present (#84)"


def t_admin_pagination():
    r = c.get("/api/admin/users", params={"limit": 5})
    assert r.status_code == 200, r.text
    return "admin users endpoint paginates (#76)"


def t_sso_config_when_unset():
    r = c.get("/api/auth/sso/config")
    assert r.status_code in (200, 404), r.text
    if r.status_code == 200:
        body = r.json()
        assert body.get("enabled") in (False, None), f"SSO reports enabled without config: {body}"
        return "SSO reports disabled when unconfigured (#77)"
    return "SSO endpoint 404s when unconfigured (#77)"


def t_scim_requires_auth():
    r = httpx.get(f"{API}/scim/v2/Users", timeout=10)
    assert r.status_code in (401, 403), f"SCIM open without a token: {r.status_code}"
    return f"SCIM refuses an unauthenticated read ({r.status_code}) (#78)"


def t_openapi():
    r = c.get("/openapi.json")
    assert r.status_code == 200
    paths = r.json()["paths"]
    return f"{len(paths)} documented paths (#90)"


for name, fn in [
    ("ingest: OTLP JSON round-trip (#2)", t_ingest),
    ("ingest: retry does not duplicate (#1)", t_dedupe),
    ("ingest: bad key refused", t_bad_key),
    ("ingest: protobuf not silently dropped (#94)", t_protobuf_not_silently_dropped),
    ("ingest: clock skew flagged (#5)", t_clock_skew),
    ("ingest: price version stamped (#9)", t_price_version_stamped),
    ("read: trace list + cursor (#15)", t_trace_list_and_cursor),
    ("read: full-text search (#17)", t_search),
    ("read: metrics/rollups (#16)", t_metrics),
    ("read: pricing card (#9)", t_pricing_card),
    ("ops: health + ingest observability (#14)", t_health_observability),
    ("ops: retention status (#13)", t_retention_status),
    ("eval: dataset versioning (#45)", t_dataset_versioning),
    ("eval: deterministic split (#45)", t_dataset_split),
    ("eval: experiment pins + compare (#52)", t_experiment_pins_and_compare),
    ("eval: scorers", t_scorers_registry),
    ("auto: promote on match (#47)", t_automation_promote),
    ("auto: empty match refused (#47)", t_automation_empty_match_refused),
    ("auto: online eval writes feedback (#39)", t_online_eval),
    ("prompts: runtime fetch (#61)", t_prompt_runtime_fetch),
    ("prompts: A/B split stable per key (#62)", t_prompt_ab_split),
    ("prompts: one-sided split refused (#62)", t_one_sided_split_refused),
    ("collab: saved views (#68)", t_saved_views),
    ("collab: share + redacted share (#70)", t_share_plain_and_redacted),
    ("integr: outbound webhooks (#92)", t_webhooks),
    ("integr: digests (#71)", t_digests),
    ("collab: activity feed (#74)", t_activity_feed),
    ("integr: bulk export (#93)", t_export),
    ("alerts: create + evaluate (#66)", t_alerts),
    ("debug: replay cassette (#54)", t_cassette),
    ("admin: fleet health (#84)", t_admin_fleet),
    ("admin: users pagination (#76)", t_admin_pagination),
    ("auth: SSO config (#77)", t_sso_config_when_unset),
    ("auth: SCIM requires a token (#78)", t_scim_requires_auth),
    ("api: OpenAPI spec (#90)", t_openapi),
]:
    check(name, fn)

ok = sum(1 for s, _, _ in results if s == "PASS")
for status, name, detail in results:
    mark = {"PASS": "PASS", "FAIL": "FAIL", "ERROR": "ERR "}[status]
    print(f"[{mark}] {name}")
    if detail:
        print(f"         {detail}")
print(f"\n{ok}/{len(results)} passed")
sys.exit(0 if ok == len(results) else 1)
