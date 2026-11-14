"""Make sure the development environment file has a master key (ADA_SECRET_KEY), which
encrypts the model providers' API keys in the database. Run by `moon run :dev` before the
backend and the worker start (backend:secret-key).

Appends a fresh Fernet key when the file has no ADA_SECRET_KEY line, creating the file if
needed. Never changes a key that is there: the keys stored with it would become unreadable.

    python dev_secret_key.py <path to .env.local>
"""

import base64
import os
import re
import sys
from pathlib import Path

DEFINED = re.compile(r"^\s*(export\s+)?ADA_SECRET_KEY\s*=", re.MULTILINE)


def ensure(path: Path) -> bool:
    """True when a key was added."""
    text = path.read_text() if path.exists() else ""
    if DEFINED.search(text):
        return False
    # A Fernet key: 32 random bytes, urlsafe base64.
    key = base64.urlsafe_b64encode(os.urandom(32)).decode()
    separator = "" if not text or text.endswith("\n") else "\n"
    with path.open("a") as file:
        file.write(
            f"{separator}# Encrypts the model providers' API keys in the database. Keep it: "
            f"stored keys cannot be read without it.\nADA_SECRET_KEY={key}\n"
        )
    return True


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".env.local")
    if ensure(target):
        print(f"Added a new ADA_SECRET_KEY to {target}")
