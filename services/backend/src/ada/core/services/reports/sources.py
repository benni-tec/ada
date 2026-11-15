"""The sources list of a report version (docs/spec.md, "Reports"): generated from the
pipelines of its widgets, never written by hand.

It is worked out once, when the version is made, and stored with it. A version is frozen
at its run, so what it rests on cannot change afterwards; storing the list also keeps the
address the data was fetched from, which a later edit of the source would otherwise
overwrite.
"""

from collections.abc import Sequence
from uuid import UUID

from pydantic import TypeAdapter

from ada.core.models.base import Id, JsonObject
from ada.core.models.operators import InputParams, OperatorId, OperatorKind, SourceParams
from ada.core.models.reports import ReportSource
from ada.core.models.runs import Run
from ada.core.models.widgets import Widget
from ada.core.ports.repositories import (
    DataSourceRepository,
    OperatorRepository,
    SnapshotRepository,
)
from ada.core.services.reports.content import SOURCES_KEY

_stored = TypeAdapter(tuple[ReportSource, ...])


class SourcesList:
    def __init__(
        self,
        operators: OperatorRepository,
        snapshots: SnapshotRepository,
        data_sources: DataSourceRepository,
    ) -> None:
        self.operators = operators
        self.snapshots = snapshots
        self.data_sources = data_sources

    @staticmethod
    def read(content: JsonObject) -> tuple[ReportSource, ...]:
        """The list stored in a version's content."""
        return _stored.validate_python(content.get(SOURCES_KEY, []))

    async def build(self, run: Run, widgets: Sequence[Widget]) -> list[JsonObject]:
        """The sources behind the widgets as they read through `run`, ordered by name, as
        stored in a version's content."""
        return [entry.model_dump(mode="json") for entry in await self.entries(run, widgets)]

    async def entries(self, run: Run, widgets: Sequence[Widget]) -> list[ReportSource]:
        """The sources behind the widgets as they read through `run`, ordered by name."""
        uses: dict[OperatorId, list[Id]] = {}
        for widget in widgets:
            # Every input: a text widget's figures come from its named inputs too.
            for input_id in widget.all_inputs().values():
                for operator_id in await self._sources_of(input_id, run):
                    using = uses.setdefault(operator_id, [])
                    if widget.id not in using:
                        using.append(widget.id)
        entries = [await self._entry(operator_id, run, ids) for operator_id, ids in uses.items()]
        entries.sort(key=lambda entry: (entry.name.lower(), entry.operator_id))
        return entries

    async def _sources_of(self, operator_id: OperatorId, run: Run) -> list[OperatorId]:
        """The source operators upstream of an operator, as the run reads it: an input
        bound by the run leads to what it is bound to, not to its default."""
        found: list[OperatorId] = []
        seen: set[OperatorId] = set()
        pending = [operator_id]
        while pending:
            current = pending.pop()
            if current in seen:
                continue
            seen.add(current)
            operator = await self.operators.get(current)
            match operator.kind:
                case OperatorKind.SOURCE:
                    found.append(operator.id)
                case OperatorKind.INPUT:
                    name = InputParams.model_validate(operator.params).name
                    bound = run.bindings.get(name)
                    pending.extend([bound] if bound is not None else operator.inputs)
                case _:
                    pending.extend(operator.inputs)
        return found

    async def _entry(self, operator_id: OperatorId, run: Run, widget_ids: list[Id]) -> ReportSource:
        operator = await self.operators.get(operator_id)
        data_source_id = SourceParams.model_validate(operator.params).data_source_id
        source = await self.data_sources.get(UUID(str(data_source_id)))
        snapshot_id = run.snapshots.get(operator_id)
        snapshot = await self.snapshots.get(snapshot_id) if snapshot_id is not None else None
        return ReportSource(
            data_source_id=source.id,
            name=source.name,
            address=source.address,
            access_kind=source.access_kind,
            format=source.format,
            operator_id=operator_id,
            snapshot_id=snapshot.id if snapshot else None,
            fetched_at=snapshot.fetched_at if snapshot else None,
            content_hash=snapshot.content_hash if snapshot else None,
            widget_ids=tuple(widget_ids),
        )

    async def of_operator(self, run: Run, operator_id: OperatorId) -> list[ReportSource]:
        """The sources behind one operator as `run` read it, ordered by name."""
        entries = [
            await self._entry(source_id, run, [])
            for source_id in dict.fromkeys(await self._sources_of(operator_id, run))
        ]
        entries.sort(key=lambda entry: (entry.name.lower(), entry.operator_id))
        return entries
