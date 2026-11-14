"""Files uploaded to ADA, kept under the data directory next to the snapshots.

A file is stored once per content, as files/<project id>/<sha256><suffix>, and read back
by its upload:// address. Nothing outside that directory can be named by an address.
"""

import asyncio
import hashlib
import re
from pathlib import Path

from ada.core.models.base import Id
from ada.core.models.errors import Invalid, NotFound
from ada.core.models.sources import UPLOAD_SCHEME, StoredFile
from ada.core.ports.sources import FileStore

_ADDRESS = re.compile(r"^upload://([0-9a-f-]{36})/([0-9a-f]{64})(\.[a-z0-9]{1,8})?$")
_SUFFIX = re.compile(r"^\.[a-z0-9]{1,8}$")


class LocalFileStore(FileStore):
    def __init__(self, data_dir: Path) -> None:
        self.root = data_dir / "files"

    async def put(self, project_id: Id, content: bytes, suffix: str) -> StoredFile:
        suffix = suffix.lower()
        if suffix and not _SUFFIX.match(suffix):
            raise Invalid(f"Not a file suffix: {suffix!r}")
        sha256 = hashlib.sha256(content).hexdigest()
        path = self.root / str(project_id) / f"{sha256}{suffix}"
        if not path.exists():
            await asyncio.to_thread(_write, path, content)
        address = f"{UPLOAD_SCHEME}{project_id}/{sha256}{suffix}"
        return StoredFile(address=address, sha256=sha256, size=len(content))

    async def get(self, address: str) -> bytes:
        match = _ADDRESS.match(address)
        if match is None:
            raise Invalid(f"Not an upload address: {address!r}")
        project, sha256, suffix = match.groups()
        path = self.root / project / f"{sha256}{suffix or ''}"
        if not path.is_file():
            raise NotFound("uploaded file", address)
        return await asyncio.to_thread(path.read_bytes)


def _write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Written aside and moved, so a reader never sees half a file.
    partial = path.with_name(path.name + ".partial")
    partial.write_bytes(content)
    partial.replace(path)
