"""The models file (`llms.yml`, path from ADA_LLMS_CONFIG): which providers exist, where
they are and which environment variable holds each key, and which model serves what.

    providers:
      gemini:
        kind: openai-compatible
        base_url: https://generativelanguage.googleapis.com/v1beta/openai/
        api_key_env: GEMINI_API_KEY
    models:
      session_agent: gemini/gemini-2.5-flash

Keys are read from the environment when the file is loaded and never leave this module
except to the provider. A missing file is a platform without an agent; a malformed one is
an error that names every problem.
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Self

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from ada.core.models.agents import SESSION_AGENT, ModelInfo, ModelList
from ada.core.ports.agents import LanguageModels

PURPOSES = (SESSION_AGENT,)


class LlmsConfigError(Exception):
    """The models file exists but cannot be used."""


class ProviderKind(StrEnum):
    # The OpenAI chat completions API, which most providers speak: Gemini's OpenAI
    # endpoint, NVIDIA NIM, OpenAI itself, vLLM.
    OPENAI_COMPATIBLE = "openai-compatible"
    # Google's own Gemini API.
    GEMINI = "gemini"


class _Strict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ProviderConfig(_Strict):
    kind: ProviderKind
    base_url: str | None = None
    # The name of the environment variable that holds the key, never the key. Left out for
    # an endpoint that needs none, e.g. a local vLLM.
    api_key_env: str | None = None

    @model_validator(mode="after")
    def _needs_base_url(self) -> Self:
        if self.kind is ProviderKind.OPENAI_COMPATIBLE and not self.base_url:
            raise ValueError("an openai-compatible provider needs a base_url")
        return self


class LlmsFile(_Strict):
    providers: dict[str, ProviderConfig] = {}
    # Purpose -> "<provider>/<model>".
    models: dict[str, str] = {}

    @model_validator(mode="after")
    def _models_name_known_providers(self) -> Self:
        problems = []
        for purpose, model_id in self.models.items():
            if purpose not in PURPOSES:
                problems.append(f"models.{purpose}: unknown purpose (known: {', '.join(PURPOSES)})")
            provider, _, model = model_id.partition("/")
            if not model:
                problems.append(f"models.{purpose}: {model_id!r} is not '<provider>/<model>'")
            elif provider not in self.providers:
                problems.append(f"models.{purpose}: no provider {provider!r} in providers")
        if problems:
            raise ValueError("; ".join(problems))
        return self


@dataclass(frozen=True)
class Target:
    """Everything needed to call one model."""

    model_id: str
    provider: ProviderConfig
    model: str
    # None when the provider needs none.
    key: str | None = field(repr=False)


@dataclass(frozen=True)
class LlmsConfig:
    """The loaded file, with the keys it names."""

    file: LlmsFile = field(default_factory=LlmsFile)
    # Variable name -> key, for the variables the file names that are set.
    keys: Mapping[str, str] = field(default_factory=dict, repr=False)
    # Where it was read from, for messages; None when there was no file.
    path: Path | None = None

    def catalog(self) -> ModelList:
        purposes: dict[str, list[str]] = {}
        for purpose, model_id in self.file.models.items():
            purposes.setdefault(model_id, []).append(purpose)
        return ModelList(
            models=tuple(self._info(model_id, tuple(p)) for model_id, p in purposes.items()),
            session_agent=self.file.models.get(SESSION_AGENT),
        )

    def target(self, model_id: str) -> Target:
        provider_name, _, model = model_id.partition("/")
        provider = self.file.providers.get(provider_name)
        if provider is None or not model:
            raise LlmsConfigError(f"No provider is configured for the model {model_id!r}")
        key = self.keys.get(provider.api_key_env) if provider.api_key_env else None
        return Target(model_id=model_id, provider=provider, model=model, key=key)

    def _info(self, model_id: str, purposes: tuple[str, ...]) -> ModelInfo:
        provider_name, _, model = model_id.partition("/")
        provider = self.file.providers[provider_name]
        reason = None
        if provider.api_key_env and not self.keys.get(provider.api_key_env):
            reason = f"The environment variable {provider.api_key_env} is not set"
        return ModelInfo(
            id=model_id,
            provider=provider_name,
            model=model,
            purposes=purposes,
            available=reason is None,
            reason=reason,
        )


def load_llms_config(path: Path, environ: Mapping[str, str] | None = None) -> LlmsConfig:
    """Read the models file. A missing file gives a configuration without models; a file
    that is not valid raises LlmsConfigError naming the file and every problem."""
    environ = os.environ if environ is None else environ
    if not path.is_file():
        return LlmsConfig()
    try:
        raw = yaml.safe_load(path.read_text()) or {}
    except (OSError, yaml.YAMLError) as error:
        raise LlmsConfigError(f"{path} could not be read as YAML: {error}") from error
    try:
        file = LlmsFile.model_validate(raw)
    except ValidationError as error:
        problems = "; ".join(_problem(detail) for detail in error.errors())
        raise LlmsConfigError(f"{path} is not a valid models file: {problems}") from error
    names = {p.api_key_env for p in file.providers.values() if p.api_key_env}
    keys = {name: environ[name] for name in names if environ.get(name)}
    return LlmsConfig(file=file, keys=keys, path=path)


def _problem(detail: Mapping[str, object]) -> str:
    location = ".".join(str(part) for part in detail.get("loc", ()))  # type: ignore[union-attr]
    message = str(detail.get("msg", "")).removeprefix("Value error, ")
    return f"{location}: {message}" if location else message


class ConfiguredModels(LanguageModels):
    def __init__(self, config: LlmsConfig) -> None:
        self.config = config

    def catalog(self) -> ModelList:
        return self.config.catalog()
