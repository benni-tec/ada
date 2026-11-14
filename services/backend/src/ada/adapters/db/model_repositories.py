"""Statistical models and their immutable versions."""

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ada.adapters.db.support import add_row, dump, fetch, oldest_first, require, rows
from ada.adapters.db.tables import ProjectRow, StatisticalModelRow, StatisticalModelVersionRow
from ada.core.models.actors import Actor
from ada.core.models.base import Id
from ada.core.models.errors import NotFound
from ada.core.models.statistical_models import Compiled, ModelSpec, ModelVersion, StatisticalModel
from ada.core.ports.repositories import StatisticalModelRepository


class SqlStatisticalModelRepository(StatisticalModelRepository):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, id: Id) -> StatisticalModel:
        return _model(await fetch(self.session, StatisticalModelRow, id, "statistical model"))

    async def list(self, project_id: Id) -> Sequence[StatisticalModel]:
        statement = oldest_first(StatisticalModelRow, StatisticalModelRow.project_id == project_id)
        return [_model(row) for row in await rows(self.session, statement)]

    async def add(self, model: StatisticalModel) -> None:
        await require(self.session, ProjectRow, model.project_id, "project")
        await add_row(
            self.session,
            StatisticalModelRow(
                id=model.id,
                project_id=model.project_id,
                name=model.name,
                description=model.description,
                kind=model.kind,
                latest_version=model.latest_version,
                created_by=dump(model.created_by),
                created_at=model.created_at,
            ),
        )

    async def add_version(self, version: ModelVersion) -> None:
        model = await fetch(
            self.session, StatisticalModelRow, version.model_id, "statistical model"
        )
        await add_row(
            self.session,
            StatisticalModelVersionRow(
                id=version.id,
                model_id=version.model_id,
                version=version.version,
                spec=dump(version.spec),
                compiled=dump(version.compiled),
                created_by=dump(version.created_by),
                created_at=version.created_at,
            ),
        )
        model.latest_version = max(model.latest_version, version.version)
        await self.session.flush()

    async def version(self, model_id: Id, number: int) -> ModelVersion:
        statement = select(StatisticalModelVersionRow).where(
            StatisticalModelVersionRow.model_id == model_id,
            StatisticalModelVersionRow.version == number,
        )
        row = (await self.session.execute(statement)).scalar_one_or_none()
        if row is None:
            raise NotFound("model version", f"{model_id}/{number}")
        return ModelVersion(
            id=row.id,
            model_id=row.model_id,
            version=row.version,
            spec=ModelSpec.model_validate(row.spec),
            compiled=Compiled.model_validate(row.compiled),
            created_by=Actor.model_validate(row.created_by),
            created_at=row.created_at,
        )


def _model(row: StatisticalModelRow) -> StatisticalModel:
    return StatisticalModel(
        id=row.id,
        project_id=row.project_id,
        name=row.name,
        description=row.description,
        kind=row.kind,
        latest_version=row.latest_version,
        created_by=Actor.model_validate(row.created_by),
        created_at=row.created_at,
    )
