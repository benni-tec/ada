from typing import Protocol


class AnalysisStore(Protocol):
    """Where snapshots are stored and queried. Grows with the operator model; for now it
    only reports whether it can be used."""

    async def is_usable(self) -> bool:
        """Whether queries run and the snapshot directory can be written."""
        ...
