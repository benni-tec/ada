"""The `ada` command: `serve` starts the API, `migrate` prepares the database before
anything can use it, `revision` writes a migration from the model changes, `openapi`
prints the API's schema, `seed-demo` creates the health demo's project, `seed-waits` the
project of waiting times read off the wellbeing areas' pages."""

import argparse
import asyncio
import json

import uvicorn

from ada.adapters.db.migrate import migrate, write_revision
from ada.composition import create_container
from ada.config import Settings
from ada.entrypoints.cli.seed import seed_demo
from ada.entrypoints.cli.waiting_times import seed_waits
from ada.entrypoints.http.app import create_app


def main() -> None:
    parser = argparse.ArgumentParser(prog="ada")
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("serve", help="serve the API (the default)")
    commands.add_parser("migrate", help="bring the database schema up to date")
    revision = commands.add_parser("revision", help="write a migration from the model changes")
    revision.add_argument("message")
    commands.add_parser("openapi", help="print the OpenAPI schema of the API")
    seed = commands.add_parser(
        "seed-demo", help="create the demo project with its sources, unless it exists"
    )
    seed.add_argument(
        "--refresh", action="store_true", help="queue a refresh of its sources for the worker"
    )
    waits = commands.add_parser(
        "seed-waits", help="create the waiting-times project on the wellbeing areas' pages"
    )
    waits.add_argument(
        "--refresh", action="store_true", help="fetch the pages now and check the alert rule"
    )
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
        case "seed-demo":
            asyncio.run(_seed_demo(args.refresh))
        case "seed-waits":
            asyncio.run(_seed_waits(args.refresh))
        case "openapi":
            # Building the app connects to nothing, so the schema needs no real settings.
            settings = Settings(
                database_url="postgresql+psycopg://unused/", valkey_url="redis://unused"
            )
            print(json.dumps(create_app(settings).openapi(), indent=2, sort_keys=True))
        case _:
            uvicorn.run(
                "ada.entrypoints.http.app:create_app", factory=True, host="0.0.0.0", port=8000
            )


async def _seed_demo(refresh: bool) -> None:
    container = create_container(Settings())
    try:
        await seed_demo(container, refresh)
    finally:
        await container.close()


async def _seed_waits(refresh: bool) -> None:
    container = create_container(Settings())
    try:
        await seed_waits(container, refresh)
    finally:
        await container.close()
