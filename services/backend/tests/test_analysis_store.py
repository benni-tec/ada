"""The DuckDB analysis store against real DuckDB and real Parquet files in tmp_path."""

from datetime import date
from pathlib import Path
from uuid import uuid7

import duckdb
import pytest

from ada.adapters.duckdb.store import DuckDbAnalysisStore
from ada.core.models.analysis import FetchedData, Query
from ada.core.models.errors import Invalid, NotFound
from ada.core.models.schema import (
    Column,
    ColumnType,
    GeoRole,
    MeasureRole,
    Roles,
    Schema,
)
from ada.core.models.sources import DataFormat
from factories import NOW

pytestmark = pytest.mark.anyio

PROJECT = uuid7()
CSV = b"region,value,day\nHelsinki,1.5,2024-01-01\nTurku,2,2024-02-01\n"


@pytest.fixture
def store(tmp_path: Path) -> DuckDbAnalysisStore:
    return DuckDbAnalysisStore(tmp_path / "data")


def fetched(content: bytes, format: DataFormat = DataFormat.CSV) -> FetchedData:
    return FetchedData(content=content, format=format, fetched_at=NOW, origin="test")


def snapshot_files(store: DuckDbAnalysisStore) -> list[str]:
    directory = store.data_dir / str(PROJECT)
    return sorted(path.name for path in directory.iterdir()) if directory.exists() else []


def over(location: str, sql: str = "SELECT * FROM s") -> Query:
    return Query(sql=sql, relations={"s": location})


# Writing


async def test_a_csv_becomes_one_parquet_file_with_columns_read_from_the_data(
    store: DuckDbAnalysisStore,
) -> None:
    stored = await store.write(PROJECT, fetched(CSV))

    assert stored.location == f"{PROJECT}/{stored.content_hash}.parquet"
    assert (store.data_dir / stored.location).is_file()
    assert snapshot_files(store) == [f"{stored.content_hash}.parquet"]
    assert stored.row_count == 2
    assert stored.output == Schema(
        columns=(
            Column(name="region", type=ColumnType.TEXT),
            Column(name="value", type=ColumnType.NUMBER),
            Column(name="day", type=ColumnType.DATE),
        ),
        derived=True,
    )
    rows = await store.run(over(stored.location), limit=10)
    assert rows.rows == (("Helsinki", 1.5, date(2024, 1, 1)), ("Turku", 2.0, date(2024, 2, 1)))


async def test_json_arrays_and_newline_delimited_json_are_read_alike(
    store: DuckDbAnalysisStore,
) -> None:
    array = await store.write(
        PROJECT, fetched(b'[{"region": "Turku", "n": 2}, {"region": "Oulu", "n": 3}]', "json")
    )
    lines = await store.write(
        PROJECT, fetched(b'{"region": "Turku", "n": 2}\n{"region": "Oulu", "n": 3}\n', "json")
    )

    assert array.output.columns == (
        Column(name="region", type=ColumnType.TEXT),
        Column(name="n", type=ColumnType.INTEGER),
    )
    assert array.content_hash == lines.content_hash
    assert array.row_count == 2


async def test_nested_json_values_are_json_columns(store: DuckDbAnalysisStore) -> None:
    stored = await store.write(PROJECT, fetched(b'[{"a": {"b": 1}, "c": [1, 2]}]', "json"))
    assert [column.type for column in stored.output.columns] == [ColumnType.JSON] * 2


async def test_parquet_is_read_as_it_is(store: DuckDbAnalysisStore, tmp_path: Path) -> None:
    source = tmp_path / "in.parquet"
    with duckdb.connect() as connection:
        connection.execute(
            f"COPY (SELECT 1 AS id, TRUE AS ok, TIMESTAMP '2024-01-01 10:00' AS at) "
            f"TO '{source}' (FORMAT parquet)"
        )

    stored = await store.write(PROJECT, fetched(source.read_bytes(), DataFormat.PARQUET))

    assert [(c.name, c.type) for c in stored.output.columns] == [
        ("id", ColumnType.INTEGER),
        ("ok", ColumnType.BOOLEAN),
        ("at", ColumnType.TIMESTAMP),
    ]


async def test_identical_data_gets_the_same_hash_whatever_its_layout(
    store: DuckDbAnalysisStore,
) -> None:
    first = await store.write(PROJECT, fetched(CSV))
    again = await store.write(PROJECT, fetched(CSV))
    # Quoted, with CRLF line ends and the rows the other way round: the same table.
    relaid = await store.write(
        PROJECT,
        fetched(b'"region","value","day"\r\n"Turku",2,2024-02-01\r\n"Helsinki",1.5,2024-01-01\r\n'),
    )
    changed = await store.write(PROJECT, fetched(CSV.replace(b"1.5", b"1.6")))

    assert first.content_hash == again.content_hash == relaid.content_hash
    assert first.location == again.location
    assert changed.content_hash != first.content_hash
    # One file per distinct content, and no scratch files left behind.
    assert snapshot_files(store) == sorted(
        f"{h}.parquet" for h in {first.content_hash, changed.content_hash}
    )


async def test_a_declared_schema_adds_roles_to_the_columns_of_the_data(
    store: DuckDbAnalysisStore,
) -> None:
    roles = Roles(
        geo=GeoRole(code="region", system="names", level="city"),
        measures=(MeasureRole(value="value"),),
    )
    declared = Schema(columns=(Column(name="value", type=ColumnType.NUMBER),), roles=roles)

    stored = await store.write(PROJECT, fetched(CSV), declared)

    assert stored.output.roles == roles
    assert stored.output.derived is False
    # Columns still come from the data, all of them.
    assert [column.name for column in stored.output.columns] == ["region", "value", "day"]


@pytest.mark.parametrize(
    "declared",
    [
        Schema(columns=(Column(name="missing", type=ColumnType.TEXT),)),
        Schema(roles=Roles(measures=(MeasureRole(value="value", lower="missing"),))),
    ],
)
async def test_a_declared_schema_naming_absent_columns_is_invalid(
    store: DuckDbAnalysisStore, declared: Schema
) -> None:
    with pytest.raises(Invalid, match="missing"):
        await store.write(PROJECT, fetched(CSV), declared)
    assert snapshot_files(store) == []


@pytest.mark.parametrize(
    ("content", "format"),
    [(b"", DataFormat.CSV), (b"[{not json", DataFormat.JSON), (b"nope", DataFormat.PARQUET)],
)
async def test_unreadable_data_is_invalid(
    store: DuckDbAnalysisStore, content: bytes, format: DataFormat
) -> None:
    with pytest.raises(Invalid):
        await store.write(PROJECT, fetched(content, format))
    assert snapshot_files(store) == []


# Describing


async def test_describe_names_the_columns_without_running_the_query(
    store: DuckDbAnalysisStore,
) -> None:
    stored = await store.write(PROJECT, fetched(CSV))
    # Running this would take a very long time; describing only binds it.
    query = over(
        stored.location,
        "SELECT region, sum(value) AS total, count(*) AS n,"
        " (SELECT sum(x) FROM range(1000000000000) t(x)) AS huge FROM s GROUP BY region",
    )

    assert await store.describe(query) == (
        Column(name="region", type=ColumnType.TEXT),
        Column(name="total", type=ColumnType.NUMBER),
        Column(name="n", type=ColumnType.INTEGER),
        Column(name="huge", type=ColumnType.INTEGER),
    )


@pytest.mark.parametrize(
    "sql",
    [
        "SELEC region FROM s",
        "SELECT nope FROM s",
        "SELECT * FROM missing_table",
        "SELECT 1; SELECT 2",
        "CREATE TABLE x AS SELECT 1",
        "",
    ],
)
async def test_describe_rejects_bad_sql_and_unknown_names(
    store: DuckDbAnalysisStore, sql: str
) -> None:
    stored = await store.write(PROJECT, fetched(CSV))
    with pytest.raises(Invalid):
        await store.describe(over(stored.location, sql))


# Running


async def test_run_returns_at_most_limit_rows_and_says_when_there_are_more(
    store: DuckDbAnalysisStore,
) -> None:
    query = Query(sql="SELECT x, x * 1.5::DECIMAL(4, 1) AS y FROM range(5) t(x) ORDER BY x DESC")

    some = await store.run(query, limit=2)
    every = await store.run(query, limit=5)

    assert some.rows == ((4, 6.0), (3, 4.5))
    assert some.truncated is True
    assert len(every.rows) == 5
    assert every.truncated is False
    assert some.columns == (
        Column(name="x", type=ColumnType.INTEGER),
        Column(name="y", type=ColumnType.NUMBER),
    )


async def test_run_fails_as_invalid_when_the_query_fails(store: DuckDbAnalysisStore) -> None:
    with pytest.raises(Invalid, match="failed"):
        await store.run(Query(sql="SELECT CAST('x' AS INTEGER)"), limit=1)


# Materializing


async def test_materialize_stores_the_query_result_as_a_snapshot(
    store: DuckDbAnalysisStore,
) -> None:
    source = await store.write(PROJECT, fetched(CSV))

    copy = await store.materialize(PROJECT, over(source.location))
    total = await store.materialize(PROJECT, over(source.location, "SELECT sum(value) AS t FROM s"))

    # The same table, by whatever route, is the same content.
    assert copy.content_hash == source.content_hash
    assert copy.location == source.location
    assert total.row_count == 1
    assert total.output.columns == (Column(name="t", type=ColumnType.NUMBER),)
    assert (await store.run(over(total.location), 1)).rows == ((3.5,),)


# Guarding


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM read_csv('{other}')",
        "SELECT * FROM read_text('/etc/passwd')",
        "SELECT * FROM read_parquet('{data}/*/*.parquet')",
        "COPY (SELECT 1) TO '{other}'",
        "ATTACH '{other}.db'",
        "INSTALL httpfs",
        "SET enable_external_access = true",
    ],
)
async def test_queries_cannot_reach_other_files(
    store: DuckDbAnalysisStore, tmp_path: Path, sql: str
) -> None:
    other = tmp_path / "secret.csv"
    other.write_text("secret\n1\n")
    stored = await store.write(PROJECT, fetched(CSV))
    query = over(stored.location, sql.format(other=other, data=store.data_dir))

    with pytest.raises(Invalid):
        await store.run(query, limit=10)
    with pytest.raises(Invalid):
        await store.materialize(PROJECT, query)


@pytest.mark.parametrize("location", ["../outside.parquet", "/etc/passwd", "x/y.csv"])
async def test_relations_must_be_snapshots_in_the_data_directory(
    store: DuckDbAnalysisStore, location: str
) -> None:
    with pytest.raises(Invalid):
        await store.run(over(location), limit=1)


async def test_relation_names_must_be_plain_identifiers(store: DuckDbAnalysisStore) -> None:
    stored = await store.write(PROJECT, fetched(CSV))
    query = Query(sql="SELECT 1", relations={'s" AS SELECT 1; --': stored.location})
    with pytest.raises(Invalid):
        await store.run(query, limit=1)


async def test_a_missing_snapshot_is_not_found(store: DuckDbAnalysisStore) -> None:
    with pytest.raises(NotFound):
        await store.run(over(f"{PROJECT}/{'0' * 64}.parquet"), limit=1)
