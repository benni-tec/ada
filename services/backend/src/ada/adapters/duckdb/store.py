import asyncio
import os
from pathlib import Path

import duckdb

from ada.core.ports.analysis import AnalysisStore


class DuckDbAnalysisStore(AnalysisStore):
    """Snapshots are Parquet files under data_dir, written once and never changed. Every
    process queries them with its own in-memory DuckDB, so the API and the workers never
    contend for one database file."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir

    async def is_usable(self) -> bool:
        return await asyncio.to_thread(self._is_usable)

    def _is_usable(self) -> bool:
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            if not os.access(self.data_dir, os.W_OK):
                return False
            with duckdb.connect(":memory:") as connection:
                connection.execute("SELECT 1").fetchone()
        except OSError, duckdb.Error:
            return False
        return True
