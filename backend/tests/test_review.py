"""The human review queue (#40).

The ordering is the feature. A queue that returned newest-first would be a trace list with extra
steps; this one has to put the runs that *teach* something at the top, and it must never re-queue
a run somebody already ruled on.
"""
import uuid

from fastapi.testclient import TestClient

from provekit.database import SessionLocal
from provekit.main import app
from provekit.models import Feedback, ProviderConnection, Run


def _client():
    return TestClient(app, base_url="https://testserver")


def _ws_id(c) -> int:
    """The workspace these portal calls land in."""
    conn = c.post("/api/connections",
                  json={"provider": "openai", "label": f"rv{uuid.uuid4().hex[:6]}",
                        "key": "sk-test-0000"}).json()
    db = SessionLocal()
    try:
        return db.get(ProviderConnection, conn["id"]).workspace_id
    finally:
        db.close()


def _root(ws_id: int, trace: str, *, status: str = "completed", label: str = "run") -> None:
    db = SessionLocal()
    db.add(Run(workspace_id=ws_id, trace_id=trace, span_id=trace[:16], parent_span_id="",
               type="agent", label=label, status=status, duration_ms=100))
    db.commit(); db.close()


def _fb(ws_id: int, trace: str, *, source: str, score: float) -> None:
    db = SessionLocal()
    db.add(Feedback(workspace_id=ws_id, trace_id=trace, name="j" if source != "human" else "review",
                    score=score, source=source))
    db.commit(); db.close()


def test_queue_ranks_judge_scored_first_and_hides_what_is_already_labelled():
    c = _client()
    ws = _ws_id(c)
    tag = uuid.uuid4().hex[:6]
    plain, failed, judged, labelled = (f"{tag}plain".ljust(32, "0"), f"{tag}fail".ljust(32, "0"),
                                       f"{tag}judge".ljust(32, "0"), f"{tag}done".ljust(32, "0"))
    _root(ws, plain)
    _root(ws, failed, status="failed")
    _root(ws, judged)
    _root(ws, labelled)
    _fb(ws, judged, source="eval", score=0.2)          # a judge ruled, no human has
    _fb(ws, labelled, source="human", score=1.0)       # already reviewed

    body = c.get("/api/review/queue", params={"limit": 200}).json()
    ids = [i["trace_id"] for i in body["items"]]

    assert labelled not in ids, "a run with a human verdict must not be re-queued"
    assert judged in ids and failed in ids and plain in ids
    # Judge-scored outranks a bare failure, which outranks an ordinary unreviewed run.
    assert ids.index(judged) < ids.index(failed) < ids.index(plain)

    row = next(i for i in body["items"] if i["trace_id"] == judged)
    assert row["judge"] == {"name": "j", "score": 0.2, "verdict": "fail"}
    assert "judge scored it" in row["reason"]


def test_summary_counts_the_pairs_calibration_is_waiting_for():
    c = _client()
    ws = _ws_id(c)
    tag = uuid.uuid4().hex[:6]
    both, judge_only = f"{tag}both".ljust(32, "0"), f"{tag}jonly".ljust(32, "0")
    _root(ws, both); _root(ws, judge_only)
    _fb(ws, both, source="eval", score=0.9)
    _fb(ws, both, source="human", score=1.0)           # a complete pair
    _fb(ws, judge_only, source="eval", score=0.4)      # half a pair

    s = c.get("/api/review/queue").json()["summary"]
    assert s["paired"] >= 1
    assert s["judge_scored"] >= 2 and s["human_labelled"] >= 1
    # The shortfall is stated as a number rather than implied by an empty panel.
    assert s["pairs_needed"] == max(0, s["min_pairs"] - s["paired"])
    assert s["scan_limit"] >= s["scanned"]


def test_labelling_through_the_normal_feedback_route_clears_the_item():
    """The queue must not own a second write path — a label is ordinary human feedback."""
    c = _client()
    ws = _ws_id(c)
    trace = f"{uuid.uuid4().hex[:6]}lbl".ljust(32, "0")
    _root(ws, trace)
    assert trace in [i["trace_id"] for i in c.get("/api/review/queue", params={"limit": 200}).json()["items"]]

    r = c.post(f"/api/traces/{trace}/feedback",
               json={"name": "review", "score": 1, "value": "pass", "source": "human"})
    assert r.status_code == 200, r.text
    after = [i["trace_id"] for i in c.get("/api/review/queue", params={"limit": 200}).json()["items"]]
    assert trace not in after, "labelling it should take it out of the queue"
