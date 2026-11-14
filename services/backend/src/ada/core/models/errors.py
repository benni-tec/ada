class NotFound(Exception):
    """The addressed record does not exist."""

    def __init__(self, kind: str, id: object) -> None:
        super().__init__(f"{kind} {id} not found")
        self.kind = kind
        self.id = id


class Conflict(Exception):
    """A write named a revision that is no longer current: someone else changed the record
    since the caller read it. The caller reads again and retries."""

    def __init__(self, kind: str, id: object, expected: int, actual: int) -> None:
        super().__init__(
            f"{kind} {id} is at revision {actual}, but the write expected revision {expected}"
        )
        self.kind = kind
        self.id = id
        self.expected = expected
        self.actual = actual


class Invalid(Exception):
    """The request is well-formed but breaks a rule of the model, e.g. an input binding
    whose schema does not match, or SQL that does not parse."""


class Unavailable(Exception):
    """An external dependency (a data source, the task queue) could not be reached or
    answered with an error. Nothing is wrong with the request; retrying later may work."""
