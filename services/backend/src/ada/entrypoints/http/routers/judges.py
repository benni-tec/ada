"""The judges' routes: global defaults per kind (Settings › Global › Judges), a project's
overrides (Settings › This project › Judges), the project's verdicts, and reviewing a
widget again."""

from collections.abc import Sequence

from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter

from ada.core.models.base import UNCHANGED, Change, Id
from ada.core.models.judges import JudgeDefaults, JudgeKind, JudgeSettings, Outcome, Strictness
from ada.core.models.widgets import Widget
from ada.core.services.ports.judges import JudgeService, WidgetReviewService
from ada.core.services.ports.projects import ProjectService
from ada.entrypoints.http.requests import Request

router = APIRouter(route_class=DishkaRoute, tags=["judges"])


class _Change(Request):
    def given[T](self, field: str, value: T) -> Change[T]:
        return value if field in self.model_fields_set else UNCHANGED


class JudgeDefaultsChange(_Change):
    """Fields left out stay as they are. `model_id` null clears the model (reviews are then
    unchecked); `instructions` "" clears them."""

    expected_revision: int
    strictness: Strictness | None = None
    model_id: str | None = None
    instructions: str | None = None


class JudgeOverrideChange(_Change):
    """Fields left out stay as they are; null inherits the global default again."""

    # JudgeSettings.revision: 0 while the project overrides nothing of this kind.
    expected_revision: int
    strictness: Strictness | None = None
    model_id: str | None = None
    instructions: str | None = None


@router.get("/settings/judges", tags=["settings"])
async def get_judge_defaults(service: FromDishka[JudgeService]) -> Sequence[JudgeDefaults]:
    """The global settings of every kind of judge, beside the LLM registry."""
    return await service.defaults()


@router.put("/settings/judges/{kind}", tags=["settings"])
async def set_judge_defaults(
    kind: JudgeKind, body: JudgeDefaultsChange, service: FromDishka[JudgeService]
) -> JudgeDefaults:
    return await service.set_defaults(
        kind,
        body.expected_revision,
        strictness=body.strictness,
        model_id=body.given("model_id", body.model_id),
        instructions=body.instructions,
    )


@router.get("/projects/{project_id}/judges")
async def get_project_judges(
    project_id: Id, service: FromDishka[JudgeService]
) -> Sequence[JudgeSettings]:
    """What the judges use in the project, one per kind, with the fields it overrides."""
    return await service.settings(project_id)


@router.put("/projects/{project_id}/judges/{kind}")
async def override_project_judge(
    project_id: Id, kind: JudgeKind, body: JudgeOverrideChange, service: FromDishka[JudgeService]
) -> JudgeSettings:
    return await service.override(
        project_id,
        kind,
        body.expected_revision,
        strictness=body.given("strictness", body.strictness),
        model_id=body.given("model_id", body.model_id),
        instructions=body.given("instructions", body.instructions),
    )


@router.get("/projects/{project_id}/verdicts")
async def list_verdicts(
    project_id: Id,
    service: FromDishka[WidgetReviewService],
    projects: FromDishka[ProjectService],
    kind: JudgeKind | None = None,
    outcome: Outcome | None = None,
) -> Sequence[Widget]:
    """The project's widgets with a verdict (`Widget.verdict`), newest verdict first."""
    await projects.get(project_id)
    return await service.verdicts(project_id, kind, outcome)


@router.post("/widgets/{widget_id}/review", tags=["widgets"])
async def review_widget(
    widget_id: Id, service: FromDishka[WidgetReviewService], run_id: Id | None = None
) -> Widget:
    """Review a text or custom widget again, in the request: on `run_id`, else on a new run.
    The widget comes back with its verdict."""
    return await service.review(widget_id, run_id)
