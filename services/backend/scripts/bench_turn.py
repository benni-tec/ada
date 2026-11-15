"""Benchmark one agent turn chain (session, child analysis/research, report-back) in process.

  cd services/backend && ../../.venv/bin/python scripts/bench_turn.py --provider openai \
      --model gpt-6.1-sol --tier fast --thinking low --depth quick \\
      --prompt "..." --csv scripts/bench_data/shortages.csv

Keys come from OPENAI_API_KEY / GEMINI_API_KEY and are never printed. --provider fake uses the
tests' scripted model (no keys). --mode analysis starts the analyst child directly with
the prompt as its brief. Runtime timing lines go to stderr; per-turn JSON lines and a
summary to stdout."""

import argparse
import asyncio
import functools
import http.server
import json
import logging
import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any
from uuid import UUID

BACKEND = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(BACKEND / "tests"), str(BACKEND / "src")]

from dishka import Provider, Scope, provide  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from ada.adapters.llm.runtime import ModelSpeed, PydanticAiRuntime  # noqa: E402
from ada.adapters.secrets.fernet import FernetSecretBox  # noqa: E402
from ada.config import Settings  # noqa: E402
from ada.core.models.agents import FINISHED, ProviderKind  # noqa: E402
from ada.core.ports.agents import AgentRuntime  # noqa: E402
from ada.core.ports.secrets import SecretBox  # noqa: E402
from ada.core.services.ports.agents import AgentSettingsService  # noqa: E402
from ada.entrypoints.http.app import create_app  # noqa: E402
from agent_support import MASTER_KEY, Script, run_turn, say  # noqa: E402
from api_support import dispatcher, send  # noqa: E402
from memory import memory_adapters  # noqa: E402


class Bench(Provider):
    scope = Scope.APP

    def __init__(self, speed: ModelSpeed, factory: Any = None) -> None:
        super().__init__()
        self.speed, self.factory = speed, factory

    @provide
    def secrets(self) -> SecretBox:
        return FernetSecretBox(MASTER_KEY)

    @provide
    def runtime(self) -> AgentRuntime:
        return PydanticAiRuntime(model_factory=self.factory, speed=self.speed)


async def configure(container: Any, provider: str, model: str, key: str | None) -> str:
    kind = ProviderKind.GEMINI if provider == "gemini" else ProviderKind.OPENAI_COMPATIBLE
    # The settings service insists on a base URL for openai-compatible; this one is OpenAI's own,
    # which the runtime treats as base_url None (Responses API, openai_service_tier).
    base_url = {"openai": "https://api.openai.com/v1", "test": "http://127.0.0.1:1/v1"}.get(
        provider
    )
    async with container() as request:
        service = await request.get(AgentSettingsService)
        added = await service.add_provider(provider, kind, base_url, key)
        await service.add_model(added.id, model)
        await service.set_session_agent(f"{provider}/{model}", (await service.view()).revision)
    return f"{provider}/{model}"


def serve_file(csv: Path) -> http.server.ThreadingHTTPServer:
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(csv.parent))
    handler.func.log_message = lambda *a, **k: None  # type: ignore[attr-defined]
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--provider", choices=["openai", "gemini", "fake"], required=True)
    p.add_argument("--model", default="gpt-6.1-sol")
    p.add_argument("--tier", default=None, help="service tier, e.g. fast")
    p.add_argument("--thinking", default=None, help="reasoning effort, e.g. low")
    p.add_argument("--prompt", required=True)
    p.add_argument("--csv", type=Path, required=True)
    p.add_argument("--mode", choices=["session", "analysis"], default="session")
    p.add_argument("--timeout", type=float, default=900)
    p.add_argument("--depth", choices=["quick", "deep"], default="deep")
    args = p.parse_args()

    logging.basicConfig(stream=sys.stderr, level=logging.WARNING, format="%(message)s")
    logging.getLogger("ada.adapters.llm.runtime").setLevel(logging.INFO)

    key = None
    factory = None
    if args.provider == "fake":
        script = Script().then(*[say("Fake answer.")] * 10)
        factory = lambda _id: script.model()  # noqa: E731
        key = "fake"
    else:
        key = os.environ.get("OPENAI_API_KEY" if args.provider == "openai" else "GEMINI_API_KEY")
        if not key:
            sys.exit("Set OPENAI_API_KEY / GEMINI_API_KEY in the environment")

    server = serve_file(args.csv.resolve())
    settings = Settings(
        database_url="postgresql+psycopg://test@127.0.0.1:1/test",
        valkey_url="redis://127.0.0.1:1/0",
        data_dir=Path(tempfile.mkdtemp(prefix="bench_turn_")),
        allow_private_sources=True,
        agent_analysis_depth=args.depth,
    )
    provider = Bench(ModelSpeed(args.tier, args.thinking), factory)
    start = time.monotonic()
    with TestClient(create_app(settings, *memory_adapters(), provider)) as client:
        assert client.portal is not None
        container = client.app.state.dishka_container  # type: ignore[attr-defined]
        client.portal.call(
            configure,
            container,
            args.provider if args.provider != "fake" else "test",
            args.model if args.provider != "fake" else "scripted",
            key,
        )
        project = send(client, "POST", "/projects", {"name": "Bench"}, 201)
        send(
            client,
            "POST",
            f"/projects/{project['id']}/sources",
            {
                "name": "Shortages",
                "access_kind": "url",
                "format": "csv",
                "address": f"http://127.0.0.1:{server.server_port}/{args.csv.name}",
            },
            201,
        )
        session = send(
            client, "POST", f"/projects/{project['id']}/sessions", {"title": "Bench"}, 201
        )
        if args.mode == "analysis":
            send(
                client,
                "POST",
                f"/sessions/{session['id']}/analysis",
                {"brief": args.prompt, "title": "Bench"},
                201,
            )
        else:
            send(client, "POST", f"/sessions/{session['id']}/messages", {"text": args.prompt}, 201)

        queue = dispatcher(client)
        done = 0
        final = ""
        while done < len(queue.turns):
            left = args.timeout - (time.monotonic() - start)
            if left <= 0:
                print(json.dumps({"error": "timeout", "turns_run": done}))
                break
            turn_id = queue.turns[done]
            done += 1
            t0 = time.monotonic()
            try:
                turn = client.portal.call(
                    asyncio.wait_for, run_turn(container, UUID(str(turn_id))), left
                )
            except TimeoutError:
                print(json.dumps({"error": "timeout", "turns_run": done}))
                break
            tools: dict[str, int] = {}
            for part in turn.parts:
                if part.type == "tool":
                    tools[part.tool_name] = tools.get(part.tool_name, 0) + 1
            text = "".join(part.text for part in turn.parts if part.type == "text")
            agent = send(client, "GET", f"/sessions/{turn.session_id}")["agent"]
            if agent == "session" or not final:
                final = text or final
            print(
                json.dumps(
                    {
                        "agent": agent,
                        "status": turn.status.value,
                        "seconds": round(time.monotonic() - t0, 2),
                        "tools": tools,
                        "text_len": len(text),
                        "error": turn.error,
                        "finished": turn.status in FINISHED,
                    }
                ),
                flush=True,
            )
        reports = [
            e["text"]
            for e in send(client, "GET", f"/sessions/{session['id']}/entries")
            if e["kind"] == "report"
        ]
        print(
            json.dumps(
                {
                    "summary": True,
                    "total_seconds": round(time.monotonic() - start, 2),
                    "turns": done,
                    "report": (reports[-1] if reports else "")[:1500],
                    "final_text": final[:1500],
                }
            )
        )
    server.shutdown()


if __name__ == "__main__":
    main()
