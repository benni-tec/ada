"""What every SQLAlchemy repository shares: reading a row or raising NotFound, listing in
the port's order, and the revision check of mutable records.

Reads always refresh rows from the database (`populate_existing`). A request shares one
session, and some writes bypass the ORM (`record_check`, `supersede`), so an object that
the session remembers can be older than the row.
"""

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic_core import to_jsonable_python
from sqlalchemy import Select, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import StaleDataError

from ada.core.models.base import DomainModel
from ada.core.models.errors import Conflict, NotFound


def dump(model: DomainModel) -> dict[str, Any]:
    """A model in the JSON form that JSONB columns hold."""
    return model.model_dump(mode="json")


def json_object(value: Any) -> Any:
    """A free-form JSON value of a model (options, spec, params) as JSONB can store it:
    models allow `Any` there, so a UUID or a date may be inside."""
    return to_jsonable_python(value)


def dump_all(models: Sequence[DomainModel]) -> list[dict[str, Any]]:
    return [dump(model) for model in models]


def oldest_first(row_type: Any, *conditions: Any, by: Any = None) -> Select[Any]:
    """Select rows in creation order, `by` naming the timestamp column when it is not
    `created_at`. Ids are UUIDv7, so they break ties between equal timestamps in the order
    the records were made."""
    column = by if by is not None else row_type.created_at
    return select(row_type).where(*conditions).order_by(column, row_type.id)


def in_position_order(row_type: Any, *conditions: Any) -> Select[Any]:
    """Select rows in the order people gave them (`position`), then the unplaced ones in
    creation order."""
    return (
        select(row_type)
        .where(*conditions)
        .order_by(row_type.position.asc().nulls_last(), row_type.created_at, row_type.id)
    )


async def set_positions(
    session: AsyncSession, row_type: Any, project_id: object, ids: Sequence[object]
) -> None:
    """Pin the given rows in this order and unpin the project's others. A bulk update, so the
    revision stays: pinning conflicts with no edit."""
    await session.execute(
        update(row_type)
        .where(row_type.project_id == project_id, row_type.id.not_in(list(ids)))
        .values(position=None)
        .execution_options(synchronize_session=False)
    )
    for position, id in enumerate(ids):
        await session.execute(
            update(row_type)
            .where(row_type.id == id, row_type.project_id == project_id)
            .values(position=position)
            .execution_options(synchronize_session=False)
        )


def newest_first(row_type: Any, column: Any, *conditions: Any) -> Select[Any]:
    return select(row_type).where(*conditions).order_by(column.desc(), row_type.id.desc())


async def fetch[R](session: AsyncSession, row_type: type[R], id: object, kind: str) -> R:
    row = await session.get(row_type, id, populate_existing=True)
    if row is None:
        raise NotFound(kind, id)
    return row


async def require(session: AsyncSession, row_type: type[Any], id: object, kind: str) -> None:
    """Raise NotFound unless the record exists. For references the database would reject
    with an integrity error, which callers cannot tell from any other failure."""
    found = await session.scalar(select(row_type.id).where(row_type.id == id))
    if found is None:
        raise NotFound(kind, id)


async def rows(session: AsyncSession, statement: Select[Any]) -> Sequence[Any]:
    result = await session.scalars(statement.execution_options(populate_existing=True))
    return result.all()


async def add_row(session: AsyncSession, row: object) -> None:
    session.add(row)
    # Flush now, so a violated constraint surfaces at the call that caused it.
    await session.flush()


async def update_row[R](
    session: AsyncSession,
    row_type: type[R],
    kind: str,
    id: object,
    expected_revision: int,
    changes: Mapping[str, Any],
) -> R:
    """Apply `changes` to a mutable record whose stored revision is `expected_revision`,
    and return the row.

    The row is locked while it is read, so a concurrent writer waits and then sees the new
    revision instead of failing halfway. SQLAlchemy's version counter (`version_id_col`)
    adds the same check to the UPDATE itself and counts the revision up by one.
    """
    row = await session.get(row_type, id, with_for_update=True, populate_existing=True)
    if row is None:
        raise NotFound(kind, id)
    actual: int = row.revision  # type: ignore[attr-defined]
    if actual != expected_revision:
        raise Conflict(kind, id, expected_revision, actual)
    for name, value in changes.items():
        setattr(row, name, value)
    try:
        await session.flush()
    except StaleDataError:
        # Not reachable while the row is locked; if it ever happens, report it like any
        # other lost race.
        await session.refresh(row)
        raise Conflict(kind, id, expected_revision, row.revision) from None  # type: ignore[attr-defined]
    return row
