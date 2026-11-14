"""Geography: mapping Sotkanet's region ids to the wellbeing services county codes with the
reference sources, joining the county boundaries, and a map widget over the result. All
from the recorded answers of Sotkanet and Statistics Finland's geodata service."""

import json
from pathlib import Path

import pytest

from ada.adapters.sources.examples import (
    REFERENCE,
    SOTKANET_BREAST_SCREENING,
    SOTKANET_REGIONS,
    WELLBEING_COUNTY_BOUNDARIES,
)
from ada.core.models.errors import Invalid
from ada.core.models.operators import Operator
from ada.core.models.schema import GeoRole, MeasureRole, Roles, TimeRole
from ada.core.models.time import Grain
from ada.core.services.schema import geo
from factories import AGENT
from time_world import World

pytestmark = pytest.mark.anyio

# The recipe of ada.core.services.schema.geo: an explicit join with the mapping, and the
# new code system and level declared on the result. A map starts from the boundaries, so
# a county without a value is still drawn, as missing.
TO_COUNTIES = """
SELECT b.county_code, b.name AS county, d.period_start, d.period_end, d.value, b.geometry
FROM input_2 AS b
LEFT JOIN input_1 AS r ON r.code = b.county_code AND r.category = 'HYVINVOINTIALUE'
LEFT JOIN input_0 AS d ON d.region = r.sotkanet_id
ORDER BY county_code, period_start
"""
COUNTY_ROLES = Roles(
    time=TimeRole(start="period_start", end="period_end", grain=Grain.YEAR),
    geo=GeoRole(code="county_code", system=geo.STATFIN, level=geo.WELLBEING_SERVICES_COUNTY),
    measures=(MeasureRole(value="value"),),
)


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World(tmp_path)


async def counties(world: World) -> tuple[Operator, Operator]:
    screening = await world.operator(await world.register(SOTKANET_BREAST_SCREENING))
    regions = await world.operator(await world.register(SOTKANET_REGIONS))
    boundaries = await world.operator(await world.register(WELLBEING_COUNTY_BOUNDARIES))
    mapped = await world.transform(TO_COUNTIES, screening, regions, boundaries, roles=COUNTY_ROLES)
    return screening, mapped


async def test_the_reference_sources_map_every_county(world: World) -> None:
    regions = await world.operator(await world.register(SOTKANET_REGIONS))
    boundaries = await world.operator(await world.register(WELLBEING_COUNTY_BOUNDARIES))
    run = await world.run()

    mapping = [
        row for row in await world.rows(regions, run) if row["category"] == "HYVINVOINTIALUE"
    ]
    shapes = await world.rows(boundaries, run)

    # 21 counties, the City of Helsinki and Åland, with the same codes on both sides.
    assert len(mapping) == len(shapes) == 23
    assert {row["code"] for row in mapping} == {row["county_code"] for row in shapes}
    assert {row["code"]: row["sotkanet_id"] for row in mapping}["90"] == 960
    helsinki = next(row for row in shapes if row["county_code"] == "90")
    geometry = json.loads(str(helsinki["geometry"]))
    assert geometry["type"] in {"Polygon", "MultiPolygon"}
    assert helsinki["name"] == "City of Helsinki"


async def test_a_mapped_measure_feeds_a_map(world: World) -> None:
    _, mapped = await counties(world)
    widget = await world.widgets.create(
        world.project_id, mapped.id, "map", "Breast cancer screening, 2024", AGENT
    )

    data = await world.widgets.data(widget.id, (await world.run(2024, 2024)).id)

    names = [column.name for column in data.columns]
    rows = [dict(zip(names, row, strict=True)) for row in data.rows]
    assert len(rows) == 23
    value = {row["county_code"]: row["value"] for row in rows}
    # The spec's first gap: 74.3% in the City of Helsinki, 85.6% in North Ostrobothnia.
    assert (value["90"], value["19"]) == (74.3, 85.6)
    # Åland runs its own screening and Sotkanet has no value for it: drawn as missing.
    assert value["91"] is None
    assert data.output.roles.geo == COUNTY_ROLES.geo
    assert not data.is_stale


async def test_regions_of_mixed_levels_do_not_make_a_map(world: World) -> None:
    screening, _ = await counties(world)
    with pytest.raises(Invalid, match="mixed levels"):
        await world.widgets.create(world.project_id, screening.id, "map", "Screening", AGENT)


def test_reference_sources_declare_their_regions() -> None:
    for example in REFERENCE:
        assert example.declared_schema is not None
        assert example.declared_schema.roles.geo is not None
    boundaries = WELLBEING_COUNTY_BOUNDARIES.declared_schema
    assert boundaries is not None and boundaries.roles.geo == GeoRole(
        code="county_code", system=geo.STATFIN, level=geo.WELLBEING_SERVICES_COUNTY
    )
