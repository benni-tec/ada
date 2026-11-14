import re

from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter
from fastapi.responses import FileResponse

from ada.config import Settings
from ada.core.models.errors import NotFound

router = APIRouter(route_class=DishkaRoute, tags=["widgets"])

# A bundle's name is its widget type: a folder name under services/widgets/src/widgets.
# Anything else, a path separator or a dot included, is not a bundle.
BUNDLE_NAME = re.compile(r"[a-z0-9][a-z0-9-]*")


@router.get("/widget-bundles/{name}.html", response_class=FileResponse)
async def widget_bundle(name: str, settings: FromDishka[Settings]) -> FileResponse:
    """A built widget, one self-contained HTML file. The frontend loads it in an iframe as
    `<name>.html#widget=<id>&run=<run>`; the widget then reads its data from this API."""
    path = settings.widgets_dir / f"{name}.html"
    if not BUNDLE_NAME.fullmatch(name) or not path.is_file():
        raise NotFound("widget bundle", name)
    return FileResponse(path, media_type="text/html")
