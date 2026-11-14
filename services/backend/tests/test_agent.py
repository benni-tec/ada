"""The in-platform agent: messages that queue turns, turns that run the
scripted model (pydantic-ai's FunctionModel, agent_support.py) with the platform's own MCP
tools in process, and their parts stored and streamed. No provider is ever called.

The REST routes run in a TestClient; a turn runs as the worker's task would, on the app's
container, in the client's event loop."""

from collections.abc import Iterator
from typing import Any
from uuid import UUID, uuid7

import pytest
from fastapi.testclient import TestClient
from fastmcp import Client
from mcp.types import Implementation
from openai import AsyncOpenAI
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from taskiq import InMemoryBroker

from ada.adapters.memory.events import MemoryEventBus
from ada.adapters.memory.repositories import MemoryStore
from ada.config import Settings
from ada.core.models.actors import Actor, ActorKind
from ada.core.models.agents import AgentTurn, ProviderKind
from ada.core.ports.agents import ToolCallFailed
from ada.core.services.agents import service as agent_service
from ada.core.services.ports.agents import AgentTurnService
from ada.core.services.ports.projects import ProjectService
from ada.core.services.ports.sessions import SessionService
from ada.entrypoints.mcp.agent import CLIENT, LEFT_OUT, InProcessToolbox
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
from api_support import Overrides, dispatcher, events, new_project, send, serve
from memory import memory_adapters

pytestmark = pytest.mark.anyio

WEB = {"kind": "user", "name": "web"}


# Turns, through the REST routes


@pytest.fixture(scope="module")
def agent() -> AgentOverrides:
    return AgentOverrides(Script())


@pytest.fixture(scope="module")
def client(unreachable_settings: Settings, agent: AgentOverrides) -> Iterator[TestClient]:
    with serve(unreachable_settings, Overrides(), agent) as client:
        # One provider with its key, one model, the session agent: as the Settings page sets.
        assert client.portal is not None
        client.portal.call(configure, container(client), config())
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
                assert models == {"models": [], "session_agent": None}


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
    assert [e.payload["status"] for e in finished] == ["cancelled", "cancelled"]


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

    assert names == everything - LEFT_OUT
    assert {"list_pipelines", "create_widget", "pin_widget"} <= names
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

    actors = [e["actor"] for e in send(client, "GET", f"/sessions/{session['id']}/entries")]
    assert actors == [
        {"kind": "external_agent", "name": CLIENT.name},
        {"kind": "external_agent", "name": "gemini/flash"},
    ]


# The worker


async def test_the_worker_task_runs_a_turn(unreachable_settings: Settings) -> None:
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
        async with app_container() as request:
            project = await (await request.get(ProjectService)).create("P")
            session = await (await request.get(SessionService)).create(project.id, "S")
        async with app_container() as request:
            posted = await (await request.get(AgentTurnService)).post_message(
                session.id, "Hi", Actor(kind=ActorKind.USER, name="web")
            )
        assert posted.turn is not None
        script.then(say("Hello from the worker."))

        task = broker.find_task("ada.entrypoints.worker.tasks.agent:run_turn")
        assert task is not None
        result = await (await task.kiq(turn_id=str(posted.turn.id))).wait_result(timeout=5)
        assert not result.is_err, result.error

        async with app_container() as request:
            turn = await (await request.get(AgentTurnService)).get(posted.turn.id)
        assert turn.status == "done"
        assert turn.parts[0].text == "Hello from the worker."  # type: ignore[union-attr]
    finally:
        await broker.shutdown()
