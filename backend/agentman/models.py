"""AgentMan data model. Everything the console persists: connections (providers),
collections + saved requests, environments (variables), and run history."""
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, TypeDecorator, UniqueConstraint
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


class SealedJSON(TypeDecorator):
    """JSON column whose secret fields (api_key, auth headers) are encrypted at rest.
    Application code always sees plaintext; the database file never does."""
    impl = JSON
    cache_ok = True

    def process_bind_param(self, value, dialect):
        from .services.sealing import seal_config
        return seal_config(value) if isinstance(value, dict) else value

    def process_result_value(self, value, dialect):
        from .services.sealing import unseal_config
        return unseal_config(value) if isinstance(value, dict) else value


class User(Base):
    """An account. password_hash is null for OAuth-only users."""
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    name: Mapped[str] = mapped_column(String(160), default="")
    password_hash: Mapped[str] = mapped_column(String(255), default="")
    auth_provider: Mapped[str] = mapped_column(String(32), default="password")  # password | github | local
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Workspace(Base):
    """A tenant boundary. Every user gets a default workspace; teams share one later."""
    __tablename__ = "workspaces"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), default="My workspace")
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class WorkspaceMember(Base):
    __tablename__ = "workspace_members"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(16), default="member")  # owner | member
    __table_args__ = (UniqueConstraint("workspace_id", "user_id", name="uq_member"),)


class Connection(Base):
    """A provider you can run against. kind = llm | mcp | agent."""
    __tablename__ = "connections"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = _ws_fk()
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(16))  # llm | mcp | agent
    # config shape by kind:
    #   llm   -> {provider: openai|anthropic|compatible, base_url, api_key, models: [str]}
    #   mcp   -> {url}
    #   agent -> {base_url, headers: {}}
    config: Mapped[dict] = mapped_column(SealedJSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Collection(Base):
    __tablename__ = "collections"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = _ws_fk()
    name: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Request(Base):
    """A saved request. type = prompt | tool | agent. payload holds the type-specific body."""
    __tablename__ = "requests"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = _ws_fk()
    collection_id: Mapped[int | None] = mapped_column(ForeignKey("collections.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(160))
    type: Mapped[str] = mapped_column(String(16))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class Environment(Base):
    __tablename__ = "environments"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = _ws_fk()
    name: Mapped[str] = mapped_column(String(120))
    variables: Mapped[dict] = mapped_column(JSON, default=dict)
    is_active: Mapped[bool] = mapped_column(default=False)


class Prompt(Base):
    """A managed, reusable prompt (the generic Prompt Registry)."""
    __tablename__ = "prompts"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = _ws_fk()
    key: Mapped[str] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    content: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)
    __table_args__ = (UniqueConstraint("workspace_id", "key", name="uq_prompt_key"),)


class Flow(Base):
    """A visual agent workflow: a graph of nodes + edges executed by the flow engine."""
    __tablename__ = "flows"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = _ws_fk()
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    nodes: Mapped[list] = mapped_column(JSON, default=list)
    edges: Mapped[list] = mapped_column(JSON, default=list)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class Dataset(Base):
    """A reusable, named set of input rows — run any request over it. rows =
    [{name, variables}]. Decoupled from requests, like a shared data file."""
    __tablename__ = "datasets"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = _ws_fk()
    name: Mapped[str] = mapped_column(String(160))
    rows: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Run(Base):
    """A single execution + its result (for history/replay)."""
    __tablename__ = "runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = _ws_fk()
    type: Mapped[str] = mapped_column(String(16))
    label: Mapped[str] = mapped_column(String(200), default="")
    request: Mapped[dict] = mapped_column(JSON, default=dict)   # the sent request
    result: Mapped[dict] = mapped_column(JSON, default=dict)    # {output, meta, events?}
    status: Mapped[str] = mapped_column(String(16), default="completed")
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
