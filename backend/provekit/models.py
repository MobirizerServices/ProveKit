"""ProveKit data model: accounts, projects (workspaces), project keys, and captured
runs (the spans of an agent trace)."""
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
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
