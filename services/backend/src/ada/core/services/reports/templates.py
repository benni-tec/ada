from collections.abc import Sequence
from uuid import uuid7

from ada.core.models.base import Id, JsonObject
from ada.core.models.dashboards import Slot
from ada.core.models.errors import Invalid, NotFound
from ada.core.models.reports import Template, TemplateKind
from ada.core.ports.repositories import ProjectRepository, TemplateRepository, WidgetRepository
from ada.core.ports.system import Clock
from ada.core.services.ports.reports import TemplateService
from ada.core.services.reports import content as tree

# Dashboards lay their slots out on a grid of this many columns.
GRID_COLUMNS = 12
LAYOUT_KEYS = ("x", "y", "w", "h")


class Templates(TemplateService):
    """Report templates (a tree with named slots, filled by widgets when a report is made
    from it) and dashboard templates (slots with a place on the grid)."""

    def __init__(
        self,
        templates: TemplateRepository,
        projects: ProjectRepository,
        widgets: WidgetRepository,
        clock: Clock,
    ) -> None:
        self.templates = templates
        self.projects = projects
        self.widgets = widgets
        self.clock = clock

    async def create(
        self,
        project_id: Id,
        name: str,
        kind: TemplateKind,
        slots: Sequence[Slot],
        content: JsonObject | None = None,
    ) -> Template:
        await self.projects.get(project_id)
        name = name.strip()
        if not name:
            raise Invalid("A template needs a name")
        await self._check_slots(project_id, slots)
        template = Template(
            id=uuid7(),
            project_id=project_id,
            name=name,
            kind=kind,
            slots=tuple(slots),
            content=_content(kind, slots, content),
            created_at=self.clock.now(),
        )
        await self.templates.add(template)
        return template

    async def get(self, id: Id) -> Template:
        return await self.templates.get(id)

    async def list(self, project_id: Id) -> Sequence[Template]:
        await self.projects.get(project_id)
        return await self.templates.list(project_id)

    async def _check_slots(self, project_id: Id, slots: Sequence[Slot]) -> None:
        if not slots:
            raise Invalid("A template needs at least one slot")
        names = [slot.name.strip() for slot in slots]
        if any(name != slot.name or not name for name, slot in zip(names, slots, strict=True)):
            raise Invalid("Slot names must be non-blank, without surrounding spaces")
        repeated = sorted({name for name in names if names.count(name) > 1})
        if repeated:
            raise Invalid(f"Slot names must be unique; repeated: {repeated}")
        for slot in slots:
            _check_layout(slot)
            if slot.widget_id is not None:
                try:
                    widget = await self.widgets.get(slot.widget_id)
                except NotFound:
                    raise Invalid(
                        f"Slot {slot.name!r}: widget {slot.widget_id} does not exist"
                    ) from None
                if widget.project_id != project_id:
                    raise Invalid(f"Slot {slot.name!r}: the widget belongs to another project")


def _content(kind: TemplateKind, slots: Sequence[Slot], content: JsonObject | None) -> JsonObject:
    names = [slot.name for slot in slots]
    if kind is TemplateKind.DASHBOARD:
        if content:
            raise Invalid("A dashboard template has no content tree: its slots are its layout")
        return {}
    if not content:
        # Without a tree, the slots in their order make one.
        blocks: tuple[tree.Block, ...] = tuple(
            tree.WidgetBlock(type="widget", slot=name) for name in names
        )
    else:
        blocks = tree.parse(content, tree.Tree.TEMPLATE)
    placed = tree.slot_names(blocks)
    undeclared = sorted(set(placed) - set(names))
    if undeclared:
        raise Invalid(f"The tree places slots that are not declared: {undeclared}")
    unplaced = [name for name in names if name not in placed]
    if unplaced:
        raise Invalid(f"Every slot must appear in the tree; not placed: {unplaced}")
    return {tree.BLOCKS_KEY: tree.dump(blocks)}


def _check_layout(slot: Slot) -> None:
    """A slot's place on the grid, when it has one: {x, y, w, h} in grid cells."""
    if not slot.layout:
        return
    unknown = sorted(set(slot.layout) - set(LAYOUT_KEYS))
    if unknown:
        raise Invalid(f"Slot {slot.name!r}: layout has unknown keys {unknown}; use x, y, w, h")
    values = {key: slot.layout.get(key, 0) for key in LAYOUT_KEYS}
    if not all(isinstance(v, int) and not isinstance(v, bool) and v >= 0 for v in values.values()):
        raise Invalid(f"Slot {slot.name!r}: x, y, w and h are whole numbers of at least 0")
    if values["x"] + values["w"] > GRID_COLUMNS:
        raise Invalid(f"Slot {slot.name!r}: the grid has {GRID_COLUMNS} columns")
