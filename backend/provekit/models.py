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
    # Flattened label + input/output text for search, built at write time by
    # services/search.text_for — from the row *after* redaction, so this never becomes a
    # fast-to-query copy of the PII redaction just removed. Nullable: rows written before
    # this column existed fall back to the old JSON scan.
    search_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    # OTLP exporters retry on 5xx by replaying the whole batch, so without this a retry
    # silently doubles span counts, tokens and cost. Keyed on trace_id too because OTel only
    # guarantees a span id is unique *within a trace* — two traces may reuse one, and dropping
    # the second would be worse data loss than the duplicate this prevents. Partial
    # (span_id != '') because rows created outside OTLP ingest — replays, evals — have none.
    # Composites for the hot reads. workspace_id was already indexed alone, but it is the least
    # selective column here — leading with it and carrying the discriminating column is what
    # keeps a busy project's dashboard off a full scan. See migration f2a3b4c5d6e7 for the
    # query shape behind each one.
    __table_args__ = (
        Index("uq_run_span", "workspace_id", "trace_id", "span_id", unique=True,
              sqlite_where=text("span_id != ''"), postgresql_where=text("span_id != ''")),
        Index("ix_runs_ws_root", "workspace_id", "parent_span_id", "id"),
        Index("ix_runs_ws_created", "workspace_id", "created_at"),
        Index("ix_runs_ws_status_created", "workspace_id", "status", "created_at"),
        Index("ix_runs_ws_session", "workspace_id", "session_id"),
    )


class Dataset(Base):
    """A named collection of examples ({input, expected}) — the material offline evaluations
    run against. Curated by hand or captured from production traces."""
    __tablename__ = "datasets"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = _ws_fk()
    name: Mapped[str] = mapped_column(String(160), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    # Bumped on every content change. An experiment records the version it ran against, so
    # "these two runs are comparable" becomes a fact rather than an assumption — a dataset
    # edited between two runs silently invalidated the comparison, and nothing said so.
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class DatasetItem(Base):
    """One example in a dataset: an input, an optional expected output, and free-form meta."""
    __tablename__ = "dataset_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = _ws_fk()
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id"), index=True)
    input: Mapped[str] = mapped_column(Text, default="")
    expected: Mapped[str] = mapped_column(Text, default="")
    # A multi-turn example (#44): [{"input": ..., "expected": ...}, …]. Empty for the ordinary
    # single-turn row, so every existing dataset keeps its exact meaning — a conversation is an
    # additional shape, not a reinterpretation of the old one.
    turns: Mapped[list] = mapped_column(JSON, default=list)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    # "" (unassigned) | train | test. Empty by default so existing datasets keep behaving as
    # one undivided set — silently reassigning them would change what every saved experiment
    # was measured over.
    split: Mapped[str] = mapped_column(String(16), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Experiment(Base):
    """One offline-evaluation run: a target executed over a dataset, scored. Compare
    experiments on the same dataset to catch regressions before they ship."""
    __tablename__ = "experiments"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = _ws_fk()
    name: Mapped[str] = mapped_column(String(160), default="")
    dataset_id: Mapped[int | None] = mapped_column(ForeignKey("datasets.id"), nullable=True, index=True)
    # What this run was actually measured against and with. Without it a result is a number
    # with no provenance: months later nobody can say which dataset contents, which model, or
    # which scorers produced it, so it can be quoted but never re-derived or trusted.
    dataset_version: Mapped[int] = mapped_column(Integer, default=0)
    # Content hash of the items as they were at run time. The version counter says "something
    # changed"; the fingerprint proves whether two runs saw identical data even across
    # restores, re-imports, or a counter that was reset.
    dataset_fingerprint: Mapped[str] = mapped_column(String(64), default="")
    config: Mapped[dict] = mapped_column(JSON, default=dict)   # model, params, scorers, split
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
    it notifies by email and/or a chat webhook. Evaluated via POST /api/alerts/check (or a
    cron)."""
    __tablename__ = "alerts"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = _ws_fk()
    name: Mapped[str] = mapped_column(String(160), default="")
    metric: Mapped[str] = mapped_column(String(32))   # error_rate | latency_p95_ms | trace_count | ...
    comparator: Mapped[str] = mapped_column(String(4), default="gt")  # gt | lt
    threshold: Mapped[float] = mapped_column(Float, default=0.0)
    window_hours: Mapped[int] = mapped_column(Integer, default=24)
    email: Mapped[str] = mapped_column(String(255), default="")
    webhook_url: Mapped[str] = mapped_column(String(500), default="")   # Slack/Discord incoming
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
    # A moving pointer ("production", "staging") so an app fetches by label rather than pinning
    # a version number — which is what lets a prompt change without a deploy (#61).
    label: Mapped[str] = mapped_column(String(64), default="", index=True)
    # Share of traffic for a live A/B (#62). 0 = not serving. Two versions of one name each
    # carrying a weight is the whole experiment; anything else is a deploy.
    traffic: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class AuditLog(Base):
    """An append-only record of a privileged change: who did what, to what, when.

    Deliberately denormalised. `actor_email` and `target_label` are snapshots taken at write
    time rather than joins, because the point of an audit trail is to survive the thing it
    describes — deleting a user or a project must not erase the evidence that it happened.

    `workspace_id` is nullable: platform-level events (granting superuser) belong to no project.
    """
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int | None] = mapped_column(
        ForeignKey("workspaces.id"), nullable=True, index=True)
    actor_user_id: Mapped[int | None] = mapped_column(nullable=True)
    actor_email: Mapped[str] = mapped_column(String(255), default="")
    action: Mapped[str] = mapped_column(String(64), index=True)   # e.g. superuser.grant
    target_type: Mapped[str] = mapped_column(String(32), default="")   # user | project | key
    target_id: Mapped[str] = mapped_column(String(64), default="")
    target_label: Mapped[str] = mapped_column(String(255), default="")
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    ip: Mapped[str] = mapped_column(String(45), default="")            # 45 = max IPv6 literal
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)


class MetricRollup(Base):
    """One hour of a project's dashboard numbers, pre-aggregated.

    The dashboard used to recompute everything from raw spans per request, capped — so a wide
    window was not just slow but silently truncated. A closed hour never changes, so it is
    folded once and read thereafter; only the open hour is still computed live.

    `latency_hist` is a bucketed histogram rather than stored percentiles, because percentiles
    don't merge: the p95 of a day is not the average of 24 hourly p95s. See services/rollups.py
    for the bucket layout.
    """
    __tablename__ = "metric_rollups"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = _ws_fk()
    bucket: Mapped[datetime] = mapped_column(DateTime, index=True)   # start of the hour, UTC
    trace_count: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    latency_hist: Mapped[list] = mapped_column(JSON, default=list)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    model_calls: Mapped[int] = mapped_column(Integer, default=0)     # usage-coverage denominator
    usage_spans: Mapped[int] = mapped_column(Integer, default=0)     # ...and its numerator
    fail_by_type: Mapped[dict] = mapped_column(JSON, default=dict)

    __table_args__ = (
        Index("uq_metric_rollup", "workspace_id", "bucket", unique=True),
    )


class ModelRollup(Base):
    """Per-model token totals for one hour. Separate from MetricRollup because model cardinality
    is unbounded — folding it into a JSON column would make the common read carry every model a
    project has ever called."""
    __tablename__ = "model_rollups"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = _ws_fk()
    bucket: Mapped[datetime] = mapped_column(DateTime, index=True)
    model: Mapped[str] = mapped_column(String(200), default="")
    calls: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    usage_spans: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (
        Index("uq_model_rollup", "workspace_id", "bucket", "model", unique=True),
    )


class SavedView(Base):
    """A named filter + time-window + search combination, shareable by URL.

    Filters were ephemeral: "our failing checkout traces" existed only as whatever someone
    had typed into the toolbar, so it could be described in chat but not handed over. The
    query lives in `params` as the same key/values the trace list already accepts, so a saved
    view is replayable through the normal read path rather than being a second query language
    that can drift away from the first.
    """
    __tablename__ = "saved_views"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = _ws_fk()
    name: Mapped[str] = mapped_column(String(160), default="")
    params: Mapped[dict] = mapped_column(JSON, default=dict)   # status, window_hours, q, …
    created_by: Mapped[str] = mapped_column(String(255), default="")   # email, for display
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    __table_args__ = (
        Index("uq_saved_view_name", "workspace_id", "name", unique=True),
    )


class WebhookSubscription(Base):
    """A customer endpoint to notify when something happens in their project.

    Alerts already push to a webhook (#66), but only for a breached alert rule. Everything else
    — a trace finished, an experiment finished — was only observable by polling, which means a
    customer integration either polls too often or finds out too late.

    Deliberately a subscription row rather than a column on the project: a team needs different
    destinations for different events (an experiment result to CI, a failure to on-call), and
    one URL per project forces them to build the fan-out themselves.
    """
    __tablename__ = "webhook_subscriptions"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = _ws_fk()
    url: Mapped[str] = mapped_column(String(500), default="")
    events: Mapped[list] = mapped_column(JSON, default=list)   # e.g. ["trace.failed"]
    # Signing secret: the receiver has no other way to know a POST is genuinely from ProveKit,
    # and an unauthenticated webhook endpoint is a way to inject fake events into their system.
    secret: Mapped[str] = mapped_column(String(64), default="")
    enabled: Mapped[bool] = mapped_column(default=True)
    # Consecutive failures. A dead endpoint that is retried forever becomes an outbound DoS the
    # customer is paying for, so delivery backs off and eventually stops.
    failures: Mapped[int] = mapped_column(Integer, default=0)
    last_status: Mapped[str] = mapped_column(String(120), default="")
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Digest(Base):
    """A recurring "here's what changed" summary for a project.

    Alerts fire on a threshold, which answers "is something broken right now". Nobody was
    answering the slower question — did quality drift this week, is spend climbing — and that
    one is only visible by comparing a window to the one before it. A dashboard shows it to
    whoever opens the dashboard; a digest shows it to a team that didn't.

    Destination reuses the alert webhook shape (`notify.payload_for` picks Slack/Discord/
    PagerDuty/Opsgenie by host) or an email address, so this adds a schedule rather than a
    second delivery stack.
    """
    __tablename__ = "digests"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = _ws_fk()
    cadence: Mapped[str] = mapped_column(String(16), default="weekly")   # daily | weekly
    webhook_url: Mapped[str] = mapped_column(String(500), default="")
    email: Mapped[str] = mapped_column(String(255), default="")
    enabled: Mapped[bool] = mapped_column(default=True)
    # When the last one actually went out. The scheduler is driven by this rather than by a
    # cron expression, so a restarted or briefly-down instance sends late instead of skipping
    # the window entirely — a digest nobody received is indistinguishable from nothing to
    # report, which is the failure that makes people stop trusting it.
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_status: Mapped[str] = mapped_column(String(160), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class AutomationRule(Base):
    """Route matching production traces somewhere useful.

    Evaluation was entirely offline: you curated a dataset by hand and ran experiments against
    it. Nothing connected what actually happened in production back to that loop, so the
    dataset drifted away from real traffic and the traces worth learning from were the ones
    nobody got round to copying across.

    A rule is a match plus an action. `promote` copies a matching trace into a dataset;
    `score` samples matching traces and scores them online (#39) — the eval loop that needs no
    ground truth, which is why it is the one worth having on live traffic.

    Runs on a background pass rather than on the ingest path. Ingest is the hottest write in
    the product and it now carries a durability spool; making it also evaluate every rule and
    call a judge model would trade the guarantee this codebase spent a lot of effort acquiring
    for a feature nobody needs to be synchronous.
    """
    __tablename__ = "automation_rules"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = _ws_fk()
    name: Mapped[str] = mapped_column(String(160), default="")
    # {status?, label_contains?, q?, type?} — all optional, ANDed. An empty match is refused at
    # save time rather than treated as "everything": a rule that silently matched every trace
    # would promote a project's entire history into a dataset on its first pass.
    match: Mapped[dict] = mapped_column(JSON, default=dict)
    action: Mapped[str] = mapped_column(String(16), default="promote")   # promote | score
    target_dataset_id: Mapped[int | None] = mapped_column(nullable=True)
    scorers: Mapped[list] = mapped_column(JSON, default=list)
    # Fraction of matching traces to act on, 0<f<=1. Online scoring costs money per trace, so
    # sampling is a first-class control rather than something to bolt on after the first bill.
    sample: Mapped[float] = mapped_column(Float, default=1.0)
    enabled: Mapped[bool] = mapped_column(default=True)
    # Watermark: the highest Run.id already considered. Rules act on new traffic only — a rule
    # created today that swept all history would be a surprise, and an expensive one for
    # `score`.
    last_run_id: Mapped[int] = mapped_column(Integer, default=0)
    matched: Mapped[int] = mapped_column(Integer, default=0)
    acted: Mapped[int] = mapped_column(Integer, default=0)
    last_status: Mapped[str] = mapped_column(String(160), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class RetentionEvent(Base):
    """What retention deleted, and when.

    Pruning enforces a per-project span cap on every ingest, and it used to do so silently —
    so "my trace is missing" had no answer distinguishable from "it never arrived", which are
    very different bugs to chase. Recording the deletion makes the first one checkable.

    Coalesced by hour rather than one row per prune: on a busy project pruning runs on almost
    every batch, and a row each would be a second write-amplification problem in the name of
    observing the first.
    """
    __tablename__ = "retention_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = _ws_fk()
    bucket: Mapped[datetime] = mapped_column(DateTime, index=True)   # start of the hour, UTC
    deleted: Mapped[int] = mapped_column(Integer, default=0)
    # The cap in force — so a jump in deletions can be traced to a policy change rather than
    # to a traffic spike.
    keep: Mapped[int] = mapped_column(Integer, default=0)
    last_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    __table_args__ = (
        Index("uq_retention_event", "workspace_id", "bucket", unique=True),
    )


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


class Flow(Base):
    """A visual agent workflow — the node/edge graph built on the Flow Studio canvas.

    Stored as a whole document rather than normalised node/edge tables: the canvas always
    reads and writes the entire graph, nothing queries an individual node, and keeping it in
    one row makes a version snapshot a plain copy rather than a cascading clone.

    `published` is a moving pointer in the same spirit as Prompt.label — the draft is what the
    canvas edits, the published version is what a run would execute. Without the split, saving
    a half-built graph would change what production does.
    """
    __tablename__ = "flows"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = _ws_fk()
    name: Mapped[str] = mapped_column(String(160), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    # {"nodes": [...], "edges": [...]} — the canvas document.
    graph: Mapped[dict] = mapped_column(JSON, default=dict)
    version: Mapped[int] = mapped_column(Integer, default=1)
    # Version currently marked live. 0 = never published, so the flow is draft-only.
    published_version: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class FlowVersion(Base):
    """An immutable snapshot of a flow's graph, written on every publish.

    Kept separate from Flow so "restore version 3" is a read of a frozen document rather than
    a reconstruction from a diff — and so a publish can be rolled back without having kept the
    editor open.
    """
    __tablename__ = "flow_versions"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = _ws_fk()
    flow_id: Mapped[int] = mapped_column(Integer, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    graph: Mapped[dict] = mapped_column(JSON, default=dict)
    note: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class FlowRun(Base):
    """One test execution of a flow from the canvas.

    Records the per-node outcome so the canvas can replay the run visually — which node ran,
    in what order, how long each took, and where it stopped. `trace_id` links to the captured
    trace when the run produced one, so a flow execution lands in the same evidence store as
    everything else rather than in a parallel log.
    """
    __tablename__ = "flow_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = _ws_fk()
    flow_id: Mapped[int] = mapped_column(Integer, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(16), default="running")  # running|completed|failed
    input: Mapped[str] = mapped_column(Text, default="")
    output: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str] = mapped_column(Text, default="")
    # [{node_id, label, type, status, duration_ms, output, error}] in execution order.
    steps: Mapped[list] = mapped_column(JSON, default=list)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    trace_id: Mapped[str] = mapped_column(String(32), default="", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
