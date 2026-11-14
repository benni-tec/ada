"""Builders for domain models with sensible defaults, so a test states only what it is
about."""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid7

from ada.core.models.actors import Actor, ActorKind
from ada.core.models.base import Id
from ada.core.models.operators import Operator, OperatorId, OperatorKind, operator_identity
from ada.core.models.projects import Project
from ada.core.models.runs import Run, Snapshot
from ada.core.models.schema import Column, ColumnType, Schema
from ada.core.models.sessions import Session
from ada.core.models.sources import AccessKind, DataFormat, DataSource

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
AGENT = Actor(kind=ActorKind.EXTERNAL_AGENT, name="test client")
SCHEMA = Schema(
    columns=(
        Column(name="region", type=ColumnType.TEXT),
        Column(name="value", type=ColumnType.NUMBER),
    )
)


def project(**changes: Any) -> Project:
    return Project(**{"id": uuid7(), "name": "Project", "created_at": NOW, **changes})


def data_source(project_id: Id, **changes: Any) -> DataSource:
    return DataSource(
        **{
            "id": uuid7(),
            "project_id": project_id,
            "name": "Source",
            "access_kind": AccessKind.URL,
            "address": "https://example.test/data.csv",
            "format": DataFormat.CSV,
            "created_at": NOW,
            **changes,
        }
    )


def session(project_id: Id, **changes: Any) -> Session:
    return Session(
        **{"id": uuid7(), "project_id": project_id, "title": "Session", "created_at": NOW} | changes
    )


def operator(
    project_id: Id,
    kind: OperatorKind = OperatorKind.TRANSFORM,
    params: dict[str, Any] | None = None,
    inputs: tuple[OperatorId, ...] = (),
    **changes: Any,
) -> Operator:
    params = params if params is not None else {"sql": "SELECT 1"}
    return Operator(
        **{
            "id": operator_identity(project_id, kind, params, inputs),
            "project_id": project_id,
            "kind": kind,
            "params": params,
            "inputs": inputs,
            "output": SCHEMA,
            "materializing": kind is OperatorKind.SOURCE,
            "created_by": AGENT,
            "created_at": NOW,
            **changes,
        }
    )


def snapshot(project_id: Id, operator_id: OperatorId, **changes: Any) -> Snapshot:
    return Snapshot(
        **{
            "id": uuid7(),
            "project_id": project_id,
            "operator_id": operator_id,
            "parameters_key": "",
            "content_hash": "abc",
            "location": "memory://snapshot",
            "fetched_at": NOW,
            **changes,
        }
    )


def run(project_id: Id, **changes: Any) -> Run:
    return Run(
        **{"id": uuid7(), "project_id": project_id, "started_by": AGENT, "started_at": NOW}
        | changes
    )
