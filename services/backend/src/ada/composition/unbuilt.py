from typing import Any, NoReturn


class Unbuilt:
    """Stands in for a port nobody has implemented yet, so the container is complete and
    everything else starts. Using it fails with a message that says what is missing."""

    def __init__(self, port: type) -> None:
        self._port = port.__name__

    def __getattr__(self, name: str) -> NoReturn:
        raise NotImplementedError(f"{self._port} is not implemented yet (called .{name})")


def unbuilt[T](port: type[T]) -> Any:
    """A dishka factory, for use inside a Provider class, that provides the stand-in."""

    def factory(self: object) -> T:
        return Unbuilt(port)  # type: ignore[return-value]

    factory.__annotations__["return"] = port
    return factory
