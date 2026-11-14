"""Turning part of a pipeline into one query: pipelining in the query-engine sense.

A plan is a small graph of nodes. A stored snapshot is a leaf the query reads; a
pass-through transform is a step over the nodes it names as input_0, input_1, ...; a
stand-in is a leaf with known columns and no rows, used to describe a query before any
data exists; a period filter keeps the rows of a source whose period is in the run's time
range. `compose` writes the whole graph as one SQL statement:

    WITH __ada_n0 AS (SELECT * FROM __ada_s0),
         __ada_n1 AS (
           WITH input_0 AS (SELECT * FROM __ada_n0)
           SELECT * FROM (
             <the transform's own SQL>
           )
         )
    SELECT * FROM __ada_n1

Every step gets its own scope for the names input_0, input_1, ..., so steps that each
call their input input_0 do not clash, and a step used twice (a diamond) is written once.
The transform's SQL goes inside a subquery untouched, so it may have its own WITH and its
ORDER BY carries through.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC

from ada.core.models.analysis import Query
from ada.core.models.operators import OperatorId
from ada.core.models.runs import Snapshot
from ada.core.models.schema import Column, ColumnType, TimeRole
from ada.core.models.time import TimeRange

# The SQL type a stand-in column gets for each platform type. Describing over these gives
# back the same platform types, so derived schemas stay stable along a chain.
_SQL_TYPES = {
    ColumnType.TEXT: "VARCHAR",
    ColumnType.INTEGER: "BIGINT",
    ColumnType.NUMBER: "DOUBLE",
    ColumnType.BOOLEAN: "BOOLEAN",
    ColumnType.DATE: "DATE",
    ColumnType.TIMESTAMP: "TIMESTAMP",
    ColumnType.JSON: "JSON",
}


@dataclass(frozen=True, eq=False)
class SnapshotNode:
    """A stored output: the pipeline breaker below a fused query."""

    snapshot: Snapshot


@dataclass(frozen=True, eq=False)
class StandInNode:
    """An input whose columns are known but whose data is not needed: no rows."""

    columns: tuple[Column, ...]


@dataclass(frozen=True, eq=False)
class QueryNode:
    """A transform computed from its inputs instead of read from storage."""

    operator_id: OperatorId
    sql: str
    inputs: tuple[Node, ...]


@dataclass(frozen=True, eq=False)
class PeriodFilterNode:
    """The rows of `input` whose period overlaps the range: how a run applies its time
    range to a source that could not fetch only the requested periods."""

    input: Node
    time: TimeRole
    time_range: TimeRange


type Node = SnapshotNode | StandInNode | QueryNode | PeriodFilterNode


def compose(root: Node) -> Query:
    """One query that answers `root` from the snapshots it rests on."""
    if isinstance(root, SnapshotNode):
        return Query(sql="SELECT * FROM __ada_s0", relations={"__ada_s0": root.snapshot.location})
    relations: dict[str, str] = {}
    steps: list[str] = []
    # Keyed by object identity: the planner hands out one node per operator, so a shared
    # upstream is the same object and is written once.
    names: dict[int, str] = {}

    def name(node: Node) -> str:
        if id(node) in names:
            return names[id(node)]
        match node:
            case SnapshotNode(snapshot=snapshot):
                relation = f"__ada_s{len(relations)}"
                relations[relation] = snapshot.location
                names[id(node)] = relation
                return relation
            case StandInNode(columns=columns):
                body = stand_in_sql(columns)
            case PeriodFilterNode(input=upstream, time=time, time_range=time_range):
                body = f"SELECT * FROM {name(upstream)} WHERE {_overlaps(time, time_range)}"
            case QueryNode(sql=sql, inputs=inputs):
                aliases = [
                    f"input_{index} AS (SELECT * FROM {name(upstream)})"
                    for index, upstream in enumerate(inputs)
                ]
                scope = f"WITH {', '.join(aliases)}\n" if aliases else ""
                body = f"{scope}SELECT * FROM (\n{sql}\n)"
        step = f"__ada_n{len(steps)}"
        steps.append(f"{step} AS (\n{body}\n)")
        names[id(node)] = step
        return step

    top = name(root)
    return Query(sql=f"WITH {',\n'.join(steps)}\nSELECT * FROM {top}", relations=relations)


def content_identity(node: Node) -> str:
    """What a node's data is a function of. For a snapshot, its content hash: a refetch of
    identical data changes nothing downstream. For a query, its operator and the identities
    of its inputs."""
    match node:
        case SnapshotNode(snapshot=snapshot):
            return f"snapshot:{snapshot.content_hash}"
        case QueryNode(operator_id=operator_id, inputs=inputs):
            return "query:" + _digest(
                {"operator": operator_id, "inputs": [content_identity(i) for i in inputs]}
            )
        case PeriodFilterNode(input=upstream, time=time, time_range=time_range):
            return "periods:" + _digest(
                {
                    "input": content_identity(upstream),
                    "columns": [time.start, time.end],
                    "range": time_range.model_dump(mode="json"),
                }
            )
        case StandInNode():
            raise ValueError("A stand-in has no data, so it has no content identity")


def parameters_key(inputs: tuple[Node, ...]) -> str:
    """The snapshot key of a materializing transform over these inputs.

    The operator id already fixes the SQL and which operators feed it, so the key only has
    to say which data they delivered: the content identities of the inputs, in order. A new
    source snapshot with different content, or an Input bound to another pipeline, changes
    the key and so makes a new snapshot; identical content keeps the key and is reused.
    The run's time range counts only where it changed the data, through a period filter
    or the period snapshots below; an operator whose inputs ignore it keeps its key."""
    return "inputs:" + _digest([content_identity(node) for node in inputs])


def history(operator_id: OperatorId, snapshots: list[Snapshot]) -> QueryNode:
    """Union stored versions by name; metadata participates in downstream cache keys."""
    parts = [
        "SELECT *, TIMESTAMP '"
        f"{snapshot.fetched_at.astimezone(UTC).replace(tzinfo=None).isoformat()}' "
        f"AS snapshot_at, CAST({rank} AS INTEGER) AS snapshot_rank FROM input_{rank - 1}"
        for rank, snapshot in enumerate(snapshots, 1)
    ]
    identity = _digest([[str(s.id), s.fetched_at.isoformat(), s.content_hash] for s in snapshots])
    return QueryNode(
        f"{operator_id}:{identity}",
        "SELECT * FROM (" + " UNION ALL BY NAME ".join(parts) + ") ORDER BY snapshot_rank",
        tuple(SnapshotNode(s) for s in snapshots),
    )


def stand_in_sql(columns: tuple[Column, ...]) -> str:
    """A table with these columns and no rows, e.g. a period a source has no data for."""
    selected = ", ".join(
        f"CAST(NULL AS {_SQL_TYPES[column.type]}) AS {quote(column.name)}" for column in columns
    )
    return f"SELECT {selected} LIMIT 0"


def union(columns: tuple[Column, ...], snapshots: list[Snapshot], order_by: str) -> Query:
    """One table of several snapshots with the same declared columns, e.g. the periods of
    a source. Every part is cast to the declared types, so a period whose values are all
    empty, and so were read with another type, still lines up with the rest."""
    selected = ", ".join(
        f"CAST({quote(column.name)} AS {_SQL_TYPES[column.type]}) AS {quote(column.name)}"
        for column in columns
    )
    relations = {f"__ada_s{index}": s.location for index, s in enumerate(snapshots)}
    parts = "\nUNION ALL\n".join(f"SELECT {selected} FROM {name}" for name in relations)
    return Query(sql=f"SELECT * FROM (\n{parts}\n) ORDER BY {quote(order_by)}", relations=relations)


def _overlaps(time: TimeRole, time_range: TimeRange) -> str:
    """A row is in the range when its period shares at least one day with it; a row
    without a period is in no bounded range."""
    conditions = []
    if time_range.start is not None:
        conditions.append(f"CAST({quote(time.end)} AS DATE) >= DATE '{time_range.start}'")
    if time_range.end is not None:
        conditions.append(f"CAST({quote(time.start)} AS DATE) <= DATE '{time_range.end}'")
    return " AND ".join(conditions) or "TRUE"


def quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _digest(value: object) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:32]
