"""Roles checked before anything runs: declarations against columns, a binding against the
slot it fills (same geography, same period shape), a widget against what its type needs,
and the guard that keeps confidence intervals from surviving an aggregation."""

import re
from pathlib import Path

import httpx
import pytest

from ada.core.models.errors import Invalid
from ada.core.models.operators import Operator
from ada.core.models.schema import (
    Column,
    ColumnType,
    GeoRole,
    MeasureRole,
    OutputKind,
    Roles,
    Schema,
    TimeRole,
)
from ada.core.models.sources import AccessKind, DataFormat
from ada.core.models.time import Grain
from ada.core.services.schema.roles import check_compatible, check_roles, check_widget
from factories import AGENT
from time_world import World

pytestmark = pytest.mark.anyio

COUNTY = GeoRole(code="region", system="statfin", level="wellbeing_services_county")
YEARS = TimeRole(start="period_start", end="period_end", grain=Grain.YEAR)
COLUMNS = (
    Column(name="region", type=ColumnType.TEXT),
    Column(name="period", type=ColumnType.TEXT),
    Column(name="value", type=ColumnType.NUMBER),
    Column(name="lower", type=ColumnType.NUMBER),
    Column(name="upper", type=ColumnType.NUMBER),
    Column(name="period_start", type=ColumnType.DATE),
    Column(name="period_end", type=ColumnType.DATE),
)
BOUNDED = MeasureRole(value="value", lower="lower", upper="upper")
TABLES = {
    "/years.csv": b"region,period,value,lower,upper\n01,2023,70,68,72\n01,2024,71,69,73\n"
    b"90,2023,74,72,76\n90,2024,74.3,72.1,76.5\n",
    "/quarters.csv": b"region,period,value,lower,upper\n01,2024Q1,70,68,72\n",
}


def schema(roles: Roles) -> Schema:
    return Schema(columns=COLUMNS, roles=roles)


class Tables(World):
    """Small CSV sources answered in memory, each declared with the roles it is given."""

    def __init__(self, tmp_path: Path) -> None:
        def answer(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=TABLES[request.url.path])

        super().__init__(tmp_path, transport=httpx.MockTransport(answer))

    async def table(self, path: str, roles: Roles) -> Operator:
        source = await self.sources.register(
            self.project_id,
            name=path,
            access_kind=AccessKind.URL,
            address=f"https://tables.example{path}",
            format=DataFormat.CSV,
            options={"period": {"column": "period"}},
            declared_schema=schema(roles),
        )
        return await self.operator(source)


@pytest.fixture
def world(tmp_path: Path) -> Tables:
    return Tables(tmp_path)


# Declarations


def test_a_period_s_ends_must_be_dates() -> None:
    columns = (*COLUMNS, Column(name="year", type=ColumnType.INTEGER))
    with pytest.raises(Invalid, match="time start needs 'year' to be date or timestamp"):
        check_roles(Roles(time=TimeRole(start="year", end="period_end")), columns)
    check_roles(Roles(time=YEARS), columns)


def test_bounds_come_in_pairs_and_regions_name_their_system() -> None:
    with pytest.raises(Invalid, match="both bounds"):
        check_roles(Roles(measures=(MeasureRole(value="value", lower="lower"),)), COLUMNS)
    with pytest.raises(Invalid, match="code system and a level"):
        check_roles(Roles(geo=GeoRole(code="region", system="", level="county")), COLUMNS)


async def test_a_source_s_declared_roles_are_checked_at_registration(world: Tables) -> None:
    with pytest.raises(Invalid, match="a measure needs 'region'"):
        await world.table("/years.csv", Roles(measures=(MeasureRole(value="region"),)))


# Bindings


def test_a_binding_needs_the_slot_s_geography_and_period_shape() -> None:
    slot = Roles(time=YEARS, geo=COUNTY)
    check_compatible(slot, Roles(time=YEARS, geo=COUNTY, measures=(BOUNDED,)), "it")

    municipalities = COUNTY.model_copy(update={"level": "municipality"})
    with pytest.raises(Invalid, match="municipality in statfin codes"):
        check_compatible(slot, Roles(time=YEARS, geo=municipalities), "it")
    with pytest.raises(Invalid, match="by quarter"):
        check_compatible(
            slot, Roles(time=YEARS.model_copy(update={"grain": "quarter"}), geo=COUNTY), "it"
        )
    with pytest.raises(Invalid, match="no time role"):
        check_compatible(slot, Roles(geo=COUNTY), "it")
    with pytest.raises(Invalid, match="no geography role"):
        check_compatible(slot, Roles(time=YEARS), "it")
    # A slot without roles takes anything with the columns; a slot without a grain any
    # period shape.
    check_compatible(Roles(), Roles(), "it")
    check_compatible(Roles(time=YEARS.model_copy(update={"grain": None})), Roles(time=YEARS), "it")


async def test_a_run_refuses_a_binding_at_another_level_or_grain(world: Tables) -> None:
    years = await world.table("/years.csv", Roles(time=YEARS, geo=COUNTY))
    await world.pipelines.add_input(
        world.project_id, "screening", schema(Roles(time=YEARS, geo=COUNTY)), years.id, AGENT
    )
    quarters = await world.table(
        "/quarters.csv",
        Roles(time=YEARS.model_copy(update={"grain": Grain.QUARTER}), geo=COUNTY),
    )
    unlabelled = await world.transform("SELECT * FROM input_0", years)
    raised = await world.transform(
        "SELECT * REPLACE (greatest(value, 80) AS value) FROM input_0",
        years,
        roles=Roles(time=YEARS, geo=COUNTY, measures=(MeasureRole(value="value"),)),
    )

    with pytest.raises(Invalid, match="its periods are by quarter, the slot's by year"):
        await world.runs.start(world.project_id, AGENT, bindings={"screening": quarters.id})
    with pytest.raises(Invalid, match="declares no time role"):
        await world.runs.start(world.project_id, AGENT, bindings={"screening": unlabelled.id})
    run = await world.runs.start(world.project_id, AGENT, bindings={"screening": raised.id})
    assert run.is_scenario


async def test_an_input_s_default_must_have_its_roles(world: Tables) -> None:
    years = await world.table("/years.csv", Roles(time=YEARS))
    with pytest.raises(Invalid, match="no geography role"):
        await world.pipelines.add_input(
            world.project_id, "screening", schema(Roles(time=YEARS, geo=COUNTY)), years.id, AGENT
        )


# Widgets


@pytest.mark.parametrize(
    ("type", "roles", "spec", "message"),
    [
        ("value", Roles(), {"column": "region"}, "needs a number, and 'region' is text"),
        ("value", Roles(), {"column": "deaths"}, "no column 'deaths'"),
        ("line-chart", Roles(), {"y": "period"}, "`y` needs a number"),
        ("line-chart", Roles(), {"x": "month"}, "no column 'month' for `x`"),
        ("line-chart", Roles(), {"series": "sex"}, "no column 'sex' for `series`"),
        ("table", Roles(), {"columns": ["region", "deaths"]}, "no column 'deaths'"),
        ("map", Roles(), {}, "needs a geography role"),
        ("map", Roles(geo=COUNTY.model_copy(update={"level": "mixed"})), {}, "mixed levels"),
        ("map", Roles(geo=COUNTY), {}, "boundaries in a column 'geometry'"),
        ("map", Roles(geo=COUNTY), {"geometry": "value"}, "must be GeoJSON"),
    ],
)
def test_a_widget_states_what_it_misses(
    type: str, roles: Roles, spec: dict[str, object], message: str
) -> None:
    with pytest.raises(Invalid, match=message):
        check_widget(type, schema(roles), spec)


def test_a_widget_finds_its_defaults_in_roles_or_columns() -> None:
    text_only = Schema(columns=(Column(name="region", type=ColumnType.TEXT),))
    with pytest.raises(Invalid, match="a measure role or a numeric column"):
        check_widget("value", text_only, {})
    with pytest.raises(Invalid, match="needs a number for `y`"):
        check_widget("line-chart", text_only, {})
    check_widget("value", schema(Roles(measures=(BOUNDED,))), {})
    check_widget("line-chart", schema(Roles(time=YEARS)), {"series": "region"})
    with_geometry = Schema(
        columns=(*COLUMNS, Column(name="shape", type=ColumnType.TEXT)), roles=Roles(geo=COUNTY)
    )
    check_widget("map", with_geometry, {"geometry": "shape", "value": "value"})
    # Unknown columns are not held against a widget; roles always are.
    check_widget("value", Schema(), {"column": "anything"})
    with pytest.raises(Invalid, match="geography role"):
        check_widget("map", Schema(), {})
    # Types the platform does not know are the bundle's business.
    check_widget("sparkline", text_only, {})
    with pytest.raises(Invalid, match="shows a table"):
        check_widget("table", Schema(kind=OutputKind.DOCUMENT), {})


async def test_create_widget_returns_invalid_with_the_reason(world: Tables) -> None:
    years = await world.table("/years.csv", Roles(time=YEARS, geo=COUNTY, measures=(BOUNDED,)))

    with pytest.raises(Invalid, match="A map widget cannot show this output: it needs the region"):
        await world.widgets.create(world.project_id, years.id, "map", "Screening", AGENT)
    widget = await world.widgets.create(
        world.project_id, years.id, "line-chart", "Screening", AGENT, spec={"series": "region"}
    )
    assert widget.type == "line-chart"
    assert world.widget_repository.store.widgets == {widget.id: widget}


# The interval guard


@pytest.mark.parametrize(
    ("sql", "reason"),
    [
        (
            "SELECT region, avg(value) AS value, min(lower) AS lower, max(upper) AS upper "
            "FROM input_0 GROUP BY region",
            "GROUP BY",
        ),
        (
            "SELECT avg(value) AS value, min(lower) AS lower, max(upper) AS upper FROM input_0",
            "avg()",
        ),
        (
            "SELECT * REPLACE (avg(value) OVER (PARTITION BY region) AS value) FROM input_0",
            "avg() OVER",
        ),
        ("SELECT DISTINCT * FROM input_0", "DISTINCT"),
        ("SELECT * FROM input_0 UNION SELECT * FROM input_0", "UNION without ALL"),
        (
            "WITH t AS (SELECT region, sum(value) AS value, sum(lower) AS lower, "
            "sum(upper) AS upper FROM input_0 GROUP BY ALL) SELECT * FROM t",
            "GROUP BY",
        ),
        (
            "SELECT s.* FROM (SELECT region, max(value) AS value, max(lower) AS lower, "
            "max(upper) AS upper FROM input_0 GROUP BY region) AS s JOIN input_0 USING (region)",
            "GROUP BY",
        ),
    ],
)
async def test_an_aggregating_transform_cannot_declare_bounds(
    world: Tables, sql: str, reason: str
) -> None:
    years = await world.table("/years.csv", Roles(measures=(BOUNDED,)))

    with pytest.raises(Invalid, match=re.escape(f"aggregates ({reason})")):
        await world.transform(sql, years, roles=Roles(measures=(BOUNDED,)))
    # Without the bounds the same step is fine: the widget then draws no band.
    plain = await world.transform(sql, years, roles=Roles(measures=(MeasureRole(value="value"),)))
    assert plain.output.roles.measures[0].lower is None


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM input_0 WHERE region = '90'",
        # A subquery that only picks the rows keeps them as they are: the latest period.
        "SELECT * FROM input_0 WHERE period_end = (SELECT max(period_end) FROM input_0)",
        "SELECT region, round(value, 1) AS value, lower, upper FROM input_0",
        "SELECT * FROM input_0 UNION ALL SELECT * FROM input_0",
        "SELECT a.* FROM input_0 AS a JOIN input_0 AS b USING (region, period)",
        "SELECT * FROM input_0 WHERE region IN (SELECT region FROM input_0 GROUP BY region)",
    ],
)
async def test_steps_that_keep_rows_keep_their_bounds(world: Tables, sql: str) -> None:
    years = await world.table("/years.csv", Roles(measures=(BOUNDED,)))

    step = await world.transform(sql, years, roles=Roles(measures=(BOUNDED,)))

    assert step.output.roles.measures == (BOUNDED,)


async def test_an_aggregation_without_declared_bounds_is_not_guarded(world: Tables) -> None:
    years = await world.table("/years.csv", Roles(measures=(BOUNDED,)))
    total = await world.transform("SELECT count(*) AS n FROM input_0", years)
    assert total.output.roles == Roles()
