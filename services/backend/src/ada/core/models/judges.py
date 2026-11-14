"""Judges: a language model that reviews what an agent wrote before people see it, e.g. a
text widget's words against its numbers, or a custom widget's code for data written into it.
A verdict never changes the content; the caller stores it beside the content."""

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from ada.core.models.base import DomainModel
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
