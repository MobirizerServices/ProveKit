"""Indexed full-text search over span content."""
import pytest
from fastapi.testclient import TestClient

from provekit.database import SessionLocal
from provekit.main import app
from provekit.models import Run, Workspace
from provekit.services import search

from conftest import ingest_workspace_id


def _span(i, prompt="", completion="", tool=None):
    attrs = [{"key": "gen_ai.request.model", "value": {"stringValue": "gpt-4o"}}]
    if prompt:
        attrs.append({"key": "gen_ai.prompt", "value": {"stringValue": prompt}})
    if completion:
        attrs.append({"key": "gen_ai.completion", "value": {"stringValue": completion}})
    if tool:
        attrs.append({"key": "gen_ai.tool.name", "value": {"stringValue": tool}})
    return {"name": "chat", "traceId": f"{i:032x}", "spanId": f"{i:016x}",
            "startTimeUnixNano": "1000000000", "endTimeUnixNano": "1500000000",
            "status": {"code": 1}, "attributes": attrs}


def _otlp(*spans):
    return {"resourceSpans": [{"scopeSpans": [{"spans": list(spans)}]}]}


# -- what goes into the column ---------------------------------------------------------------

def test_text_is_built_from_values_not_json_keys():
    """Searching the raw JSON blob matched structure — a search for "model" returned every
    LLM span in the project, because the word is a key in every one of them."""
    row = {"label": "chat gpt-4o",
           "request": {"type": "llm", "model": "gpt-4o", "input": "how do I cancel"},
           "result": {"text": "open settings", "meta": {"usage": {"input_tokens": 5}}}}
    txt = search.text_for(row)
    assert "how do I cancel" in txt and "open settings" in txt
    assert "input_tokens" not in txt          # a key, not something anyone said
    assert "type" not in txt


def test_text_is_capped():
    row = {"label": "x", "request": {"input": "a" * 50000}, "result": {}}
    assert len(search.text_for(row)) <= 16000


def test_nested_and_list_payloads_are_flattened():
    row = {"label": "", "request": {"input": [{"role": "user", "content": "find the invoice"}]},
           "result": {"text": None}}
    assert "find the invoice" in search.text_for(row)


def test_error_text_is_searchable():
    row = {"label": "call", "request": {}, "result": {}, "error": "ConnectionError: refused"}
    assert "ConnectionError" in search.text_for(row)


# -- the property that matters ---------------------------------------------------------------

def test_search_column_is_built_after_redaction():
    """The one way this feature could be actively harmful.

    redact.scrub_run masks PII before storage. Deriving the search column from the *un*masked
    row would copy exactly those values into a new column and then index them for fast
    retrieval — making PII easier to find while redaction reported itself as on.
    """
    ws_id = ingest_workspace_id()
    db = SessionLocal()
    ws = db.query(Workspace).filter(Workspace.id == ws_id).first()
    prev = ws.redact_pii
    ws.redact_pii = True
    db.commit()
    db.close()
    try:
        with TestClient(app) as client:
            client.post("/v1/traces", json=_otlp(
                _span(0x5151, prompt="email me at alice@example.com about it")))
        db = SessionLocal()
        row = db.query(Run).filter(Run.trace_id == f"{0x5151:032x}").first()
        stored = row.search_text or ""
        db.close()
        assert "alice@example.com" not in stored      # never indexed
        assert "about it" in stored                   # ...but the rest is still searchable
    finally:
        db = SessionLocal()
        db.query(Workspace).filter(Workspace.id == ws_id).first().redact_pii = prev
        db.commit()
        db.close()


# -- end to end ------------------------------------------------------------------------------

def test_search_finds_a_trace_by_what_it_said():
    with TestClient(app) as client:
        client.post("/v1/traces", json=_otlp(
            _span(0x6001, prompt="pelican crossing rules", completion="wait for the beep")))
        hits = client.get("/api/traces", params={"q": "pelican crossing"}).json()
        assert any(t["trace_id"] == f"{0x6001:032x}" for t in hits)
        # and a term nobody said finds nothing
        assert not any(t["trace_id"] == f"{0x6001:032x}"
                       for t in client.get("/api/traces", params={"q": "zzzznotpresent"}).json())


def test_search_matches_the_output_too():
    with TestClient(app) as client:
        client.post("/v1/traces", json=_otlp(
            _span(0x6002, prompt="q", completion="the capital is Reykjavik")))
        hits = client.get("/api/traces", params={"q": "Reykjavik"}).json()
    assert any(t["trace_id"] == f"{0x6002:032x}" for t in hits)


def test_rows_written_before_the_column_existed_stay_findable():
    """A migration that leaves history NULL must not make history invisible — that would look
    exactly like data loss."""
    ws_id = ingest_workspace_id()
    db = SessionLocal()
    db.add(Run(workspace_id=ws_id, type="llm", label="legacy-span",
               trace_id=f"{0x6003:032x}", span_id=f"{0x6003:016x}", parent_span_id="",
               request={"input": "antediluvian phrasing"}, result={}, search_text=None))
    db.commit()
    db.close()
    with TestClient(app) as client:
        hits = client.get("/api/traces", params={"q": "antediluvian"}).json()
    assert any(t["trace_id"] == f"{0x6003:032x}" for t in hits)


def test_dialect_detection_matches_the_test_database():
    db = SessionLocal()
    try:
        assert search.is_postgres(db) is False       # the suite runs on SQLite
    finally:
        db.close()


# -- the Postgres path, which SQLite tests can never exercise --------------------------------

def test_postgres_clause_matches_the_indexed_expression():
    """The GIN index is on `to_tsvector('english', coalesce(search_text, ''))`. If the query
    doesn't produce that expression *character for character*, Postgres silently ignores the
    index and sequentially scans — the exact failure this item exists to remove, and one no
    SQLite test can catch.
    """
    from sqlalchemy.dialects import postgresql

    sql = str(search.postgres_clause("cancel order").compile(
        dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "to_tsvector('english', coalesce(runs.search_text, ''))" in sql
    assert "@@ plainto_tsquery('english', 'cancel order')" in sql
    # The migration builds exactly this expression; keep them in lockstep.
    from pathlib import Path
    mig = (Path(__file__).resolve().parents[1] / "provekit" / "migrations" / "versions"
           / "c5d6e7f8a9b0_search_text.py").read_text()
    assert "to_tsvector('english', coalesce(search_text, ''))" in mig


def test_legacy_fallback_is_scoped_to_unbackfilled_rows():
    """Without the NULL guard the expensive JSON cast would run on every row, and the index
    would buy nothing."""
    from sqlalchemy.dialects import postgresql

    sql = str(search.postgres_clause("x").compile(
        dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "runs.search_text IS NULL AND" in sql
