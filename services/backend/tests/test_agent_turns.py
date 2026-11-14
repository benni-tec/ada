"""The in-platform agent: messages queue turns, turns run the scripted model with the
platform's own MCP tools in process, and their parts are stored and streamed.

The REST routes run in a TestClient; a turn runs as the worker's task would, on the app's
container, in the client's event loop. The model is pydantic-ai's FunctionModel, so no
provider is ever called."""

from collections.abc import Iterator
from typing import Any
from uuid import UUID, uuid7

import pytest
from fastapi.testclient import TestClient
from openai import AsyncOpenAI
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from taskiq import InMemoryBroker

from ada.adapters.llm.config import LlmsConfig
from ada.adapters.memory.events import MemoryEventBus
from ada.adapters.memory.repositories import MemoryStore
from ada.adapters.memory.tasks import RecordingTaskDispatcher
from ada.config import Settings
from ada.core.models.actors import Actor, ActorKind
from ada.core.models.agents import AgentTurn
from ada.core.models.events import Event
from ada.core.ports.tasks import TaskDispatcher
from ada.core.services.agents import service as agent_service
from ada.core.services.ports.agents import AgentTurnService
from ada.core.services.ports.projects import ProjectService
from ada.core.services.ports.sessions import SessionService
from ada.entrypoints.http.app import create_app
from ada.entrypoints.worker import create_broker
from agent_support import (
    AGENT,
    MODEL,
    AgentOverrides,
    Script,
    call,
    config,
    fail,
    returned,
    run_turn,
    say,
)
from memory import memory_adapters
from test_api_support import Overrides

WEB = {"kind": "user", "name": "web"}
RUN_TURN = "ada.entrypoints.worker.tasks.agent:run_turn"


@pytest.fixture
def script() -> Script:
    return Script()


@pytest.fixture
def llms() -> LlmsConfig:
    return config()


@pytest.fixture
def agent(script: Script, llms: LlmsConfig) -> AgentOverrides:
    return AgentOverrides(script, llms)


@pytest.fixture
def client(unreachable_settings: Settings, agent: AgentOverrides) -> Iterator[TestClient]:
    app = create_app(unreachable_settings, *memory_adapters(), Overrides(), agent)
    with TestClient(app) as client:
        yield client


def resolve[T](client: TestClient, port: type[T]) -> T:
    assert client.portal is not None
    return client.portal.call(container(client).get, port)


def container(client: TestClient) -> Any:
    return client.app.state.dishka_container  # type: ignore[attr-defined]


def events(client: TestClient, *types: str) -> list[Event]:
    published = resolve(client, MemoryEventBus).published
    return [event for event in published if not types or event.type in types]


def queued(client: TestClient) -> list[UUID]:
    dispatcher = resolve(client, TaskDispatcher)
    assert isinstance(dispatcher, RecordingTaskDispatcher)
    return dispatcher.turns


def run(client: TestClient, turn_id: str) -> AgentTurn:
    assert client.portal is not None
    return client.portal.call(run_turn, container(client), UUID(turn_id))


def post(client: TestClient, path: str, body: dict[str, Any] | None = None) -> Any:
    response = client.post(f"/api{path}", json=body or {})
    assert response.status_code in (200, 201, 202), response.text
    return response.json()


def get(client: TestClient, path: str) -> Any:
    response = client.get(f"/api{path}")
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture
def project(client: TestClient) -> dict[str, Any]:
    return post(client, "/projects", {"name": "Wellbeing"})


@pytest.fixture
def source(client: TestClient, project: dict[str, Any]) -> dict[str, Any]:
    return post(
        client,
        f"/projects/{project['id']}/sources",
        {
            "name": "Sotkanet",
            "access_kind": "url",
            "address": "https://example.test/screening.csv",
            "format": "csv",
        },
    )


@pytest.fixture
def session(client: TestClient, project: dict[str, Any]) -> dict[str, Any]:
    return post(client, f"/projects/{project['id']}/sessions", {"title": "Screening"})


def message(client: TestClient, session: dict[str, Any], text: str, **body: Any) -> Any:
    return post(client, f"/sessions/{session['id']}/messages", {"text": text, **body})


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


# Queueing


def test_a_message_queues_a_turn_after_its_entry(
    client: TestClient, session: dict[str, Any]
) -> None:
    posted = message(client, session, "Show screening")

    entry, turn = posted["entry"], posted["turn"]
    assert (turn["status"], turn["model"], turn["parts"]) == ("queued", MODEL, [])
    assert turn["prompt_entry_id"] == entry["id"]
    assert turn["session_id"] == session["id"]
    entries = get(client, f"/sessions/{session['id']}/entries")
    assert [(e["kind"], e["actor"], e["ref"]) for e in entries] == [
        ("message", WEB, None),
        ("agent_turn", AGENT, turn["id"]),
    ]
    # Queued once the message's unit of work committed; announced the same way.
    assert queued(client) == [UUID(turn["id"])]
    started = events(client, "agent.turn_started")
    assert [event.payload for event in started] == [
        {"session_id": session["id"], "turn_id": turn["id"]}
    ]
    kinds = [event.type for event in events(client)]
    assert kinds.index("agent.turn_started") > kinds.index("session.entry_added")


def test_without_a_session_agent_a_message_gets_no_turn(
    unreachable_settings: Settings, script: Script
) -> None:
    app = create_app(
        unreachable_settings, *memory_adapters(), Overrides(), AgentOverrides(script, LlmsConfig())
    )
    with TestClient(app) as client:
        project = post(client, "/projects", {"name": "P"})
        session = post(client, f"/projects/{project['id']}/sessions", {"title": "S"})
        posted = message(client, session, "Hello")

        assert posted["turn"] is None
        assert [e["kind"] for e in get(client, f"/sessions/{session['id']}/entries")] == ["message"]
        assert queued(client) == []
        assert get(client, "/llm/models") == {"models": [], "session_agent": None}


@pytest.mark.parametrize("llms", [config(key=None)])
def test_a_model_without_its_key_fails_the_turn_at_once(
    client: TestClient, session: dict[str, Any]
) -> None:
    models = get(client, "/llm/models")
    assert models == {
        "models": [
            {
                "id": MODEL,
                "provider": "test",
                "model": "scripted",
                "purposes": ["session_agent"],
                "available": False,
                "reason": "The environment variable TEST_LLM_KEY is not set",
            }
        ],
        "session_agent": MODEL,
    }

    turn = message(client, session, "Hello")["turn"]

    assert turn["status"] == "failed"
    assert turn["error"] == "The environment variable TEST_LLM_KEY is not set"
    assert turn["finished_at"] is not None
    assert queued(client) == []
    finished = events(client, "agent.turn_finished")
    assert [event.payload["status"] for event in finished] == ["failed"]


def test_the_models_list_never_carries_a_key(client: TestClient) -> None:
    response = client.get("/api/llm/models")
    assert response.json()["models"][0]["available"] is True
    assert "secret" not in response.text


def test_an_unknown_model_is_refused_and_nothing_is_stored(
    client: TestClient, session: dict[str, Any]
) -> None:
    response = client.post(
        f"/api/sessions/{session['id']}/messages", json={"text": "Hi", "model": "other/x"}
    )

    assert response.status_code == 422
    assert "other/x" in response.json()["detail"]
    assert get(client, f"/sessions/{session['id']}/entries") == []
    assert events(client, "agent.turn_started") == []


# Context


def test_context_is_stored_with_the_message_and_reaches_the_prompt(
    client: TestClient,
    project: dict[str, Any],
    source: dict[str, Any],
    session: dict[str, Any],
    script: Script,
) -> None:
    operator = post(
        client,
        f"/projects/{project['id']}/operators",
        {"kind": "source", "data_source_id": source["id"]},
    )
    dashboard = post(client, f"/projects/{project['id']}/dashboards", {"name": "Screening"})
    widget = post(
        client,
        f"/projects/{project['id']}/widgets",
        {"operator_id": operator["id"], "type": "table", "title": "Regions"},
    )
    context = [
        {"kind": "pipeline", "operator_id": operator["id"]},
        {"kind": "dashboard", "dashboard_id": dashboard["id"], "slot": " headline "},
        {"kind": "widget", "widget_id": widget["id"]},
    ]
    script.then(say("Noted."))

    posted = message(client, session, "Add this", context=context)
    run(client, posted["turn"]["id"])

    assert posted["entry"]["context"] == [
        context[0],
        {"kind": "dashboard", "dashboard_id": dashboard["id"], "slot": "headline"},
        context[2],
    ]
    instructions = script.calls[0][1].instructions or ""
    assert f"operator {operator['id']}" in instructions
    assert 'A pipeline to build on: "Sotkanet"' in instructions
    assert f'"Screening", id {dashboard["id"]}' in instructions
    assert 'in its slot "headline"' in instructions
    assert f'"Regions", id {widget["id"]}' in instructions
    assert f'Session "Screening", id {session["id"]}' in instructions
    assert "Never state a number you did not read from a tool" in instructions


def test_context_must_name_something_in_the_project(
    client: TestClient, session: dict[str, Any]
) -> None:
    other = post(client, "/projects", {"name": "Other"})
    dashboard = post(client, f"/projects/{other['id']}/dashboards", {"name": "Elsewhere"})
    path = f"/api/sessions/{session['id']}/messages"

    elsewhere = {"kind": "dashboard", "dashboard_id": dashboard["id"]}
    missing = {"kind": "pipeline", "operator_id": "op_missing"}
    unknown = {"kind": "chart", "id": "x"}

    assert client.post(path, json={"text": "a", "context": [elsewhere]}).status_code == 422
    assert client.post(path, json={"text": "a", "context": [missing]}).status_code == 404
    assert client.post(path, json={"text": "a", "context": [unknown]}).status_code == 422
    assert get(client, f"/sessions/{session['id']}/entries") == []


# Running


def test_a_turn_builds_with_the_tools_and_answers(
    client: TestClient,
    project: dict[str, Any],
    source: dict[str, Any],
    session: dict[str, Any],
    script: Script,
) -> None:
    script.then(*build_a_table(project, source))
    turn_id = message(client, session, "Show screening")["turn"]["id"]

    finished = run(client, turn_id)

    stored = get(client, f"/turns/{turn_id}")
    assert stored == finished.model_dump(mode="json")
    assert stored["status"] == "done"
    assert stored["error"] is None
    assert stored["finished_at"] is not None
    parts = stored["parts"]
    assert [(p["type"], p.get("tool_name"), p.get("state")) for p in parts] == [
        ("tool", "add_source_operator", "output-available"),
        ("source", None, None),
        ("tool", "create_widget", "output-available"),
        ("text", None, None),
    ]
    operator = parts[0]["output"]
    assert parts[0]["input"]["data_source_id"] == source["id"]
    assert parts[1] == {
        "type": "source",
        "source_id": source["id"],
        "title": "Sotkanet",
        "url": "https://example.test/screening.csv",
    }
    widget = parts[2]["output"]["widget"]
    assert parts[3]["text"] == "I made a table."
    assert get(client, f"/sessions/{session['id']}/turns") == [stored]

    # Recorded in the session as the agent, like an external agent's work.
    entries = get(client, f"/sessions/{session['id']}/entries")
    assert [(e["kind"], e["actor"], e["ref"]) for e in entries] == [
        ("message", WEB, None),
        ("agent_turn", AGENT, turn_id),
        ("operator", AGENT, operator["id"]),
        ("widget", AGENT, widget["id"]),
    ]
    assert entries[3]["text"] == "Participation per region"
    assert widget["session_id"] == session["id"]
    assert widget["created_by"] == AGENT
    assert operator["created_by"] == AGENT


def test_parts_are_published_as_they_happen_and_the_turn_around_them(
    client: TestClient,
    project: dict[str, Any],
    source: dict[str, Any],
    session: dict[str, Any],
    script: Script,
) -> None:
    script.then(*build_a_table(project, source))
    turn_id = message(client, session, "Show screening")["turn"]["id"]

    run(client, turn_id)

    turn_events = [e for e in events(client) if e.type.startswith("agent.")]
    assert turn_events[0].type == "agent.turn_started"
    assert turn_events[-1].type == "agent.turn_finished"
    assert turn_events[-1].payload == {
        "session_id": session["id"],
        "turn_id": turn_id,
        "status": "done",
    }
    parts = [
        (e.payload["index"], e.payload["part"]["type"], e.payload["part"].get("state"))
        for e in turn_events
        if e.type == "agent.turn_part"
    ]
    # A tool call is shown when made, then replaced by its result; text grows in place.
    assert parts == [
        (0, "tool", "input-available"),
        (0, "tool", "output-available"),
        (1, "source", None),
        (2, "tool", "input-available"),
        (2, "tool", "output-available"),
        (3, "text", None),
        (3, "text", None),
    ]
    texts = [
        e.payload["part"]["text"]
        for e in turn_events
        if e.type == "agent.turn_part" and e.payload["index"] == 3
    ]
    assert texts == ["I made ", "I made a table."]


def test_a_part_is_live_before_it_is_stored(
    client: TestClient, session: dict[str, Any], script: Script
) -> None:
    seen: dict[str, Any] = {}
    turn_id = message(client, session, "Hi")["turn"]["id"]

    async def streaming(messages: Any, info: Any) -> Any:
        yield "Hello"
        bus = await container(client).get(MemoryEventBus)
        store = await container(client).get(MemoryStore)
        seen["live"] = [e.payload["part"] for e in bus.published if e.type == "agent.turn_part"]
        seen["stored"] = store.agent_turns[UUID(turn_id)].parts
        yield " there"

    script.then(streaming)
    run(client, turn_id)

    assert seen["live"] == [{"type": "text", "text": "Hello"}]
    assert seen["stored"] == ()
    assert get(client, f"/turns/{turn_id}")["parts"] == [{"type": "text", "text": "Hello there"}]


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
    widget_id = get(client, f"/turns/{first}")["parts"][2]["output"]["widget"]["id"]

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
    assert len(answers) == 1
    assert "I made a table." in answers[0]
    assert f"[called create_widget: widget {widget_id}]" in answers[0]
    assert "[read data source Sotkanet" in answers[0]


# Stopping and failing


def test_a_queued_turn_is_cancelled_at_once_and_never_runs(
    client: TestClient, session: dict[str, Any], script: Script
) -> None:
    turn_id = message(client, session, "Hi")["turn"]["id"]

    response = client.post(f"/api/turns/{turn_id}/cancel")
    finished = run(client, turn_id)

    assert response.status_code == 202
    assert response.json()["status"] == "cancelled"
    assert finished.status == "cancelled"
    assert script.calls == []
    assert [e.payload["status"] for e in events(client, "agent.turn_finished")] == ["cancelled"]
    assert events(client, "agent.turn_part") == []
    # A finished turn stays as it is.
    again = client.post(f"/api/turns/{turn_id}/cancel")
    assert (again.status_code, again.json()["status"]) == (202, "cancelled")


def test_a_running_turn_stops_at_its_next_step(
    client: TestClient, project: dict[str, Any], session: dict[str, Any], script: Script
) -> None:
    turn_id = message(client, session, "Hi")["turn"]["id"]

    async def cancel(step: int) -> None:
        # Someone presses stop while the model is answering its first request.
        if step == 1:
            async with container(client)() as request:
                await (await request.get(AgentTurnService)).cancel(UUID(turn_id))

    script.before_step = cancel
    script.then(call("list_pipelines", {"project_id": project["id"]}), say("never"))

    finished = run(client, turn_id)

    assert finished.status == "cancelled"
    assert len(script.calls) == 1
    # The tool call the model asked for was not made.
    assert finished.parts == ()
    assert [e.payload["status"] for e in events(client, "agent.turn_finished")] == ["cancelled"]


def test_a_failing_provider_ends_the_turn_as_failed(
    client: TestClient, session: dict[str, Any], script: Script
) -> None:
    script.then(fail(ModelHTTPError(503, "scripted", "overloaded")))
    turn_id = message(client, session, "Hi")["turn"]["id"]

    finished = run(client, turn_id)

    assert finished.status == "failed"
    assert finished.error is not None
    assert finished.error.startswith("The model provider answered with an error")
    assert get(client, f"/turns/{turn_id}")["status"] == "failed"
    assert [e.payload["status"] for e in events(client, "agent.turn_finished")] == ["failed"]


def test_an_unreachable_provider_ends_the_turn_as_failed(
    client: TestClient, session: dict[str, Any], agent: AgentOverrides
) -> None:
    # A real OpenAI client against a port nobody listens on: refused at once, no network.
    client_ = AsyncOpenAI(base_url="http://127.0.0.1:1/v1", api_key="x", max_retries=0)
    agent.factory = lambda model_id: OpenAIChatModel(
        "any", provider=OpenAIProvider(openai_client=client_)
    )
    turn_id = message(client, session, "Hi")["turn"]["id"]

    finished = run(client, turn_id)

    assert finished.status == "failed"
    assert finished.error is not None
    assert "could not be reached" in finished.error


def test_a_tool_that_keeps_refusing_ends_the_turn_as_failed(
    client: TestClient,
    project: dict[str, Any],
    source: dict[str, Any],
    session: dict[str, Any],
    script: Script,
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
    turn_id = message(client, session, "Hi")["turn"]["id"]

    finished = run(client, turn_id)

    assert finished.status == "failed"
    assert finished.error is not None
    assert "add_transform" in finished.error
    errors = [p for p in finished.parts if getattr(p, "state", None) == "output-error"]
    assert errors
    assert all(p.error_text == "Not a query: nonsense" for p in errors)  # type: ignore[union-attr]


def test_a_turn_that_needs_too_many_steps_fails(
    client: TestClient,
    project: dict[str, Any],
    session: dict[str, Any],
    script: Script,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(agent_service, "MAX_STEPS", 2)
    script.then(*[call("list_pipelines", {"project_id": project["id"]}) for _ in range(4)])
    turn_id = message(client, session, "Hi")["turn"]["id"]

    finished = run(client, turn_id)

    assert finished.status == "failed"
    assert finished.error == "The agent did not finish within 2 steps"


def test_an_unknown_turn_is_not_found(client: TestClient) -> None:
    missing = uuid7()
    assert client.get(f"/api/turns/{missing}").status_code == 404
    assert client.post(f"/api/turns/{missing}/cancel").status_code == 404
    assert client.get(f"/api/sessions/{missing}/turns").status_code == 404


# The worker


@pytest.mark.anyio
async def test_the_worker_task_runs_a_turn(unreachable_settings: Settings, script: Script) -> None:
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
        async with app_container() as request:
            project = await (await request.get(ProjectService)).create("P")
            session = await (await request.get(SessionService)).create(project.id, "S")
        async with app_container() as request:
            posted = await (await request.get(AgentTurnService)).post_message(
                session.id, "Hi", Actor(kind=ActorKind.USER, name="web")
            )
        assert posted.turn is not None
        script.then(say("Hello from the worker."))

        task = broker.find_task(RUN_TURN)
        assert task is not None
        result = await (await task.kiq(turn_id=str(posted.turn.id))).wait_result(timeout=5)
        assert not result.is_err, result.error

        async with app_container() as request:
            turn = await (await request.get(AgentTurnService)).get(posted.turn.id)
        assert turn.status == "done"
        assert turn.parts[0].text == "Hello from the worker."  # type: ignore[union-attr]
    finally:
        await broker.shutdown()
