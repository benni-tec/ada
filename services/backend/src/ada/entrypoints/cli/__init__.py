"""The `ada` command: `serve` starts the API, `migrate` prepares the database before
anything can use it, `revision` writes a migration from the model changes."""

import argparse

import uvicorn

from ada.adapters.db.migrate import migrate, write_revision
from ada.config import Settings


def main() -> None:
    parser = argparse.ArgumentParser(prog="ada")
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("serve", help="serve the API (the default)")
    commands.add_parser("migrate", help="bring the database schema up to date")
    revision = commands.add_parser("revision", help="write a migration from the model changes")
    revision.add_argument("message")
    args = parser.parse_args()

    match args.command:
        case "migrate":
            applied = migrate(Settings().database_url)
            for applied_revision in applied:
                print(f"Applied migration {applied_revision}")
            if not applied:
                print("Database schema is up to date")
        case "revision":
            write_revision(Settings().database_url, args.message)
        case _:
            uvicorn.run(
                "ada.entrypoints.http.app:create_app", factory=True, host="0.0.0.0", port=8000
            )
