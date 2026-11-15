"""Every table of the definitions database.

Conventions:

- Ids are UUIDs, except operators, whose id is their identity hash.
- Nested values (schemas, specs, slots, actors, formulas) are JSONB holding the domain
  model's JSON form.
- Mutable tables have a `revision` column that SQLAlchemy uses as its version counter:
  an UPDATE names the revision it read, and StaleDataError means someone else wrote first.
- Immutable tables (operators, snapshots, runs, the version tables) are only inserted into.
- The pointers `current_version_id` and `latest_version_id` have no foreign key, since the
  version rows point back at their owner.
"""

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ada.adapters.db.base import Base

type Json = dict[str, Any]

_timestamp = DateTime(timezone=True)
# Defined out here: inside SessionEntryRow, `text` is its column.
_empty_list = text("'[]'::jsonb")


def _project() -> Mapped[UUID]:
    return mapped_column(Uuid, ForeignKey("projects.id", ondelete="CASCADE"), index=True)


class ProjectRow(Base):
    __tablename__ = "projects"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(_timestamp)
    # Instructions for the session agent in this project; "" for none (migration 0008).
    agent_instructions: Mapped[str] = mapped_column(Text, default="", server_default="")
    revision: Mapped[int] = mapped_column(Integer)

    __mapper_args__ = {"version_id_col": revision}


class DataSourceRow(Base):
    __tablename__ = "data_sources"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    project_id: Mapped[UUID] = _project()
    name: Mapped[str] = mapped_column(Text)
    access_kind: Mapped[str] = mapped_column(String(16))
    address: Mapped[str] = mapped_column(Text)
    format: Mapped[str] = mapped_column(String(16))
    options: Mapped[Json] = mapped_column(JSONB)
    freshness: Mapped[Json] = mapped_column(JSONB)
    declared_schema: Mapped[Json | None] = mapped_column(JSONB)
    provenance: Mapped[Json | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(_timestamp)
    last_checked_at: Mapped[datetime | None] = mapped_column(_timestamp)
    last_probe_token: Mapped[str | None] = mapped_column(Text)
    last_error: Mapped[str | None] = mapped_column(Text)
    check_every: Mapped[str | None] = mapped_column(Text)
    monitor_id: Mapped[str | None] = mapped_column(Text)
    # Sealed by the SecretBox; never on the model.
    monitor_secret_encrypted: Mapped[str | None] = mapped_column(Text)
    # What unwatching restores; set while a monitor is.
    freshness_before_watch: Mapped[Json | None] = mapped_column(JSONB)
    revision: Mapped[int] = mapped_column(Integer)

    __mapper_args__ = {"version_id_col": revision}


class DashboardRow(Base):
    __tablename__ = "dashboards"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    project_id: Mapped[UUID] = _project()
    name: Mapped[str] = mapped_column(Text)
    current_version_id: Mapped[UUID | None] = mapped_column(Uuid)
    default_time_start: Mapped[date | None] = mapped_column(Date)
    default_time_end: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(_timestamp)
    revision: Mapped[int] = mapped_column(Integer)
    # The order people gave the project's dashboards; outside the revision.
    position: Mapped[int | None] = mapped_column(Integer)

    __mapper_args__ = {"version_id_col": revision}


class TemplateRow(Base):
    __tablename__ = "templates"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    project_id: Mapped[UUID] = _project()
    name: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(16))
    slots: Mapped[list[Json]] = mapped_column(JSONB)
    content: Mapped[Json] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(_timestamp)
    revision: Mapped[int] = mapped_column(Integer)

    __mapper_args__ = {"version_id_col": revision}


class DashboardVersionRow(Base):
    __tablename__ = "dashboard_versions"
    __table_args__ = (UniqueConstraint("dashboard_id", "number"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    dashboard_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("dashboards.id", ondelete="CASCADE"), index=True
    )
    number: Mapped[int] = mapped_column(Integer)
    slots: Mapped[list[Json]] = mapped_column(JSONB)
    template_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("templates.id", ondelete="SET NULL")
    )
    created_by: Mapped[Json] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(_timestamp)


class SessionRow(Base):
    __tablename__ = "sessions"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    project_id: Mapped[UUID] = _project()
    title: Mapped[str] = mapped_column(Text)
    origin_dashboard_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("dashboards.id", ondelete="SET NULL")
    )
    panel_dashboard_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("dashboards.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(_timestamp)
    agent: Mapped[str] = mapped_column(String(16), server_default="session")
    parent_session_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("sessions.id", ondelete="SET NULL"), index=True
    )
    # Paid web calls of a research session; outside the revision, like a counter.
    web_calls: Mapped[int] = mapped_column(Integer, server_default="0")
    revision: Mapped[int] = mapped_column(Integer)

    __mapper_args__ = {"version_id_col": revision}


class SessionEntryRow(Base):
    __tablename__ = "session_entries"
    __table_args__ = (Index("ix_session_entries_session_created", "session_id", "created_at"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    session_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("sessions.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(16))
    text: Mapped[str] = mapped_column(Text)
    ref: Mapped[str | None] = mapped_column(Text)
    actor: Mapped[Json] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(_timestamp)
    # What a message is about: the domain model's context items as JSON.
    context: Mapped[list[Json]] = mapped_column(JSONB, server_default=_empty_list)
    # For a tool call: the domain model's ToolCall as JSON.
    tool_call: Mapped[Json | None] = mapped_column(JSONB)


class SessionAttachmentRow(Base):
    """What is attached to a session, shown beside it as tabs and listed to its agent."""

    __tablename__ = "session_attachments"
    __table_args__ = (
        UniqueConstraint("session_id", "kind", "ref", name="uq_session_attachments_ref"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    session_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    # The AttachmentKind; `ref` is the thing's id (an operator id for a pipeline, a URL for
    # a web page). Not a foreign key: the service checks it, and a deleted thing shows as
    # gone.
    kind: Mapped[str] = mapped_column(String(16))
    ref: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text, server_default="")
    actor: Mapped[Json] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(_timestamp)


class AgentTurnRow(Base):
    """The in-platform agent's turns. Written by the worker as the turn runs, outside any
    revision; `cancel_requested` is the one column someone else writes. `settled` says
    that the turn's end was announced (its finished event, a research turn's report)."""

    __tablename__ = "agent_turns"
    __table_args__ = (
        Index("ix_agent_turns_session_created", "session_id", "created_at"),
        Index("ix_agent_turns_unsettled", "status", postgresql_where=text("NOT settled")),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    session_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("sessions.id", ondelete="CASCADE"))
    prompt_entry_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("session_entries.id", ondelete="CASCADE")
    )
    model: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16))
    parts: Mapped[list[Json]] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    settled: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(_timestamp)
    started_at: Mapped[datetime | None] = mapped_column(_timestamp)
    finished_at: Mapped[datetime | None] = mapped_column(_timestamp)


class LlmProviderRow(Base):
    """The in-platform agent's model providers, shared by all projects."""

    __tablename__ = "llm_providers"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    name: Mapped[str] = mapped_column(Text, unique=True)
    kind: Mapped[str] = mapped_column(String(32))
    base_url: Mapped[str | None] = mapped_column(Text)
    # The SecretBox token of the key, never the key.
    api_key_encrypted: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(_timestamp)
    revision: Mapped[int] = mapped_column(Integer)

    __mapper_args__ = {"version_id_col": revision}


class LlmModelRow(Base):
    """A provider's model. The domain addresses it as "<provider name>/<model>"; the uuid
    is only for the session agent's reference."""

    __tablename__ = "llm_models"
    __table_args__ = (UniqueConstraint("provider_id", "model"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    provider_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("llm_providers.id", ondelete="CASCADE")
    )
    model: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(_timestamp)


class AgentSettingsRow(Base):
    """One row (id 1, inserted by the migration): which model does what."""

    __tablename__ = "agent_settings"
    __table_args__ = (CheckConstraint("id = 1", name="agent_settings_one_row"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_agent_model_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("llm_models.id", ondelete="SET NULL")
    )
    # Instructions for the session agent in every project; "" for none (migration 0008).
    instructions: Mapped[str] = mapped_column(Text, default="", server_default="")
    research_agent_model_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("llm_models.id", ondelete="SET NULL")
    )
    revision: Mapped[int] = mapped_column(Integer)

    __mapper_args__ = {"version_id_col": revision}


class JudgeDefaultsRow(Base):
    """The judges' global settings, one row per kind (inserted by migration 0012)."""

    __tablename__ = "judge_defaults"

    kind: Mapped[str] = mapped_column(String(32), primary_key=True)
    strictness: Mapped[str] = mapped_column(String(16))
    model_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("llm_models.id", ondelete="SET NULL")
    )
    instructions: Mapped[str] = mapped_column(Text, default="", server_default="")
    revision: Mapped[int] = mapped_column(Integer)

    __mapper_args__ = {"version_id_col": revision}


class ProjectJudgeRow(Base):
    """A project's overrides of one kind's settings; NULL inherits the global default."""

    __tablename__ = "project_judges"

    project_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    kind: Mapped[str] = mapped_column(String(32), primary_key=True)
    strictness: Mapped[str | None] = mapped_column(String(16))
    model_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("llm_models.id", ondelete="SET NULL")
    )
    instructions: Mapped[str | None] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(Integer)

    __mapper_args__ = {"version_id_col": revision}


class OperatorRow(Base):
    __tablename__ = "operators"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[UUID] = _project()
    kind: Mapped[str] = mapped_column(String(16))
    params: Mapped[Json] = mapped_column(JSONB)
    # The input ids in order, as the domain model has them. operator_inputs holds the
    # same edges as rows, for walking the graph in SQL.
    inputs: Mapped[list[str]] = mapped_column(JSONB)
    output: Mapped[Json] = mapped_column(JSONB)
    materializing: Mapped[bool] = mapped_column(Boolean)
    # Set for source operators, so the operators reading a data source can be found.
    data_source_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("data_sources.id", ondelete="RESTRICT"), index=True
    )
    created_by: Mapped[Json] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(_timestamp)


class OperatorInputRow(Base):
    __tablename__ = "operator_inputs"

    operator_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("operators.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    input_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("operators.id", ondelete="RESTRICT"), index=True
    )


class SnapshotRow(Base):
    __tablename__ = "snapshots"
    __table_args__ = (
        # At most one snapshot per operator and key is current.
        Index(
            "uq_snapshots_current",
            "operator_id",
            "parameters_key",
            unique=True,
            postgresql_where=text("superseded_at IS NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    project_id: Mapped[UUID] = _project()
    operator_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("operators.id", ondelete="RESTRICT"), index=True
    )
    parameters_key: Mapped[str] = mapped_column(Text)
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    content_hash: Mapped[str] = mapped_column(String(64))
    location: Mapped[str] = mapped_column(Text)
    row_count: Mapped[int | None] = mapped_column(Integer)
    fetched_at: Mapped[datetime] = mapped_column(_timestamp)
    origin: Mapped[str | None] = mapped_column(Text)
    superseded_at: Mapped[datetime | None] = mapped_column(_timestamp)


class RunRow(Base):
    __tablename__ = "runs"
    __table_args__ = (Index("ix_runs_project_started", "project_id", "started_at"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    project_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("projects.id", ondelete="CASCADE"))
    time_start: Mapped[date | None] = mapped_column(Date)
    time_end: Mapped[date | None] = mapped_column(Date)
    bindings: Mapped[dict[str, str]] = mapped_column(JSONB)
    started_by: Mapped[Json] = mapped_column(JSONB)
    started_at: Mapped[datetime] = mapped_column(_timestamp)


class RunSnapshotRow(Base):
    """Which snapshot a run fixed for an operator. Rows are only ever added."""

    __tablename__ = "run_snapshots"

    run_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True
    )
    operator_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("operators.id", ondelete="RESTRICT"), primary_key=True
    )
    # A snapshot that a run uses is never removed.
    snapshot_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("snapshots.id", ondelete="RESTRICT"))


class WidgetRow(Base):
    __tablename__ = "widgets"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    project_id: Mapped[UUID] = _project()
    session_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("sessions.id", ondelete="SET NULL"), index=True
    )
    operator_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("operators.id", ondelete="RESTRICT")
    )
    type: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(Text)
    spec: Mapped[Json] = mapped_column(JSONB)
    note: Mapped[str] = mapped_column(Text)
    created_by: Mapped[Json] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(_timestamp)
    # The widget a dashboard's copy was made from; the copy outlives a deleted original.
    copied_from: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("widgets.id", ondelete="SET NULL")
    )
    # Further inputs by name ({name: operator id}); not foreign keys, checked by the service.
    inputs: Mapped[Json] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    render_error: Mapped[str | None] = mapped_column(Text)
    # A judge's review of what the agent wrote (a custom widget's code): a Verdict as JSON.
    verdict: Mapped[Json | None] = mapped_column(JSONB)


class ReportRow(Base):
    __tablename__ = "reports"
    __table_args__ = (
        CheckConstraint(
            "(session_id IS NULL) <> (dashboard_id IS NULL)", name="ck_reports_one_owner"
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    project_id: Mapped[UUID] = _project()
    name: Mapped[str] = mapped_column(Text)
    session_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    dashboard_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("dashboards.id", ondelete="CASCADE"), index=True
    )
    latest_version_id: Mapped[UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(_timestamp)
    revision: Mapped[int] = mapped_column(Integer)
    # The order people gave the project's reports; outside the revision.
    position: Mapped[int | None] = mapped_column(Integer)

    __mapper_args__ = {"version_id_col": revision}


class ReportVersionRow(Base):
    __tablename__ = "report_versions"
    __table_args__ = (UniqueConstraint("report_id", "version"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    report_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("reports.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[str] = mapped_column(String(32))
    # A run that a report pins is never removed.
    run_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("runs.id", ondelete="RESTRICT"))
    time_start: Mapped[date | None] = mapped_column(Date)
    time_end: Mapped[date | None] = mapped_column(Date)
    content: Mapped[Json] = mapped_column(JSONB)
    template_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("templates.id", ondelete="SET NULL")
    )
    dashboard_version_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("dashboard_versions.id", ondelete="SET NULL")
    )
    created_by: Mapped[Json] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(_timestamp)


class AlertRuleRow(Base):
    __tablename__ = "alert_rules"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    project_id: Mapped[UUID] = _project()
    dashboard_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("dashboards.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(Text)
    operator_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("operators.id", ondelete="RESTRICT")
    )
    formula: Mapped[Json] = mapped_column(JSONB)
    key_columns: Mapped[list[str]] = mapped_column(JSONB)
    severity: Mapped[str] = mapped_column(String(16))
    check_interval_seconds: Mapped[int | None] = mapped_column(Integer)
    max_data_age_seconds: Mapped[int | None] = mapped_column(Integer)
    alert_pipeline_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("operators.id", ondelete="RESTRICT")
    )
    enabled: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(_timestamp)
    last_checked_at: Mapped[datetime | None] = mapped_column(_timestamp)
    revision: Mapped[int] = mapped_column(Integer)

    __mapper_args__ = {"version_id_col": revision}


class AlertRow(Base):
    __tablename__ = "alerts"
    __table_args__ = (
        # At most one firing alert per rule and key.
        Index(
            "uq_alerts_firing",
            "rule_id",
            "key",
            unique=True,
            postgresql_where=text("state = 'firing'"),
        ),
        Index("ix_alerts_project_started", "project_id", "started_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    project_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("projects.id", ondelete="CASCADE"))
    rule_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("alert_rules.id", ondelete="CASCADE"), index=True
    )
    key: Mapped[Json] = mapped_column(JSONB)
    state: Mapped[str] = mapped_column(String(16))
    since_run_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("runs.id", ondelete="RESTRICT"))
    last_run_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("runs.id", ondelete="RESTRICT"))
    started_at: Mapped[datetime] = mapped_column(_timestamp)
    resolved_at: Mapped[datetime | None] = mapped_column(_timestamp)
    condition_sql: Mapped[str | None] = mapped_column(Text)
    pipeline_run_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("runs.id", ondelete="RESTRICT")
    )


class WebUsageRow(Base):
    """The Context.dev credits a project spent on one day (UTC): the web tools and web
    sources count against Settings.web_daily_credit_limit."""

    __tablename__ = "web_usage"

    project_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    credits: Mapped[int] = mapped_column(Integer)


class AlertDeliveryRow(Base):
    __tablename__ = "alert_deliveries"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    alert_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("alerts.id", ondelete="CASCADE"))
    project_id: Mapped[UUID] = _project()
    rule_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("alert_rules.id", ondelete="CASCADE"))
    test: Mapped[bool] = mapped_column(Boolean)
    channel: Mapped[str] = mapped_column(Text)
    target: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    http_status: Mapped[int | None] = mapped_column(Integer)
    detail: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(_timestamp)
