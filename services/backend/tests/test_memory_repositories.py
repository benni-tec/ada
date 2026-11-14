"""The memory repositories are the reference for the repository ports' behaviour. The
database repositories must pass the same expectations."""

from datetime import timedelta

import pytest

import factories
from ada.adapters.memory.repositories import (
    MemoryOperatorRepository,
    MemoryProjectRepository,
    MemoryRunRepository,
    MemorySnapshotRepository,
    MemoryStore,
)
from ada.core.models.errors import Conflict, NotFound
from ada.core.models.operators import OperatorKind

pytestmark = pytest.mark.anyio


@pytest.fixture
def store() -> MemoryStore:
    return MemoryStore()


async def test_get_of_an_unknown_id_is_not_found(store: MemoryStore) -> None:
    with pytest.raises(NotFound):
        await MemoryProjectRepository(store).get(factories.project().id)


async def test_update_increases_the_revision(store: MemoryStore) -> None:
    projects = MemoryProjectRepository(store)
    project = factories.project()
    await projects.add(project)

    updated = await projects.update(project.model_copy(update={"name": "Renamed"}), 1)

    assert (updated.name, updated.revision) == ("Renamed", 2)
    assert await projects.get(project.id) == updated


async def test_update_with_a_stale_revision_conflicts_and_changes_nothing(
    store: MemoryStore,
) -> None:
    projects = MemoryProjectRepository(store)
    project = factories.project()
    await projects.add(project)
    await projects.update(project.model_copy(update={"name": "First"}), 1)

    with pytest.raises(Conflict) as error:
        await projects.update(project.model_copy(update={"name": "Second"}), 1)

    assert (error.value.expected, error.value.actual) == (1, 2)
    assert (await projects.get(project.id)).name == "First"


async def test_adding_the_same_operator_twice_keeps_the_first(store: MemoryStore) -> None:
    operators = MemoryOperatorRepository(store)
    project = factories.project()
    first = factories.operator(project.id)
    later = first.model_copy(update={"created_at": first.created_at + timedelta(days=1)})

    assert await operators.add(first) == first
    assert await operators.add(later) == first
    assert len(await operators.list(project.id)) == 1


async def test_upstream_lists_inputs_before_what_uses_them(store: MemoryStore) -> None:
    operators = MemoryOperatorRepository(store)
    project = factories.project()
    source = factories.operator(
        project.id, OperatorKind.SOURCE, {"data_source_id": str(factories.project().id)}
    )
    left = factories.operator(
        project.id, params={"sql": "SELECT 1 FROM input_0"}, inputs=(source.id,)
    )
    right = factories.operator(
        project.id, params={"sql": "SELECT 2 FROM input_0"}, inputs=(source.id,)
    )
    joined = factories.operator(project.id, params={"sql": "join"}, inputs=(left.id, right.id))
    for operator in (source, left, right, joined):
        await operators.add(operator)

    pipeline = [operator.id for operator in await operators.upstream(joined.id)]

    # The shared source appears once, and the operator itself is last.
    assert pipeline == [source.id, left.id, right.id, joined.id]


async def test_reading_finds_the_source_operators_of_a_data_source(store: MemoryStore) -> None:
    operators = MemoryOperatorRepository(store)
    project = factories.project()
    data_source = factories.data_source(project.id)
    source = factories.operator(
        project.id, OperatorKind.SOURCE, {"data_source_id": str(data_source.id)}
    )
    await operators.add(source)
    await operators.add(factories.operator(project.id, inputs=(source.id,)))

    assert await operators.reading(data_source.id) == [source]


async def test_a_superseded_snapshot_is_no_longer_current_but_stays_readable(
    store: MemoryStore,
) -> None:
    snapshots = MemorySnapshotRepository(store)
    project = factories.project()
    operator = factories.operator(project.id)
    old = factories.snapshot(project.id, operator.id, parameters_key="2024")
    await snapshots.add(old)
    assert await snapshots.current(operator.id, "2024") == old
    assert await snapshots.current(operator.id, "2025") is None

    await snapshots.supersede(old.id, factories.NOW)
    new = factories.snapshot(project.id, operator.id, parameters_key="2024", content_hash="def")
    await snapshots.add(new)

    assert await snapshots.current(operator.id, "2024") == new
    assert (await snapshots.get(old.id)).superseded_at == factories.NOW


async def test_a_run_keeps_the_first_snapshot_it_fixed_for_an_operator(store: MemoryStore) -> None:
    runs = MemoryRunRepository(store)
    project = factories.project()
    operator = factories.operator(project.id)
    first = factories.snapshot(project.id, operator.id)
    second = factories.snapshot(project.id, operator.id)
    run = factories.run(project.id)
    await runs.add(run)

    await runs.fix_snapshot(run.id, operator.id, first.id)
    fixed = await runs.fix_snapshot(run.id, operator.id, second.id)

    assert fixed.snapshots == {operator.id: first.id}
