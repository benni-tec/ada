import importlib
import pkgutil
from types import ModuleType


def modules(package: ModuleType) -> list[ModuleType]:
    """Every module directly inside a package, by name. Routers, MCP tools, worker tasks
    and providers are registered this way: adding a feature adds a file, and no shared
    list has to be edited."""
    names = sorted(info.name for info in pkgutil.iter_modules(package.__path__))
    return [importlib.import_module(f"{package.__name__}.{name}") for name in names]
