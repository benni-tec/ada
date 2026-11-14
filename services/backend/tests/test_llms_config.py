"""The models file: loading, validation, keys from the environment, and what a broken
file does to the start. Nothing here calls a provider."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.models.openai import OpenAIChatModel

from ada.adapters.llm.config import LlmsConfigError, ProviderKind, load_llms_config
from ada.adapters.llm.runtime import provider_model
from ada.config import Settings
from ada.entrypoints.http.app import create_app
from memory import memory_adapters

EXAMPLE = Path(__file__).parents[3] / "llms.example.yml"

VALID = """\
providers:
  gemini:
    kind: openai-compatible
    base_url: https://generativelanguage.googleapis.com/v1beta/openai/
    api_key_env: GEMINI_API_KEY
  local:
    kind: openai-compatible
    base_url: http://localhost:8001/v1
models:
  session_agent: gemini/gemini-flash
"""


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "llms.yml"
    path.write_text(text)
    return path


def test_a_missing_file_means_no_agent(tmp_path: Path) -> None:
    catalog = load_llms_config(tmp_path / "absent.yml", environ={}).catalog()
    assert (catalog.models, catalog.session_agent) == ((), None)


def test_a_model_with_its_key_set_is_available(tmp_path: Path) -> None:
    config = load_llms_config(write(tmp_path, VALID), environ={"GEMINI_API_KEY": "k-123"})

    catalog = config.catalog()

    assert catalog.session_agent == "gemini/gemini-flash"
    [model] = catalog.models
    assert (model.id, model.provider, model.model, model.purposes) == (
        "gemini/gemini-flash",
        "gemini",
        "gemini-flash",
        ("session_agent",),
    )
    assert (model.available, model.reason) == (True, None)
    assert "k-123" not in catalog.model_dump_json()
    assert "k-123" not in repr(config)
    assert config.target("gemini/gemini-flash").key == "k-123"


def test_a_model_without_its_key_is_unavailable_and_says_why(tmp_path: Path) -> None:
    [model] = (
        load_llms_config(write(tmp_path, VALID), environ={"GEMINI_API_KEY": ""}).catalog().models
    )
    assert model.available is False
    assert model.reason == "The environment variable GEMINI_API_KEY is not set"


def test_a_provider_without_a_key_variable_needs_none(tmp_path: Path) -> None:
    path = write(tmp_path, VALID.replace("gemini/gemini-flash", "local/org/served-model"))
    [model] = load_llms_config(path, environ={}).catalog().models
    # The model name keeps its own slashes.
    assert (model.provider, model.model, model.available) == ("local", "org/served-model", True)


def test_yaml_that_does_not_parse_names_the_file(tmp_path: Path) -> None:
    path = write(tmp_path, "providers: [unclosed")
    with pytest.raises(LlmsConfigError, match="could not be read as YAML") as error:
        load_llms_config(path, environ={})
    assert str(path) in str(error.value)


def test_every_problem_of_a_file_is_named(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        """\
providers:
  nvidia:
    kind: openai-compatible
    api_key: sk-in-the-file
  other:
    kind: carrier-pigeon
models:
  session_agent: missing/model
""",
    )
    with pytest.raises(LlmsConfigError) as error:
        load_llms_config(path, environ={})
    message = str(error.value)
    assert str(path) in message
    assert "providers.nvidia.api_key: Extra inputs are not permitted" in message
    assert "providers.other.kind" in message


def test_models_must_name_a_configured_provider_and_a_known_purpose(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        VALID.replace(
            "session_agent: gemini/gemini-flash", "session_agent: nope/x\n  chat: gemini"
        ),
    )
    with pytest.raises(LlmsConfigError) as error:
        load_llms_config(path, environ={})
    message = str(error.value)
    assert "models.session_agent: no provider 'nope' in providers" in message
    assert "models.chat: unknown purpose" in message
    assert "models.chat: 'gemini' is not '<provider>/<model>'" in message


def test_an_openai_compatible_provider_needs_a_base_url(tmp_path: Path) -> None:
    path = write(tmp_path, "providers:\n  x:\n    kind: openai-compatible\n")
    with pytest.raises(LlmsConfigError, match="needs a base_url"):
        load_llms_config(path, environ={})


def test_the_committed_example_is_a_valid_models_file() -> None:
    config = load_llms_config(EXAMPLE, environ={})
    assert config.catalog().session_agent is not None
    assert config.file.providers["gemini"].kind is ProviderKind.OPENAI_COMPATIBLE


def test_models_are_built_for_both_kinds_without_calling_anyone(tmp_path: Path) -> None:
    text = VALID + "  # unused\n"
    text = text.replace(
        "  local:\n",
        "  google:\n    kind: gemini\n    api_key_env: GEMINI_API_KEY\n  local:\n",
    )
    config = load_llms_config(write(tmp_path, text), environ={"GEMINI_API_KEY": "k"})

    openai = provider_model(config.target("gemini/gemini-flash"))
    google = provider_model(config.target("google/gemini-flash"))

    assert isinstance(openai, OpenAIChatModel)
    assert openai.model_name == "gemini-flash"
    assert isinstance(google, GoogleModel)


def test_the_settings_read_the_path_from_ada_llms_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ADA_LLMS_CONFIG", "/etc/ada/llms.yml")
    settings = Settings(database_url="postgresql+psycopg://x/y", valkey_url="redis://x")
    assert settings.llms_config == Path("/etc/ada/llms.yml")
    monkeypatch.delenv("ADA_LLMS_CONFIG")
    default = Settings(database_url="postgresql+psycopg://x/y", valkey_url="redis://x")
    assert default.llms_config == Path("llms.yml")


def test_a_broken_models_file_stops_the_api_from_starting(
    unreachable_settings: Settings, tmp_path: Path
) -> None:
    settings = unreachable_settings.model_copy(
        update={"llms_config": write(tmp_path, "providers: 3")}
    )
    with pytest.raises(LlmsConfigError, match="not a valid models file"):
        with TestClient(create_app(settings, *memory_adapters())):
            pass
