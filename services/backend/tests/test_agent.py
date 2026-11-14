"""The in-platform agent: messages that queue turns, turns that run the
scripted model (pydantic-ai's FunctionModel, agent_support.py) with the platform's own MCP
tools in process, and their parts stored and streamed. No provider is ever called.

The REST routes run in a TestClient; a turn runs as the worker's task would, on the app's
container, in the client's event loop."""

import asyncio
import json
from collections.abc import AsyncIterator, Iterator, Sequence
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid7

import pytest
from dishka import AsyncContainer, Provider, Scope, provide
from fastapi.testclient import TestClient
from fastmcp import Client
from mcp.types import Implementation
from openai import AsyncOpenAI
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, DeltaToolCall
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from taskiq import InMemoryBroker

import factories
from ada.adapters.memory.events import MemoryEventBus
from ada.adapters.memory.repositories import MemoryStore
from ada.adapters.sources.web import WebPageReader
from ada.composition import create_container
from ada.config import Settings
from ada.core.models.actors import Actor, ActorKind
from ada.core.models.agents import AgentTurn, ProviderKind, ResearchLimits, ToolPart, TurnStatus
from ada.core.models.agents import TextPart as AnswerText
from ada.core.models.base import Id
from ada.core.models.sessions import EntryKind
from ada.core.models.sources import AccessKind
from ada.core.models.web import SearchHit, SearchScope
from ada.core.ports.agents import ResearchCalls, ToolCallFailed, TurnProgress
from ada.core.ports.sources import SourceReaders
from ada.core.ports.system import Clock
from ada.core.ports.web import WebBudget, WebSearch
from ada.core.services.agents import service as agent_service
from ada.core.services.agents.research import ResearchReaders, researching
from ada.core.services.ports.agents import AgentTurnService, ResearchService
from ada.core.services.ports.projects import ProjectService
from ada.core.services.ports.sessions import SessionService
from ada.core.services.ports.sources import SourceService
from ada.core.services.sessions.service import Sessions
from ada.entrypoints.mcp.agent import CLIENT, LEFT_OUT, RESEARCH_TOOLS, InProcessToolbox
from ada.entrypoints.mcp.server import create_mcp
from ada.entrypoints.worker import create_broker
from agent_support import (
    AGENT,
    MODEL,
    AgentOverrides,
    Script,
    call,
    config,
    configure,
    fail,
    returned,
    run_turn,
    say,
)
from api_support import FakeWeb, Overrides, dispatcher, events, new_project, send, serve
from conftest import settings_in
from fakes import FakeExplorer, FakeSourceReaders, FakeWebSearch, FixedClock
from memory import MemoryBackground, memory_adapters

pytestmark = pytest.mark.anyio

WEB = {"kind": "user", "name": "web"}
RESEARCHER = "test/researcher"
RESEARCH_AGENT = {"kind": "agent", "name": RESEARCHER}
# The research sessions' web call cap in this module's app.
WEB_CALLS = 3


# Turns, through the REST routes


@pytest.fixture(scope="module")
def agent() -> AgentOverrides:
    return AgentOverrides(Script())


@pytest.fixture(scope="module")
def web() -> tuple[FakeWebSearch, FakeExplorer]:
    hit = SearchHit(url="https://stat.fi/a", title="A", snippet="s")
    return FakeWebSearch(hits=[hit]), FakeExplorer()


@pytest.fixture(scope="module")
def client(
    unreachable_settings: Settings,
    agent: AgentOverrides,
    web: tuple[FakeWebSearch, FakeExplorer],
) -> Iterator[TestClient]:
    settings = unreachable_settings.model_copy(update={"research_web_calls": WEB_CALLS})
    with serve(settings, Overrides(), agent, FakeWeb(*web)) as client:
        # One provider with its key, one model, the session agent: as the Settings page sets.
        assert client.portal is not None
        client.portal.call(configure, container(client), config())
        # A second model of it runs research sessions.
        [provider] = send(client, "GET", "/settings/agent")["providers"]
        send(
            client,
            "POST",
            "/settings/llm-models",
            {"provider_id": provider["id"], "model": "researcher"},
            201,
        )
        revision = send(client, "GET", "/settings/agent")["revision"]
        chosen = send(
            client,
            "PUT",
            "/settings/research-agent",
            {"model_id": RESEARCHER, "expected_revision": revision},
        )
        assert chosen["research_agent"] == RESEARCHER
        yield client


@pytest.fixture
def script(agent: AgentOverrides) -> Script:
    """The model's script, empty for each test."""
    agent.script.steps.clear()
    agent.script.calls.clear()
    agent.script.before_step = None
    agent.factory = None
    return agent.script


@pytest.fixture
def project(client: TestClient) -> dict[str, Any]:
    return new_project(client)


@pytest.fixture
def source(client: TestClient, project: dict[str, Any]) -> dict[str, Any]:
    return send(
        client,
        "POST",
        f"/projects/{project['id']}/sources",
        {
            "name": "Sotkanet",
            "access_kind": "url",
            "address": "https://example.test/screening.csv",
            "format": "csv",
        },
        201,
    )


@pytest.fixture
def session(client: TestClient, project: dict[str, Any]) -> dict[str, Any]:
    return send(client, "POST", f"/projects/{project['id']}/sessions", {"title": "Screening"}, 201)


def container(client: TestClient) -> Any:
    return client.app.state.dishka_container  # type: ignore[attr-defined]


def message(client: TestClient, session: dict[str, Any], text: str, **body: Any) -> Any:
    return send(client, "POST", f"/sessions/{session['id']}/messages", {"text": text, **body}, 201)


def run(client: TestClient, turn_id: str) -> AgentTurn:
    assert client.portal is not None
    return client.portal.call(run_turn, container(client), UUID(turn_id))


def turn_events(client: TestClient, session: dict[str, Any], *types: str) -> list[Any]:
    return [
        e
        for e in events(client, session["project_id"])
        if e.type.startswith("agent.") and (not types or e.type in types)
    ]


def build_a_table(project: dict[str, Any], source: dict[str, Any]) -> list[Any]:
    """Reads the source, puts a table on it, and says so. The model leaves out session_id:
    the turn's session is filled in."""
    return [
        call(
            "add_source_operator",
            {"project_id": project["id"], "data_source_id": source["id"], "note": "the data"},
        ),
        call(
            "create_widget",
            lambda messages: {
                "operator_id": returned(messages, "add_source_operator")["id"],
                "type": "table",
                "title": "Screening by region",
                "note": "Participation per region",
            },
        ),
        say("I made ", "a table."),
    ]


def test_a_message_queues_a_turn_after_its_entry(
    client: TestClient, session: dict[str, Any], script: Script
) -> None:
    posted = message(client, session, "Show screening")

    entry, turn = posted["entry"], posted["turn"]
    assert (turn["status"], turn["model"], turn["parts"]) == ("queued", MODEL, [])
    assert turn["prompt_entry_id"] == entry["id"]
    entries = send(client, "GET", f"/sessions/{session['id']}/entries")
    assert [(e["kind"], e["actor"], e["ref"]) for e in entries] == [
        ("message", WEB, None),
        ("agent_turn", AGENT, turn["id"]),
    ]
    # Queued once the message's unit of work committed; announced the same way.
    assert UUID(turn["id"]) in dispatcher(client).turns
    kinds = [event.type for event in events(client, session["project_id"])]
    assert kinds.index("agent.turn_started") > kinds.index("session.entry_added")
    unknown = client.post(
        f"/api/sessions/{session['id']}/messages", json={"text": "Hi", "model": "other/x"}
    )
    assert (unknown.status_code, "other/x" in unknown.json()["detail"]) == (422, True)
    assert client.get(f"/api/turns/{uuid7()}").status_code == 404


def test_a_turn_needs_a_session_agent_with_its_key(unreachable_settings: Settings) -> None:
    for llms in (None, config(key=None, kind=ProviderKind.GEMINI)):
        with serve(unreachable_settings, Overrides(), AgentOverrides(Script())) as app:
            assert app.portal is not None
            app.portal.call(configure, container(app), llms)
            project = new_project(app)
            session = send(app, "POST", f"/projects/{project['id']}/sessions", {"title": "S"}, 201)
            turn = message(app, session, "Hello")["turn"]
            models = send(app, "GET", "/llm/models")
            assert dispatcher(app).turns == []
            if llms is not None:
                assert turn["status"] == "failed"
                assert turn["error"] == "The provider test needs an API key"
                assert models["models"][0]["available"] is False
            else:
                assert turn is None
                assert models == {"models": [], "session_agent": None, "research_agent": None}
                refused = app.post(
                    f"/api/sessions/{session['id']}/research", json={"brief": "b", "title": "t"}
                )
                assert (refused.status_code, refused.json()["detail"]) == (
                    422,
                    "No research agent model is configured",
                )


def test_context_is_checked_stored_with_the_message_and_reaches_the_prompt(
    client: TestClient,
    project: dict[str, Any],
    source: dict[str, Any],
    session: dict[str, Any],
    script: Script,
) -> None:
    operator = send(
        client,
        "POST",
        f"/projects/{project['id']}/operators",
        {"kind": "source", "data_source_id": source["id"]},
        201,
    )
    dashboard = send(
        client, "POST", f"/projects/{project['id']}/dashboards", {"name": "Screening"}, 201
    )
    widget = send(
        client,
        "POST",
        f"/projects/{project['id']}/widgets",
        {"operator_id": operator["id"], "type": "table", "title": "Regions"},
        201,
    )
    elsewhere = new_project(client, "Other")
    foreign = send(client, "POST", f"/projects/{elsewhere['id']}/dashboards", {"name": "X"}, 201)
    path = f"/api/sessions/{session['id']}/messages"
    for wrong, status in [
        ({"kind": "dashboard", "dashboard_id": foreign["id"]}, 422),
        ({"kind": "pipeline", "operator_id": "op_missing"}, 404),
        ({"kind": "chart", "id": "x"}, 422),
    ]:
        assert client.post(path, json={"text": "a", "context": [wrong]}).status_code == status
    context = [
        {"kind": "pipeline", "operator_id": operator["id"]},
        {"kind": "dashboard", "dashboard_id": dashboard["id"], "slot": " headline "},
        {"kind": "widget", "widget_id": widget["id"]},
    ]
    script.then(say("Noted."))

    posted = message(client, session, "Add this", context=context)
    run(client, posted["turn"]["id"])

    assert posted["entry"]["context"][1]["slot"] == "headline"
    instructions = script.calls[0][1].instructions or ""
    assert 'A pipeline to build on: "Sotkanet"' in instructions
    assert f'"Screening", id {dashboard["id"]}' in instructions
    assert 'in its slot "headline"' in instructions
    assert f'"Regions", id {widget["id"]}' in instructions
    assert f'Session "Screening", id {session["id"]}' in instructions
    assert "Never state a number you did not read from a tool" in instructions


def test_people_s_instructions_follow_ada_s_rules_in_order_and_are_cut(
    client: TestClient, project: dict[str, Any], session: dict[str, Any], script: Script
) -> None:
    settings = send(client, "GET", "/settings/agent")
    pasted = "Context.dev skill: " + "x" * 25_000
    send(
        client,
        "PUT",
        "/settings/agent-instructions",
        {"instructions": pasted, "expected_revision": settings["revision"]},
    )
    send(
        client,
        "PATCH",
        f"/projects/{project['id']}",
        {"agent_instructions": "Answer in English.", "expected_revision": project["revision"]},
    )
    script.then(say("Noted."))
    try:
        run(client, message(client, session, "Hello")["turn"]["id"])
    finally:
        # The client is shared by the module's tests.
        cleared = send(client, "GET", "/settings/agent")
        send(
            client,
            "PUT",
            "/settings/agent-instructions",
            {"instructions": "", "expected_revision": cleared["revision"]},
        )

    instructions = script.calls[0][1].instructions or ""
    rules = instructions.index("Never state a number you did not read from a tool")
    every = instructions.index("Instructions for every project:")
    this = instructions.index("Instructions for this project:")
    assert rules < every < this
    assert pasted[:20_000] + "\n[Cut at 20,000 characters.]" in instructions
    assert pasted[:20_001] not in instructions
    assert instructions[this:].rstrip().endswith("Answer in English.")


def test_a_turn_builds_with_the_tools_and_streams_its_parts(
    client: TestClient,
    project: dict[str, Any],
    source: dict[str, Any],
    session: dict[str, Any],
    script: Script,
) -> None:
    script.then(*build_a_table(project, source))
    turn_id = message(client, session, "Show screening")["turn"]["id"]

    finished = run(client, turn_id)

    stored = send(client, "GET", f"/turns/{turn_id}")
    assert stored == finished.model_dump(mode="json")
    assert (stored["status"], stored["error"]) == ("done", None)
    parts = stored["parts"]
    assert [(p["type"], p.get("tool_name"), p.get("state")) for p in parts] == [
        ("tool", "add_source_operator", "output-available"),
        ("source", None, None),
        ("tool", "create_widget", "output-available"),
        ("text", None, None),
    ]
    operator, widget = parts[0]["output"], parts[2]["output"]["widget"]
    assert parts[1] == {
        "type": "source",
        "source_id": source["id"],
        "title": "Sotkanet",
        "url": "https://example.test/screening.csv",
    }
    assert parts[3]["text"] == "I made a table."
    # Recorded in the session as the agent, like an external agent's work.
    entries = send(client, "GET", f"/sessions/{session['id']}/entries")
    assert [(e["kind"], e["actor"], e["ref"]) for e in entries] == [
        ("message", WEB, None),
        ("agent_turn", AGENT, turn_id),
        ("operator", AGENT, operator["id"]),
        ("widget", AGENT, widget["id"]),
    ]
    assert widget["session_id"] == session["id"]
    # A tool call is shown when made, then replaced by its result; text grows in place.
    published = turn_events(client, session)
    assert [e.type for e in (published[0], published[-1])] == [
        "agent.turn_started",
        "agent.turn_finished",
    ]
    assert published[-1].payload["status"] == "done"
    assert [
        (e.payload["index"], e.payload["part"]["type"], e.payload["part"].get("state"))
        for e in published
        if e.type == "agent.turn_part"
    ] == [
        (0, "tool", "input-available"),
        (0, "tool", "output-available"),
        (1, "source", None),
        (2, "tool", "input-available"),
        (2, "tool", "output-available"),
        (3, "text", None),
        (3, "text", None),
    ]


def test_a_part_is_live_before_it_is_stored(
    client: TestClient, session: dict[str, Any], script: Script
) -> None:
    seen: dict[str, Any] = {}
    turn_id = message(client, session, "Hi")["turn"]["id"]

    async def streaming(messages: Any, info: Any) -> Any:
        yield "Hello"
        bus = await container(client).get(MemoryEventBus)
        store = await container(client).get(MemoryStore)
        seen["live"] = [
            e.payload["part"]
            for e in bus.published
            if e.type == "agent.turn_part" and e.payload["turn_id"] == turn_id
        ]
        seen["stored"] = store.agent_turns[UUID(turn_id)].parts
        yield " there"

    script.then(streaming)
    run(client, turn_id)

    assert seen["live"] == [{"type": "text", "text": "Hello"}]
    assert seen["stored"] == ()
    assert send(client, "GET", f"/turns/{turn_id}")["parts"] == [
        {"type": "text", "text": "Hello there"}
    ]


def test_the_second_turn_is_told_the_conversation_so_far(
    client: TestClient,
    project: dict[str, Any],
    source: dict[str, Any],
    session: dict[str, Any],
    script: Script,
) -> None:
    script.then(*build_a_table(project, source))
    first = message(client, session, "Show screening")["turn"]["id"]
    run(client, first)
    widget_id = send(client, "GET", f"/turns/{first}")["parts"][2]["output"]["widget"]["id"]

    script.then(say("By year, then."))
    second = message(client, session, "And by year?")["turn"]["id"]
    run(client, second)

    messages = script.calls[-1][0]
    prompts = [
        part.content
        for m in messages
        if isinstance(m, ModelRequest)
        for part in m.parts
        if isinstance(part, UserPromptPart)
    ]
    answers = [
        part.content
        for m in messages
        if isinstance(m, ModelResponse)
        for part in m.parts
        if isinstance(part, TextPart)
    ]
    assert prompts == ["Show screening", "And by year?"]
    [answer] = answers
    assert "I made a table." in answer
    assert f"[called create_widget: widget {widget_id}]" in answer
    assert "[read data source Sotkanet" in answer


def test_a_turn_is_cancelled_while_queued_or_at_its_next_step(
    client: TestClient, project: dict[str, Any], session: dict[str, Any], script: Script
) -> None:
    queued = message(client, session, "Hi")["turn"]["id"]
    response = client.post(f"/api/turns/{queued}/cancel")
    never_ran = run(client, queued)
    running = message(client, session, "Again")["turn"]["id"]

    async def cancel(step: int) -> None:
        # Someone presses stop while the model is answering its first request.
        if step == 1:
            async with container(client)() as request:
                await (await request.get(AgentTurnService)).cancel(UUID(running))

    script.before_step = cancel
    script.then(call("list_pipelines", {"project_id": project["id"]}), say("never"))
    stopped = run(client, running)

    assert (response.status_code, response.json()["status"]) == (202, "cancelled")
    assert never_ran.status == "cancelled"
    # The tool call the model asked for was not made.
    assert (stopped.status, stopped.parts, len(script.calls)) == ("cancelled", (), 1)
    finished = turn_events(client, session, "agent.turn_finished")
    # The running one is announced as it stops and again once settled.
    assert [e.payload["status"] for e in finished] == ["cancelled"] * 3


def test_a_failing_or_unreachable_provider_ends_the_turn_as_failed(
    client: TestClient, session: dict[str, Any], script: Script, agent: AgentOverrides
) -> None:
    script.then(fail(ModelHTTPError(503, "scripted", "overloaded")))
    failing = run(client, message(client, session, "Hi")["turn"]["id"])
    # A real OpenAI client against a port nobody listens on: refused at once, no network.
    unreachable = AsyncOpenAI(base_url="http://127.0.0.1:1/v1", api_key="x", max_retries=0)
    agent.factory = lambda model_id: OpenAIChatModel(
        "any", provider=OpenAIProvider(openai_client=unreachable)
    )
    refused = run(client, message(client, session, "Hi")["turn"]["id"])

    assert failing.status == refused.status == "failed"
    assert (failing.error or "").startswith("The model provider answered with an error")
    assert "could not be reached" in (refused.error or "")


def test_a_call_timing_out_before_the_turn_limit_ends_the_turn_as_failed(
    client: TestClient, session: dict[str, Any], script: Script
) -> None:
    script.then(fail(TimeoutError("upstream")))
    failed = run(client, message(client, session, "Hi")["turn"]["id"])

    assert failed.status == "failed"
    assert failed.error == "The turn failed unexpectedly: TimeoutError: upstream"


def test_a_turn_that_cannot_finish_fails(
    client: TestClient,
    project: dict[str, Any],
    source: dict[str, Any],
    session: dict[str, Any],
    script: Script,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script.then(
        call("add_source_operator", {"project_id": project["id"], "data_source_id": source["id"]}),
        *[
            call(
                "add_transform",
                lambda messages: {
                    "project_id": project["id"],
                    "sql": "nonsense",
                    "inputs": [returned(messages, "add_source_operator")["id"]],
                },
            )
            for _ in range(6)
        ],
    )
    refused = run(client, message(client, session, "Hi")["turn"]["id"])
    # The refusals ended the turn before the script did.
    script.steps.clear()
    monkeypatch.setattr(agent_service, "MAX_STEPS", 2)
    script.then(*[call("list_pipelines", {"project_id": project["id"]}) for _ in range(4)])
    too_long = run(client, message(client, session, "Hi")["turn"]["id"])
    script.steps.clear()
    monkeypatch.setattr(agent_service, "TURN_TIME_LIMIT", timedelta(seconds=0.2))
    script.then(hang)
    too_slow = run(client, message(client, session, "Hi")["turn"]["id"])

    # A tool that keeps refusing.
    assert refused.status == "failed"
    assert "add_transform" in (refused.error or "")
    errors = [p for p in refused.parts if getattr(p, "state", None) == "output-error"]
    assert errors
    assert all(p.error_text == "Not a query: nonsense" for p in errors)  # type: ignore[union-attr]
    assert (too_long.status, too_long.error) == (
        "failed",
        "The agent did not finish within 2 steps",
    )
    assert too_slow.status == "failed"
    assert (too_slow.error or "").startswith("The turn did not finish within")


async def hang(messages: Any, info: Any) -> AsyncIterator[str]:
    await asyncio.sleep(10)
    yield "Too late."


# The research agent, in child sessions


BRIEF = "Find five-year cancer survival by hospital district in Finland"


def delegate(client: TestClient, session: dict[str, Any], title: str = "Survival") -> Any:
    return send(
        client, "POST", f"/sessions/{session['id']}/research", {"brief": BRIEF, "title": title}, 201
    )


def entries(client: TestClient, session: dict[str, Any]) -> list[Any]:
    return send(client, "GET", f"/sessions/{session['id']}/entries")  # type: ignore[no-any-return]


def latest_turn(client: TestClient, session: dict[str, Any]) -> str:
    return send(client, "GET", f"/sessions/{session['id']}/turns")[-1]["id"]  # type: ignore[no-any-return]


def tool_names(info: Any) -> set[str]:
    return {tool.name for tool in info.function_tools}


def last_prompt(script: Script) -> str:
    messages = script.calls[-1][0]
    return [
        part.content
        for m in messages
        if isinstance(m, ModelRequest)
        for part in m.parts
        if isinstance(part, UserPromptPart)
    ][-1]


async def every_tool(app: Any) -> set[str]:
    async with Client(create_mcp(app)) as mcp:
        return {tool.name for tool in await mcp.list_tools()}


def test_delegate_creates_child_and_queues_research_turn(
    client: TestClient, session: dict[str, Any], script: Script
) -> None:
    child = delegate(client, session)

    assert (child["agent"], child["parent_session_id"], child["project_id"], child["title"]) == (
        "research",
        session["id"],
        session["project_id"],
        "Survival",
    )
    [delegation] = entries(client, session)
    assert (delegation["kind"], delegation["actor"], delegation["ref"], delegation["text"]) == (
        "delegation",
        WEB,
        child["id"],
        "Survival",
    )
    brief, queued = entries(client, child)
    [turn] = send(client, "GET", f"/sessions/{child['id']}/turns")
    assert (brief["kind"], brief["actor"], brief["text"]) == ("message", WEB, BRIEF)
    assert (turn["status"], turn["model"], turn["prompt_entry_id"]) == (
        "queued",
        RESEARCHER,
        brief["id"],
    )
    assert (queued["kind"], queued["ref"]) == ("agent_turn", turn["id"])
    assert UUID(turn["id"]) in dispatcher(client).turns


def test_research_turn_gets_only_research_tools(
    client: TestClient, session: dict[str, Any], script: Script
) -> None:
    script.then(say("Hello."))
    run(client, message(client, session, "Hi")["turn"]["id"])
    child = delegate(client, session)
    script.then(say("Nothing found."))
    run(client, latest_turn(client, child))

    assert client.portal is not None
    everything = client.portal.call(every_tool, container(client))
    (_, session_info), (_, research_info) = script.calls
    assert tool_names(research_info) == RESEARCH_TOOLS & everything
    assert tool_names(session_info) == everything - LEFT_OUT - {"report_back"}
    assert "delegate_research" in tool_names(session_info)
    assert "report_back" in (research_info.instructions or "")
    assert f'Session "Survival", id {child["id"]}' in (research_info.instructions or "")


def test_the_research_agent_reads_people_s_instructions_after_its_own_rules(
    client: TestClient, session: dict[str, Any], script: Script
) -> None:
    project = send(client, "GET", f"/projects/{session['project_id']}")
    send(
        client,
        "PATCH",
        f"/projects/{project['id']}",
        {"agent_instructions": "Prefer THL.", "expected_revision": project["revision"]},
    )
    child = delegate(client, session)
    script.then(say("Nothing found."))
    run(client, latest_turn(client, child))

    instructions = script.calls[-1][1].instructions or ""
    assert "You are the research agent of ADA" in instructions
    rules = instructions.index("Finish with report_back")
    assert rules < instructions.index("Instructions for this project:")
    assert instructions.rstrip().endswith("Prefer THL.")


def test_person_follow_up_in_research_session_uses_research_model(
    client: TestClient, session: dict[str, Any], script: Script
) -> None:
    child = delegate(client, session)
    script.then(
        call("report_back", {"summary": "Found it.", "source_ids": [], "missing": []}),
        say("Reported."),
    )
    run(client, latest_turn(client, child))
    follow_up = message(client, child, "And the 2023 figures?")["turn"]
    script.then(say("Looking."))
    run(client, follow_up["id"])

    assert follow_up["model"] == RESEARCHER
    (_, first), (_, _), (_, second) = script.calls
    assert tool_names(second) == tool_names(first)
    assert second.instructions == first.instructions


def test_report_back_posts_into_parent_without_turn_when_person_delegated(
    client: TestClient,
    source: dict[str, Any],
    session: dict[str, Any],
    script: Script,
) -> None:
    child = delegate(client, session)
    script.then(
        call(
            "report_back",
            {
                "summary": "Five-year survival by district, 2019-2023.",
                "source_ids": [source["id"]],
                "missing": ["Figures for 2024"],
            },
        ),
        say("Done."),
    )
    finished = run(client, latest_turn(client, child))

    delegation, report = entries(client, session)
    assert finished.status == "done"
    assert (report["kind"], report["ref"], report["actor"]) == (
        "report",
        child["id"],
        RESEARCH_AGENT,
    )
    assert report["text"] == (
        "Five-year survival by district, 2019-2023.\n\n"
        f"Sources added:\n- Sotkanet, source {source['id']}\n\n"
        "Not found:\n- Figures for 2024"
    )
    assert send(client, "GET", f"/sessions/{session['id']}/turns") == []


def test_report_back_queues_parent_turn_when_agent_delegated(
    client: TestClient, session: dict[str, Any], script: Script
) -> None:
    script.then(
        call("delegate_research", {"brief": BRIEF, "title": "Survival"}),
        say("I asked for research."),
    )
    run(client, message(client, session, "How does survival differ by district?")["turn"]["id"])
    *_, delegation = entries(client, session)
    child = send(client, "GET", f"/sessions/{delegation['ref']}")
    script.then(
        call(
            "report_back",
            {"summary": "No district figures exist.", "source_ids": [], "missing": ["Districts"]},
        ),
        say("Done."),
    )
    run(client, latest_turn(client, child))

    *_, report, queued = entries(client, session)
    _, second = send(client, "GET", f"/sessions/{session['id']}/turns")
    assert (delegation["kind"], delegation["actor"], child["agent"]) == (
        "delegation",
        AGENT,
        "research",
    )
    assert entries(client, child)[0]["actor"] == AGENT
    assert (report["kind"], queued["kind"], queued["ref"]) == ("report", "agent_turn", second["id"])
    assert (second["status"], second["model"], second["prompt_entry_id"]) == (
        "queued",
        MODEL,
        report["id"],
    )
    assert UUID(second["id"]) in dispatcher(client).turns
    # The session agent reads the report as its prompt.
    script.then(say("I will build on that."))
    run(client, second["id"])
    assert "No district figures exist." in last_prompt(script)


def test_research_turn_without_report_posts_incomplete_report_once(
    client: TestClient, session: dict[str, Any], script: Script
) -> None:
    child = delegate(client, session)
    turn_id = latest_turn(client, child)
    script.then(say("Statistics Finland ", "has no such table."))
    run(client, turn_id)
    run(client, turn_id)
    # A person's follow-ups in the research session are a conversation of their own.
    script.then(say("THL has none either."), fail(ModelHTTPError(503, "scripted", "overloaded")))
    for text in ("Look at THL too", "And Eurostat?"):
        run(client, message(client, child, text)["turn"]["id"])

    _, report = entries(client, session)
    assert report["text"] == (
        "Statistics Finland has no such table.\n\n(incomplete: ended without a report)"
    )
    assert report["actor"] == RESEARCH_AGENT


def test_failed_research_turn_reports_failure(
    client: TestClient, session: dict[str, Any], script: Script
) -> None:
    child = delegate(client, session)
    script.then(fail(ModelHTTPError(503, "scripted", "overloaded")))
    failed = run(client, latest_turn(client, child))

    _, report = entries(client, session)
    assert failed.status == "failed"
    assert report["text"] == f"Research failed: {failed.error}"


def test_a_research_turn_that_cannot_be_queued_reports_its_failure(
    client: TestClient, session: dict[str, Any], script: Script, monkeypatch: pytest.MonkeyPatch
) -> None:
    recording = dispatcher(client)
    queue, refused = recording.run_turn, []

    async def queue_unless_first(turn_id: Id) -> None:
        if not refused:
            refused.append(turn_id)
            raise ConnectionError("Valkey is unreachable")
        await queue(turn_id)

    script.then(
        call("delegate_research", {"brief": BRIEF, "title": "Survival"}),
        say("I asked for research."),
    )
    first = message(client, session, "How does survival differ by district?")["turn"]["id"]
    monkeypatch.setattr(recording, "run_turn", queue_unless_first)
    run(client, first)

    *_, delegation, report, queued = entries(client, session)
    [unqueued] = send(client, "GET", f"/sessions/{delegation['ref']}/turns")
    _, second = send(client, "GET", f"/sessions/{session['id']}/turns")
    assert [UUID(unqueued["id"])] == refused
    assert (unqueued["status"], unqueued["error"]) == (
        "failed",
        "The turn could not be queued: Valkey is unreachable",
    )
    assert (report["kind"], report["actor"], report["text"]) == (
        "report",
        RESEARCH_AGENT,
        f"Research failed: {unqueued['error']}",
    )
    # The session agent delegated, so it hears of the failure in a turn of its own.
    assert (queued["ref"], second["prompt_entry_id"]) == (second["id"], report["id"])
    assert UUID(second["id"]) in recording.turns


def test_web_call_cap(
    client: TestClient,
    session: dict[str, Any],
    script: Script,
    web: tuple[FakeWebSearch, FakeExplorer],
) -> None:
    search, pages = web
    search.searches.clear()
    pages.calls.clear()
    child = delegate(client, session)
    project = {"project_id": child["project_id"]}
    script.then(
        *[call("search_web", {**project, "query": f"survival {i}"}) for i in range(WEB_CALLS)],
        call("read_page", {**project, "url": "https://stat.fi/a"}),
        say("Out of calls."),
    )
    capped = run(client, latest_turn(client, child))
    script.then(call("search_web", {**project, "query": "one more"}), say("Still out."))
    again = run(client, message(client, child, "Try once more")["turn"]["id"])

    refusal = (
        f"This research session has used its {WEB_CALLS} web calls; "
        "call report_back with what you have"
    )
    tools = [p for p in capped.parts if isinstance(p, ToolPart)]
    assert [(p.tool_name, p.state) for p in tools] == [
        *[("search_web", "output-available")] * WEB_CALLS,
        ("read_page", "output-error"),
    ]
    assert tools[-1].error_text == refusal
    assert again.parts[0].error_text == refusal  # type: ignore[union-attr]
    assert (len(search.searches), pages.calls) == (WEB_CALLS, [])


# The agent's tools: the MCP server in process, acting as the agent


TOOL_AGENT = Actor(kind=ActorKind.AGENT, name="gemini/flash")


async def test_the_agent_gets_every_tool_it_can_use_and_acts_in_its_session(
    client: TestClient, project: dict[str, Any], source: dict[str, Any], session: dict[str, Any]
) -> None:
    app = container(client)
    async with Client(create_mcp(app)) as mcp:
        everything = {tool.name for tool in await mcp.list_tools()}

    # Handed a request-scoped container, as the worker's task does: the tools find the APP
    # container above it themselves (above APP is dishka's RUNTIME, where no service is).
    async with (
        app() as task_scope,
        InProcessToolbox(task_scope).connect(TOOL_AGENT, session["id"]) as tools,
    ):
        names = {spec.name for spec in tools.specs()}
        # The turn fills in its session, so the model need not.
        required = {spec.name: spec.input_schema.get("required", []) for spec in tools.specs()}
        operator = await tools.call(
            "add_source_operator",
            {"project_id": project["id"], "data_source_id": source["id"], "note": "why"},
        )
        listed = await tools.call("list_pipelines", {"project_id": project["id"]})
        with pytest.raises(ToolCallFailed, match="Not a query"):
            await tools.call(
                "add_transform", {"project_id": project["id"], "sql": "nope", "inputs": []}
            )
        with pytest.raises(ToolCallFailed, match="no tool"):
            await tools.call("get_widget_data", {"widget_id": str(uuid7())})

    assert names == everything - LEFT_OUT - {"report_back"}
    assert not [name for name, fields in required.items() if "session_id" in fields]
    assert {"list_pipelines", "create_widget", "pin_widget"} <= names
    # Its calls, the failed ones too, show in its turn: the record has no tool call entries.
    [entry] = send(client, "GET", f"/sessions/{session['id']}/entries")
    assert (entry["kind"], entry["ref"], entry["text"]) == ("operator", operator["id"], "why")
    assert entry["actor"] == TOOL_AGENT.model_dump(mode="json")
    # A list comes unwrapped, as the tool returned it.
    assert [p["operator_id"] for p in listed] == [operator["id"]]


async def test_an_outside_client_cannot_pass_for_the_agent(
    client: TestClient, project: dict[str, Any], source: dict[str, Any], session: dict[str, Any]
) -> None:
    # Over MCP, a client may report any name, including the in-process client's.
    app = container(client)
    async with Client(create_mcp(app), client_info=CLIENT) as mcp:
        await mcp.call_tool(
            "add_source_operator",
            {
                "project_id": project["id"],
                "data_source_id": source["id"],
                "session_id": session["id"],
            },
        )
    impostor = Implementation(name="gemini/flash", version="1")
    entries = send(client, "GET", f"/sessions/{session['id']}/entries")
    async with Client(create_mcp(app), client_info=impostor) as mcp:
        await mcp.call_tool(
            "create_widget",
            {
                "operator_id": entries[0]["ref"],
                "type": "table",
                "title": "T",
                "session_id": session["id"],
            },
        )

    entries = send(client, "GET", f"/sessions/{session['id']}/entries")
    # Each call made its entry and was recorded as a tool call, both as the client it is.
    assert [(e["kind"], e["actor"]["kind"], e["actor"]["name"]) for e in entries] == [
        ("operator", "external_agent", CLIENT.name),
        ("tool_call", "external_agent", CLIENT.name),
        ("widget", "external_agent", "gemini/flash"),
        ("tool_call", "external_agent", "gemini/flash"),
    ]


# The worker

RUN_TURN = "ada.entrypoints.worker.tasks.agent:run_turn"


async def two_turns(container: AsyncContainer) -> list[Id]:
    """Two messages in a new session, and the turns they queued."""
    async with container() as request:
        project = await (await request.get(ProjectService)).create("P")
        session = await (await request.get(SessionService)).create(project.id, "S")
    turns = []
    for text in ("Hi", "Hello?"):
        async with container() as request:
            posted = await (await request.get(AgentTurnService)).post_message(
                session.id, text, Actor(kind=ActorKind.USER, name="web")
            )
        assert posted.turn is not None
        turns.append(posted.turn.id)
    return turns


async def get_turn(container: AsyncContainer, id: Id) -> AgentTurn:
    async with container() as request:
        return await (await request.get(AgentTurnService)).get(id)


async def test_the_worker_task_runs_a_turn_after_the_earlier_turns_of_its_session(
    unreachable_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(agent_service, "WAIT_POLL", 0.01)
    script = Script()
    broker = create_broker(
        unreachable_settings,
        *memory_adapters(),
        Overrides(),
        AgentOverrides(script),
        in_memory=True,
    )
    assert isinstance(broker, InMemoryBroker)
    app_container = broker.middlewares[0]._container  # type: ignore[attr-defined]
    await broker.startup()
    try:
        await configure(app_container, config())
        turns = await two_turns(app_container)
        script.then(say("Hello from the worker."), say("Still here."))

        task = broker.find_task(RUN_TURN)
        assert task is not None
        # Two turns of one session can run at once in the worker: the second waits.
        second = await task.kiq(turn_id=str(turns[1]))
        await asyncio.sleep(0.1)
        waiting = await get_turn(app_container, turns[1])
        first = await (await task.kiq(turn_id=str(turns[0]))).wait_result(timeout=5)
        result = await second.wait_result(timeout=5)
        assert not first.is_err and not result.is_err, (first.error, result.error)

        done = [await get_turn(app_container, id) for id in turns]
        assert (waiting.status, [turn.status for turn in done]) == ("queued", ["done", "done"])
        assert [turn.parts[0].text for turn in done] == [  # type: ignore[union-attr]
            "Hello from the worker.",
            "Still here.",
        ]
    finally:
        await broker.shutdown()


async def test_a_turn_left_running_past_the_time_limit_fails_before_the_next_runs(
    unreachable_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(agent_service, "WAIT_POLL", 0.01)
    script, overrides = Script(), Overrides()
    broker = create_broker(
        unreachable_settings,
        *memory_adapters(),
        overrides,
        AgentOverrides(script),
        in_memory=True,
    )
    assert isinstance(broker, InMemoryBroker)
    app_container = broker.middlewares[0]._container  # type: ignore[attr-defined]
    await broker.startup()
    try:
        await configure(app_container, config())
        stuck, turn = await two_turns(app_container)
        # The worker running the first turn died: it is left running.
        assert await (await app_container.get(TurnProgress)).start(stuck, overrides.clock.now())
        seen = []

        async def look(step: int) -> None:
            seen.append((await get_turn(app_container, stuck)).status)

        script.before_step = look
        script.then(say("Hello again."))
        task = broker.find_task(RUN_TURN)
        assert task is not None
        waiting = await task.kiq(turn_id=str(turn))
        await asyncio.sleep(0.1)
        within_limit = (await get_turn(app_container, turn)).status
        bound = agent_service.TURN_TIME_LIMIT + agent_service.TURN_MARGIN
        overrides.clock.advance(seconds=bound.total_seconds() + 1)
        result = await waiting.wait_result(timeout=5)
        assert not result.is_err, result.error

        failed, done = [await get_turn(app_container, id) for id in (stuck, turn)]
        assert within_limit == "queued"
        assert (failed.status, failed.error) == ("failed", agent_service.ABANDONED)
        # Failed before the next turn started: never two running at once.
        assert (seen, done.status) == (["failed"], "done")
    finally:
        await broker.shutdown()


PERSON = Actor(kind=ActorKind.USER, name="web")


async def research_turn(container: AsyncContainer, parent_id: Id, brief: str) -> AgentTurn:
    """Research a person delegates from the session, and its turn on the brief."""
    async with container() as request:
        child = await (await request.get(ResearchService)).delegate(parent_id, brief, brief, PERSON)
        [turn] = await (await request.get(AgentTurnService)).turns(child.id)
    return turn


class WebSourceReaders(Provider):
    """The composition's readers, but web sources read with `explorer`."""

    def __init__(self, explorer: FakeExplorer) -> None:
        super().__init__()
        self.explorer = explorer

    @provide(scope=Scope.APP)
    def readers(
        self, calls: ResearchCalls, limits: ResearchLimits, budget: WebBudget
    ) -> SourceReaders:
        web = WebPageReader(self.explorer, budget, FixedClock(), 300)
        return ResearchReaders(FakeSourceReaders({AccessKind.WEB: web}), calls, limits)


async def test_a_research_turn_counts_every_document_read_it_queues(
    unreachable_settings: Settings,
) -> None:
    container = create_container(unreachable_settings, *memory_adapters())
    try:
        async with container() as request:
            project = await (await request.get(ProjectService)).create("P")
            sessions = await request.get(SessionService)
            parent = await sessions.create(project.id, "S")
            child = await sessions.create_research(
                parent.id, "R", Actor(kind=ActorKind.USER, name="web")
            )
            research = await request.get(ResearchService)
            with researching(child.id):
                # Parsed locally now, but the turn may switch it to Context.dev before the
                # worker reads it. A URL source is never a paid read.
                for kind in (AccessKind.DOCUMENT, AccessKind.URL):
                    await research.use_source_read(
                        factories.data_source(project.id, access_kind=kind)
                    )
        store = await container.get(MemoryStore)
    finally:
        await container.close()

    assert store.web_calls == {child.id: 1}


async def test_a_research_turn_counts_its_web_calls_whatever_session_it_names(
    unreachable_settings: Settings,
) -> None:
    script = Script()
    search, explorer = FakeWebSearch(), FakeExplorer()
    settings = unreachable_settings.model_copy(update={"research_web_calls": 3})
    container = create_container(
        settings,
        *memory_adapters(),
        FakeWeb(search, explorer),
        WebSourceReaders(explorer),
        AgentOverrides(script),
    )
    try:
        await configure(container, config())
        async with container() as request:
            project = await (await request.get(ProjectService)).create("P")
            parent = await (await request.get(SessionService)).create(project.id, "S")
        turn = await research_turn(container, parent.id, "Survival by district")
        page = {
            "project_id": str(project.id),
            "name": "THL page",
            "address": "https://thl.fi/survival",
            "access_kind": "web",
            "format": "html",
        }
        on_project = {"project_id": str(project.id)}
        script.then(
            # Its parent's session, as if that spent nothing.
            call("search_web", {**on_project, "query": "survival", "session_id": str(parent.id)}),
            call("register_source", page),
            call(
                "add_source_operator",
                lambda m: {
                    "project_id": str(project.id),
                    "data_source_id": returned(m, "register_source")["id"],
                    "session_id": str(parent.id),
                },
            ),
            # Reads the page in this call, then queues a read in the worker.
            call(
                "preview_operator",
                lambda m: {"operator_id": returned(m, "add_source_operator")["id"]},
            ),
            call("refresh_source", lambda m: {"source_id": returned(m, "register_source")["id"]}),
            call("read_page", {**on_project, "url": "https://thl.fi/other"}),
            say("Out of calls."),
        )
        ran = await run_turn(container, turn.id)
        store = await container.get(MemoryStore)
        async with container() as request:
            parent_record = await (await request.get(SessionService)).entries(parent.id)
    finally:
        await container.close()

    tools = [(p.tool_name, p.state) for p in ran.parts if isinstance(p, ToolPart)]
    assert tools == [
        *[
            (name, "output-available")
            for name in (
                "search_web",
                "register_source",
                "add_source_operator",
                "preview_operator",
                "refresh_source",
            )
        ],
        ("read_page", "output-error"),
    ]
    assert store.web_calls == {turn.session_id: 3}
    assert [(name, arguments["url"]) for name, arguments in explorer.calls] == [
        ("read", "https://thl.fi/survival")
    ]
    # It works in its own session only: the parent has the delegation and the report.
    assert [entry.kind for entry in parent_record] == [EntryKind.DELEGATION, EntryKind.REPORT]


RECOVER_TURNS = "ada.entrypoints.worker.tasks.agent:recover_turns"


async def test_research_whose_worker_died_is_ended_and_reported_by_the_recovery(
    unreachable_settings: Settings,
) -> None:
    overrides = Overrides()
    broker = create_broker(
        unreachable_settings,
        *memory_adapters(),
        overrides,
        AgentOverrides(Script()),
        in_memory=True,
    )
    assert isinstance(broker, InMemoryBroker)
    app_container = broker.middlewares[0]._container  # type: ignore[attr-defined]
    await broker.startup()
    try:
        await configure(app_container, config())
        async with app_container() as request:
            project = await (await request.get(ProjectService)).create("P")
            parent = await (await request.get(SessionService)).create(project.id, "S")
        running = await research_turn(app_container, parent.id, "Survival")
        ended = await research_turn(app_container, parent.id, "Deaths")
        reported = await research_turn(app_container, parent.id, "Births")
        # The workers stopped: one while its turn ran, one right after report_back stored
        # its report (before the turn stored the call), one right after its turn ended.
        progress, now = await app_container.get(TurnProgress), overrides.clock.now()
        for turn in (running, ended, reported):
            assert await progress.start(turn.id, now)
        async with app_container() as request:
            await (await request.get(SessionService)).record_report(
                reported.session_id, "Births by region.", Actor(kind=ActorKind.AGENT, name=MODEL)
            )
        await progress.finish(
            ended.id, TurnStatus.DONE, (AnswerText(text="No deaths table."),), None, now
        )

        async def recover() -> list[str]:
            task = broker.find_task(RECOVER_TURNS)
            assert task is not None
            result = await (await task.kiq()).wait_result(timeout=5)
            assert not result.is_err, result.error
            async with app_container() as request:
                entries = await (await request.get(SessionService)).entries(parent.id)
            return [entry.text for entry in entries if entry.kind is EntryKind.REPORT]

        early = await recover()
        bound = agent_service.TURN_TIME_LIMIT + agent_service.TURN_MARGIN
        overrides.clock.advance(seconds=bound.total_seconds() + 1)
        await recover()
        reports = await recover()
        failed = await get_turn(app_container, running.id)
    finally:
        await broker.shutdown()

    assert early == ["Births by region."]
    assert (failed.status, failed.error) == ("failed", agent_service.ABANDONED)
    assert reports == [
        "Births by region.",
        f"Research failed: {agent_service.ABANDONED}",
        "No deaths table.\n\n(incomplete: ended without a report)",
    ]


async def test_a_research_report_that_failed_is_posted_once_by_the_recovery(
    migrated_database_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script, clock = Script(), FixedClock()
    clocks = Provider(scope=Scope.APP)
    clocks.provide(lambda: clock, provides=Clock)
    settings = settings_in(tmp_path, migrated_database_url)
    container = create_container(settings, MemoryBackground(), clocks, AgentOverrides(script))
    record, failures = Sessions.record_report, [ConnectionError("The database went away")]

    async def record_then_fail(self: Sessions, *args: Any) -> Any:
        entry = await record(self, *args)
        if failures:
            raise failures.pop()
        return entry

    async def reports() -> list[str]:
        async with container() as request:
            entries = await (await request.get(SessionService)).entries(parent.id)
        return [entry.text for entry in entries if entry.kind is EntryKind.REPORT]

    try:
        await configure(container, config())
        async with container() as request:
            project = await (await request.get(ProjectService)).create("P")
            parent = await (await request.get(SessionService)).create(project.id, "S")
        turn = await research_turn(container, parent.id, "Survival")
        monkeypatch.setattr(Sessions, "record_report", record_then_fail)
        script.then(say("No survival table."))
        await run_turn(container, turn.id)
        lost = await reports()
        clock.advance(seconds=agent_service.TURN_MARGIN.total_seconds() + 1)
        for _ in range(2):
            async with container() as request:
                await (await request.get(AgentTurnService)).recover()
        recovered = await reports()
    finally:
        await container.close()

    # The report written before the failure was rolled back with the turn's settling.
    assert (failures, lost) == ([], [])
    assert recovered == ["No survival table.\n\n(incomplete: ended without a report)"]


class StalledSearch(FakeWebSearch):
    """A search that waits until it is let go, like a worker that stalls."""

    def __init__(self) -> None:
        super().__init__()
        self.called, self.go_on = asyncio.Event(), asyncio.Event()

    async def search(self, query: str, scope: SearchScope, limit: int) -> Sequence[SearchHit]:
        self.called.set()
        await self.go_on.wait()
        return await super().search(query, scope, limit)


async def test_a_turn_failed_while_its_worker_stalled_stays_failed(
    migrated_database_url: str, tmp_path: Path
) -> None:
    script, clock, search = Script(), FixedClock(), StalledSearch()
    stalls = Provider(scope=Scope.APP)
    stalls.provide(lambda: clock, provides=Clock)
    stalls.provide(lambda: search, provides=WebSearch)
    settings = settings_in(tmp_path, migrated_database_url)
    container = create_container(settings, MemoryBackground(), stalls, AgentOverrides(script))
    try:
        await configure(container, config())
        stalled, following = await two_turns(container)
        async with container() as request:
            session = await (await request.get(SessionService)).get(
                (await get_turn(container, stalled)).session_id
            )
        source = {
            "project_id": str(session.project_id),
            "name": "Late",
            "address": "https://example.test/late.csv",
        }

        search_q = {"project_id": str(session.project_id), "query": "q"}

        async def search_then_register(messages: Any, info: AgentInfo) -> AsyncIterator[Any]:
            yield {
                0: DeltaToolCall("search_web", json.dumps(search_q), tool_call_id="c1"),
                1: DeltaToolCall("register_source", json.dumps(source), tool_call_id="c2"),
            }

        script.then(search_then_register, say("The next turn."))
        first = asyncio.create_task(run_turn(container, stalled))
        await asyncio.wait_for(search.called.wait(), 5)
        bound = agent_service.TURN_TIME_LIMIT + agent_service.TURN_MARGIN
        clock.advance(seconds=bound.total_seconds() + 1)
        async with container() as request:
            await (await request.get(AgentTurnService)).recover()
        failed = await get_turn(container, stalled)
        # The second execution: the session's next turn runs while the first still waits.
        done = await run_turn(container, following)
        search.go_on.set()
        resumed = await asyncio.wait_for(first, 5)
        stored = await get_turn(container, stalled)
        async with container() as request:
            sources = await (await request.get(SourceService)).list(session.project_id)
    finally:
        await container.close()

    assert (failed.status, failed.error) == ("failed", agent_service.ABANDONED)
    assert done.status == "done"
    # Once failed, the stalled worker changed nothing: its next tool call was refused and
    # its own end was not stored.
    assert resumed == stored == failed
    assert sources == []
