import asyncio
import hashlib
import json
import os
import re
from collections.abc import Iterable, Sequence
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import duckdb

from ada.core.models.analysis import FetchedData, Query, Rows, StoredSnapshot
from ada.core.models.base import Id
from ada.core.models.errors import Invalid, NotFound
from ada.core.models.schema import Column, ColumnType, Roles, Schema
from ada.core.models.sources import DataFormat
from ada.core.ports.analysis import AnalysisStore

# DuckDB's reader for each format. read_json detects on its own whether the bytes are one
# array of objects or newline-delimited objects.
_READERS = {
    DataFormat.CSV: "read_csv",
    DataFormat.JSON: "read_json",
    DataFormat.PARQUET: "read_parquet",
}

_INTEGERS = {
    "tinyint",
    "smallint",
    "integer",
    "bigint",
    "hugeint",
    "utinyint",
    "usmallint",
    "uinteger",
    "ubigint",
    "uhugeint",
    "varint",
    "bignum",
}
_NUMBERS = {"float", "double", "decimal"}
_NESTED = {"struct", "list", "map", "array", "union"}

# Relation names become view names; anything else could smuggle SQL into CREATE VIEW.
_RELATION_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

_HASH_BATCH = 8192


class DuckDbAnalysisStore(AnalysisStore):
    """Snapshots are Parquet files under data_dir, written once and never changed. Every
    call opens its own in-memory DuckDB in a worker thread and reads the files it needs,
    so the API and the workers never contend for one database file.

    Layout and identity. A snapshot lives at `<project_id>/<content_hash>.parquet`,
    relative to data_dir; that relative path is its location, so data_dir can move. The
    content hash is a SHA-256 of the stored table itself: its column names and DuckDB
    types, then every row in sorted order (`ORDER BY ALL`). It therefore does not depend
    on how the bytes were laid out (quoting, whitespace, row order, CSV versus JSON for the
    same typed rows) or on DuckDB's Parquet encoding, and identical data always lands in
    the same file. Rows are sorted only for hashing; the file keeps the order the data had.

    Guarding SQL. Queries come from agents, so every connection that runs one is locked
    down before the query is seen: external access is off except for the exact Parquet
    files named by the query's relations (and, when materializing, the one file being
    written), and the configuration is locked so the SQL cannot switch that back. Reading
    other files, writing files, attaching databases and installing extensions all fail.
    Only a single SELECT statement is accepted.
    """

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir

    async def is_usable(self) -> bool:
        return await asyncio.to_thread(self._is_usable)

    async def write(
        self, project_id: Id, data: FetchedData, declared: Schema | None = None
    ) -> StoredSnapshot:
        return await asyncio.to_thread(self._write, project_id, data, declared)

    async def materialize(self, project_id: Id, query: Query) -> StoredSnapshot:
        return await asyncio.to_thread(self._materialize, project_id, query)

    async def describe(self, query: Query) -> tuple[Column, ...]:
        return await asyncio.to_thread(self._describe, query)

    async def run(self, query: Query, limit: int) -> Rows:
        return await asyncio.to_thread(self._run, query, limit)

    def _is_usable(self) -> bool:
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            if not os.access(self.data_dir, os.W_OK):
                return False
            with duckdb.connect(":memory:") as connection:
                connection.execute("SELECT 1").fetchone()
        except OSError, duckdb.Error:
            return False
        return True

    def _write(self, project_id: Id, data: FetchedData, declared: Schema | None) -> StoredSnapshot:
        if not data.content.strip():
            raise Invalid(f"The {data.format.value} data is empty")
        directory = self._project_dir(project_id)
        # DuckDB reads files, not bytes, so the data goes to a scratch file first. Nothing
        # here runs SQL from outside, so this connection needs no lockdown.
        incoming = directory / f".incoming-{uuid4().hex}.{data.format.value}"
        incoming.write_bytes(data.content)
        try:
            with duckdb.connect(":memory:") as connection:
                select = f"SELECT * FROM {_READERS[data.format]}({_literal(incoming)})"
                return self._store(
                    connection, select, directory, project_id, declared, what="the data"
                )
        finally:
            incoming.unlink(missing_ok=True)

    def _materialize(self, project_id: Id, query: Query) -> StoredSnapshot:
        _check_select(query.sql)
        directory = self._project_dir(project_id)
        relations = self._relations(query)
        target = _scratch_file(directory)
        with self._locked(relations, writable=target) as connection:
            return self._store(
                connection, query.sql, directory, project_id, None, what="the query", tmp=target
            )

    def _describe(self, query: Query) -> tuple[Column, ...]:
        _check_select(query.sql)
        with self._locked(self._relations(query)) as connection:
            try:
                # Building a relation binds the query, which resolves every name and type,
                # but does not execute it.
                relation = connection.sql(query.sql)
            except duckdb.Error as error:
                raise Invalid(f"The query is not valid: {error}") from error
            return _columns(relation.columns, relation.types)

    def _run(self, query: Query, limit: int) -> Rows:
        if limit < 0:
            raise Invalid("The limit must not be negative")
        _check_select(query.sql)
        with self._locked(self._relations(query)) as connection:
            try:
                # One row more than asked tells whether there is more. The wrapping keeps
                # the query's own order.
                relation = connection.sql(f"SELECT * FROM (\n{query.sql}\n) LIMIT {limit + 1}")
                fetched = relation.fetchall()
            except duckdb.Error as error:
                raise Invalid(f"The query failed: {error}") from error
            columns = _columns(relation.columns, relation.types)
        rows = tuple(tuple(_plain(value) for value in row) for row in fetched[:limit])
        return Rows(columns=columns, rows=rows, truncated=len(fetched) > limit)

    def _store(
        self,
        connection: duckdb.DuckDBPyConnection,
        select: str,
        directory: Path,
        project_id: Id,
        declared: Schema | None,
        what: str,
        tmp: Path | None = None,
    ) -> StoredSnapshot:
        """Write the result of `select` as a snapshot: to a scratch file first, then moved
        to its content-addressed name, so a reader never sees a half-written file."""
        tmp = tmp or _scratch_file(directory)
        try:
            try:
                connection.execute(f"COPY ({select}) TO {_literal(tmp)} (FORMAT parquet)")
                stored = f"read_parquet({_literal(tmp)})"
                relation = connection.sql(f"SELECT * FROM {stored}")
                columns = _columns(relation.columns, relation.types)
                count = connection.execute(f"SELECT count(*) FROM {stored}").fetchone()
                row_count = int(count[0]) if count else 0
            except duckdb.Error as error:
                raise Invalid(f"Could not read {what}: {error}") from error
            _check_unique(columns)
            output = _output(columns, declared)
            content_hash = _content_hash(connection, stored, relation.types, columns)
            final = directory / f"{content_hash}.parquet"
            if final.exists():
                # Identical data is already stored; the files are interchangeable.
                tmp.unlink()
            else:
                os.replace(tmp, final)
        finally:
            tmp.unlink(missing_ok=True)
        return StoredSnapshot(
            location=f"{project_id}/{final.name}",
            content_hash=content_hash,
            row_count=row_count,
            output=output,
        )

    def _locked(
        self, relations: dict[str, Path], writable: Path | None = None
    ) -> duckdb.DuckDBPyConnection:
        """A connection that can read only the given snapshots and write only `writable`,
        with each relation available as a view of its name."""
        connection = duckdb.connect(":memory:")
        try:
            allowed = [*relations.values(), *([writable] if writable else [])]
            connection.execute(f"SET allowed_paths = [{', '.join(map(_literal, allowed))}]")
            connection.execute("SET autoinstall_known_extensions = false")
            connection.execute("SET autoload_known_extensions = false")
            connection.execute("SET enable_external_access = false")
            connection.execute("SET lock_configuration = true")
            for name, path in relations.items():
                connection.execute(
                    f'CREATE VIEW "{name}" AS SELECT * FROM read_parquet({_literal(path)})'
                )
        except BaseException:
            connection.close()
            raise
        return connection

    def _relations(self, query: Query) -> dict[str, Path]:
        relations: dict[str, Path] = {}
        for name, location in query.relations.items():
            if not _RELATION_NAME.fullmatch(name):
                raise Invalid(f"{name!r} cannot name a relation")
            path = self._resolve(location)
            if not path.is_file():
                raise NotFound("snapshot", location)
            relations[name] = path
        return relations

    def _resolve(self, location: str) -> Path:
        """The file of a snapshot location. Locations are relative to data_dir; anything
        that points outside it is refused, so a query reads only snapshots."""
        root = self.data_dir.resolve()
        path = (root / location).resolve()
        if not path.is_relative_to(root) or path.suffix != ".parquet":
            raise Invalid(f"{location!r} is not a snapshot location")
        return path

    def _project_dir(self, project_id: Id) -> Path:
        directory = self.data_dir.resolve() / str(project_id)
        directory.mkdir(parents=True, exist_ok=True)
        return directory


def _check_select(sql: str) -> None:
    try:
        statements = duckdb.extract_statements(sql)
    except duckdb.Error as error:
        raise Invalid(f"The query is not valid: {error}") from error
    if len(statements) != 1 or statements[0].type is not duckdb.StatementType.SELECT:
        raise Invalid("A query must be exactly one SELECT statement")


def _columns(names: Sequence[str], types: Sequence[duckdb.DuckDBPyType]) -> tuple[Column, ...]:
    return tuple(
        Column(name=name, type=_column_type(t)) for name, t in zip(names, types, strict=True)
    )


def _column_type(t: duckdb.DuckDBPyType) -> ColumnType:
    """DuckDB's type in the platform's coarser terms. JSON is a VARCHAR to DuckDB, so it
    is recognised by name; nested types are JSON to everything above the store."""
    kind = t.id
    if kind in _INTEGERS:
        return ColumnType.INTEGER
    if kind in _NUMBERS:
        return ColumnType.NUMBER
    if kind == "boolean":
        return ColumnType.BOOLEAN
    if kind == "date":
        return ColumnType.DATE
    if kind.startswith("timestamp"):
        return ColumnType.TIMESTAMP
    if str(t) == "JSON" or kind in _NESTED:
        return ColumnType.JSON
    return ColumnType.TEXT


def _check_unique(columns: tuple[Column, ...]) -> None:
    names = [column.name for column in columns]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise Invalid(f"Column names must be unique; repeated: {', '.join(duplicates)}")


def _output(columns: tuple[Column, ...], declared: Schema | None) -> Schema:
    """The snapshot's schema: columns and types from the data, roles from the declaration,
    which may name only columns the data has."""
    if declared is None:
        return Schema(columns=columns, derived=True)
    present = {column.name for column in columns}
    named = [column.name for column in declared.columns] + list(_role_columns(declared.roles))
    missing = sorted({name for name in named if name not in present})
    if missing:
        raise Invalid(f"The declared schema names columns the data lacks: {', '.join(missing)}")
    return Schema(kind=declared.kind, columns=columns, roles=declared.roles, derived=False)


def _role_columns(roles: Roles) -> Iterable[str]:
    if roles.time:
        yield from (roles.time.start, roles.time.end)
    if roles.geo:
        yield roles.geo.code
    for measure in roles.measures:
        yield measure.value
        for name in (measure.lower, measure.upper, measure.suppressed, measure.coverage):
            if name is not None:
                yield name


def _content_hash(
    connection: duckdb.DuckDBPyConnection,
    stored: str,
    types: Sequence[duckdb.DuckDBPyType],
    columns: tuple[Column, ...],
) -> str:
    digest = hashlib.sha256()
    header = [[column.name, str(t)] for column, t in zip(columns, types, strict=True)]
    digest.update(json.dumps(header).encode())
    result = connection.execute(f"SELECT * FROM {stored} ORDER BY ALL")
    # Reading until an empty batch also completes the result, which DuckDB requires
    # before the connection runs anything else.
    while batch := result.fetchmany(_HASH_BATCH):
        for row in batch:
            digest.update(b"\n")
            digest.update(repr(row).encode())
    return digest.hexdigest()


def _plain(value: object) -> object:
    """Values as JSON can carry them: a widget wants 1.5, not "1.5"."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, UUID):
        return str(value)
    return value


def _literal(path: Path) -> str:
    return "'" + str(path).replace("'", "''") + "'"


def _scratch_file(directory: Path) -> Path:
    # A dot-name without the .parquet suffix, so it can never pass for a snapshot.
    return directory / f".{uuid4().hex}.parquet.tmp"
