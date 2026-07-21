"""ProveKit data model: accounts, projects (workspaces), project keys, and captured
runs (the spans of an agent trace)."""
from datetime import datetime, timezone

from sqlalchemy import (DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text,
                        UniqueConstraint, text)
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


def _ws_fk() -> Mapped[int]:
    """Workspace FK shared by every tenant-scoped table (indexed for per-workspace queries)."""
    return mapped_column(ForeignKey("workspaces.id"), index=True, nullable=True)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(dt: datetime | None) -> str | None:
    """Serialize a stored timestamp as ISO-8601 with an explicit UTC offset. Timestamps
    are written in UTC (_now), but SQLite hands them back naive — without the offset the
    browser would parse them as local time."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


class User(Base):
    """An account. password_hash is null for OAuth-only users."""
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    name: Mapped[str] = mapped_column(String(160), default="")
    password_hash: Mapped[str] = mapped_column(String(255), default="")
    auth_provider: Mapped[str] = mapped_column(String(32), default="password")  # password | github | local
    email_verified: Mapped[bool] = mapped_column(default=False)
    is_superuser: Mapped[bool] = mapped_column(default=False)   # platform operator (admin console)
    # Bumped on password reset to revoke every previously-issued token (sessions + the
    # just-used reset link): tokens embed the version and are rejected once it moves on.
    token_version: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Workspace(Base):
    """A project — a tenant boundary. Every user gets a default one; teams share one later."""
    __tablename__ = "workspaces"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), default="My project")
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    # Bearer token for unattended OTLP trace ingest (exporters can't send cookies).
    ingest_key_hash: Mapped[str] = mapped_column(String(128), default="", index=True)
    # Per-project overrides (0 / False → fall back to the global config default).
    retention: Mapped[int] = mapped_column(Integer, default=0)      # keep last N spans; 0 = global
    redact_pii: Mapped[bool] = mapped_column(default=False)         # mask PII on ingest
    # Optional endpoint ProveKit POSTs a fork override to for exact (webhook-mode) replay — the
    # customer re-runs their real agent and returns OTLP. Empty → reconstructed replay only.
    replay_url: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class WorkspaceMember(Base):
    __tablename__ = "workspace_members"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(16), default="member")  # owner | member
    __table_args__ = (UniqueConstraint("workspace_id", "user_id", name="uq_member"),)


class ApiKey(Base):
    """A named, revocable project key (a pk_ bearer key) for shipping traces.

    Unlike the single per-workspace `ingest_key_hash`, a project can hold many of these —
    one per app or environment — each revocable on its own. Only the SHA-256 hash is
    stored; the plaintext (`pk_…`) is shown exactly once, at creation."""
    __tablename__ = "api_keys"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = _ws_fk()
    name: Mapped[str] = mapped_column(String(120), default="")
    prefix: Mapped[str] = mapped_column(String(16), default="")   # e.g. "pk_A1b2C3d4" for display
    key_hash: Mapped[str] = mapped_column(String(128), index=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revoked: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Run(Base):
    """One captured span. A trace's spans share a trace_id; the tree is rebuilt from
    span_id / parent_span_id."""
    __tablename__ = "runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = _ws_fk()
    type: Mapped[str] = mapped_column(String(16))               # agent | llm | tool | step
    label: Mapped[str] = mapped_column(String(200), default="")
    request: Mapped[dict] = mapped_column(JSON, default=dict)   # {type, provider, model, operation, input}
    result: Mapped[dict] = mapped_column(JSON, default=dict)    # {text, output, meta}
    status: Mapped[str] = mapped_column(String(16), default="completed")
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default="")
    # OTel span identity — lets the portal rebuild spans of one run into a nested tree.
    trace_id: Mapped[str] = mapped_column(String(32), default="", index=True)
    span_id: Mapped[str] = mapped_column(String(16), default="")
    parent_span_id: Mapped[str] = mapped_column(String(16), default="")
    # Groups multi-turn runs (a conversation/thread) so the portal can show them together.
    # Captured from a span's session.id / gen_ai.conversation.id attribute when present.
    session_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    # OTLP exporters retry on 5xx by replaying the whole batch, so without this a retry
    # silently doubles span counts, tokens and cost. Keyed on trace_id too because OTel only
    # guarantees a span id is unique *within a trace* — two traces may reuse one, and dropping
    # the second would be worse data loss than the duplicate this prevents. Partial
    # (span_id != '') because rows created outside OTLP ingest — replays, evals — have none.
    __table_args__ = (
        Index("uq_run_span", "workspace_id", "trace_id", "span_id", unique=True,
              sqlite_where=text("span_id != ''"), postgresql_where=text("span_id != ''")),
    )


class Dataset(Base):
    """A named collection of examples ({input, expected}) — the material offline evaluations
    run against. Curated by hand or captured from production traces."""
    __tablename__ = "datasets"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = _ws_fk()
    name: Mapped[str] = mapped_column(String(160), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class DatasetItem(Base):
    """One example in a dataset: an input, an optional expected output, and free-form meta."""
    __tablename__ = "dataset_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = _ws_fk()
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id"), index=True)
    input: Mapped[str] = mapped_column(Text, default="")
    expected: Mapped[str] = mapped_column(Text, default="")
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Experiment(Base):
    """One offline-evaluation run: a target executed over a dataset, scored. Compare
    experiments on the same dataset to catch regressions before they ship."""
    __tablename__ = "experiments"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = _ws_fk()
    name: Mapped[str] = mapped_column(String(160), default="")
    dataset_id: Mapped[int | None] = mapped_column(ForeignKey("datasets.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class ExperimentResult(Base):
    """One scored example within an experiment: the target's output for an item, plus the
    per-scorer scores ({scorer_name: value})."""
    __tablename__ = "experiment_results"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = _ws_fk()
    experiment_id: Mapped[int] = mapped_column(ForeignKey("experiments.id"), index=True)
    item_id: Mapped[int | None] = mapped_column(nullable=True)
    input: Mapped[str] = mapped_column(Text, default="")
    output: Mapped[str] = mapped_column(Text, default="")
    expected: Mapped[str] = mapped_column(Text, default="")
    scores: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Alert(Base):
    """A threshold rule over the dashboard metrics. When breached (and outside its cooldown)
    it notifies by email. Evaluated on demand via POST /api/alerts/check (or a cron)."""
    __tablename__ = "alerts"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = _ws_fk()
    name: Mapped[str] = mapped_column(String(160), default="")
    metric: Mapped[str] = mapped_column(String(32))   # error_rate | latency_p95_ms | trace_count | ...
    comparator: Mapped[str] = mapped_column(String(4), default="gt")  # gt | lt
    threshold: Mapped[float] = mapped_column(Float, default=0.0)
    window_hours: Mapped[int] = mapped_column(Integer, default=24)
    email: Mapped[str] = mapped_column(String(255), default="")
    enabled: Mapped[bool] = mapped_column(default=True)
    last_triggered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class ProviderConnection(Base):
    """A per-project model-provider credential used to *re-run* captured LLM calls in the
    playground / replay harness. The key is stored sealed (Fernet); only a masked hint is ever
    returned to the client. `base_url` supports OpenAI-compatible gateways (Azure/OpenRouter/local)."""
    __tablename__ = "provider_connections"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = _ws_fk()
    provider: Mapped[str] = mapped_column(String(24))          # openai | anthropic | openai_compatible | mock
    label: Mapped[str] = mapped_column(String(120), default="")
    key_sealed: Mapped[str] = mapped_column(Text, default="")  # Fernet-encrypted; never returned
    key_hint: Mapped[str] = mapped_column(String(24), default="")   # e.g. "…a1b2" for display
    base_url: Mapped[str] = mapped_column(String(300), default="")  # for openai_compatible
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class ReplayRun(Base):
    """Provenance for a replay: which trace/span it forked from, the overrides applied, and the
    new trace branch it produced (stored as normal Run rows tagged meta.replay_of)."""
    __tablename__ = "replay_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = _ws_fk()
    origin_trace_id: Mapped[str] = mapped_column(String(32), default="", index=True)
    fork_span_id: Mapped[str] = mapped_column(String(16), default="")
    overrides: Mapped[dict] = mapped_column(JSON, default=dict)
    mode: Mapped[str] = mapped_column(String(16), default="reconstructed")  # reconstructed | webhook
    new_trace_id: Mapped[str] = mapped_column(String(32), default="", index=True)
    status: Mapped[str] = mapped_column(String(16), default="completed")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Prompt(Base):
    """A saved prompt version from the playground — the edited messages/model/params, kept under
    a name so it can be restored, compared, or promoted to code. Newest version wins on restore."""
    __tablename__ = "prompts"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = _ws_fk()
    name: Mapped[str] = mapped_column(String(160), default="")
    version: Mapped[int] = mapped_column(Integer, default=1)
    model: Mapped[str] = mapped_column(String(120), default="")
    messages: Mapped[list] = mapped_column(JSON, default=list)
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class SpanNote(Base):
    """A teammate's note pinned to one span of a trace — inline collaboration on a specific step."""
    __tablename__ = "span_notes"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = _ws_fk()
    trace_id: Mapped[str] = mapped_column(String(32), index=True)
    span_id: Mapped[str] = mapped_column(String(16), default="")
    author: Mapped[str] = mapped_column(String(120), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Feedback(Base):
    """A score or annotation attached to a whole trace — a human thumbs-up, an LLM-judge
    score, or an offline-eval result. Many per trace; the portal shows them on the run."""
    __tablename__ = "feedback"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = _ws_fk()
    trace_id: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(120), default="")     # e.g. "correctness", "thumbs"
    score: Mapped[float | None] = mapped_column(Float, nullable=True)   # numeric score, if any
    value: Mapped[str] = mapped_column(String(200), default="")    # categorical/string value, if any
    comment: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(16), default="human")  # human | sdk | eval
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
