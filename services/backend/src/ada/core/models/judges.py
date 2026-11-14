"""Judges: a language model that reviews what an agent wrote before people see it, e.g. a
text widget's words against its numbers, or a custom widget's code for data written into it.
A verdict never changes the content; the caller stores it beside the content."""

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from ada.core.models.base import DomainModel, Id
from ada.core.models.schema import Column


class JudgeKind(StrEnum):
    TEXT_WIDGET = "text_widget"
    WIDGET_CODE = "widget_code"


class Strictness(StrEnum):
    OFF = "off"
    # Findings are shown; the content is kept.
    WARN = "warn"
    # A failed review refuses the content.
    BLOCK = "block"


class Outcome(StrEnum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"
    # Not reviewed: the judge is off, has no model, or its call failed (Verdict.reason).
    UNCHECKED = "unchecked"


class JudgeInput(DomainModel):
    """One dataset the content is about: its name, columns and a sample of its rows (the
    service caps the sample per kind)."""

    name: str
    columns: tuple[Column, ...]
    rows: tuple[tuple[Any, ...], ...] = ()


class JudgeContext(DomainModel):
    inputs: tuple[JudgeInput, ...] = ()
    # What the content is, for the judge, e.g. "custom widget: Survival by county".
    note: str = ""


class Finding(DomainModel):
    message: str
    # The exact text of the content the finding is about.
    excerpt: str
    severity: Literal["error", "warning"] = "error"


class Verdict(DomainModel):
    kind: JudgeKind
    outcome: Outcome
    # Pass or warn; unchecked is not passed.
    passed: bool
    # The strictness is block and the outcome fail: the caller refuses the content.
    blocking: bool
    findings: tuple[Finding, ...] = ()
    # "<provider>/<model>"; None when no model reviewed it.
    model: str | None = None
    # Why it is unchecked.
    reason: str | None = None
    # sha256 of the content and its context: the same content under the same settings is
    # not reviewed twice.
    content_hash: str
    checked_at: datetime


class JudgeDefaults(DomainModel):
    """The global settings of one kind, beside the global LLM registry."""

    kind: JudgeKind
    strictness: Strictness = Strictness.WARN
    # "<provider>/<model>" from the configured models; None: no model, so unchecked.
    model_id: str | None = None
    # Added to the kind's prompt in every project.
    instructions: str = ""
    revision: int = 0


class JudgeOverride(DomainModel):
    """A project's overrides of one kind; None inherits the global default."""

    project_id: Id
    kind: JudgeKind
    strictness: Strictness | None = None
    model_id: str | None = None
    # Project instructions come after the global ones.
    instructions: str | None = None
    # 0 while the project overrides nothing of this kind (no record yet).
    revision: int = 0


class JudgeSettings(DomainModel):
    """What review uses in a project: the defaults with the project's overrides applied."""

    project_id: Id
    kind: JudgeKind
    strictness: Strictness
    model_id: str | None
    # Global, then project.
    instructions: str
    # The fields the project overrides.
    overridden: frozenset[str] = frozenset()
    # The project override's revision, 0 when there is none yet: the expected_revision of
    # the next override.
    revision: int = 0
