"""The rules for fields, pure: a value per field type, whether a case type covers what a
model needs, which schema changes keep old cases valid, and what a key may be."""

import re
from datetime import date
from typing import Any

from ada.core.models.base import JsonObject
from ada.core.models.cases import Field, FieldType, Gap
from ada.core.models.errors import Invalid

KEY = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
# A Finnish personal identity code: DDMMYY, the century sign, a number and a check sign.
IDENTITY_CODE = re.compile(r"\d{6}[-+A-FYXWVU]\d{3}[0-9A-Y]", re.IGNORECASE)
NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
WITH_LEVELS = (FieldType.ENUM, FieldType.ENUM_LIST, FieldType.DAY_MAP)


def check_key(key: str) -> None:
    if IDENTITY_CODE.search(key):
        raise Invalid("A case key must not be a personal identity code: use your system's id")
    if not KEY.match(key):
        raise Invalid("A case key is 1 to 128 characters of letters, digits and . _ : -")


def check_fields(fields: tuple[Field, ...]) -> None:
    names = [f.name for f in fields]
    if len(set(names)) != len(names):
        raise Invalid("Every field of a case type needs its own name")
    for f in fields:
        if not NAME.match(f.name):
            raise Invalid(f"Field name {f.name!r}: lowercase letters, digits and _")
        if f.type in WITH_LEVELS and not f.levels:
            raise Invalid(f"Field {f.name} ({f.type.value}) needs its levels")
        if f.type not in WITH_LEVELS and f.levels:
            raise Invalid(f"Field {f.name} ({f.type.value}) takes no levels")
        if len(set(f.levels)) != len(f.levels):
            raise Invalid(f"Field {f.name} repeats a level")


def _value(f: Field, value: Any) -> Any:
    match f.type:
        case FieldType.TEXT:
            if not isinstance(value, str):
                raise Invalid(f"{f.name} must be text")
            return value
        case FieldType.NUMBER:
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise Invalid(f"{f.name} must be a number")
            return value
        case FieldType.INTEGER:
            if isinstance(value, bool) or not isinstance(value, int):
                raise Invalid(f"{f.name} must be a whole number")
            return value
        case FieldType.BOOLEAN:
            if not isinstance(value, bool):
                raise Invalid(f"{f.name} must be true or false")
            return value
        case FieldType.DATE:
            try:
                return date.fromisoformat(str(value)).isoformat()
            except ValueError:
                raise Invalid(f"{f.name} must be a date (YYYY-MM-DD)") from None
        case FieldType.ENUM:
            if value not in f.levels:
                raise Invalid(f"{f.name} must be one of {', '.join(f.levels)}")
            return value
        case FieldType.ENUM_LIST:
            if not isinstance(value, list | tuple) or any(v not in f.levels for v in value):
                raise Invalid(f"{f.name} must be a list of {', '.join(f.levels)}")
            if len(set(value)) != len(value):
                raise Invalid(f"{f.name} repeats a value")
            return list(value)
        case FieldType.DAY_MAP:
            if not isinstance(value, dict):
                raise Invalid(f"{f.name} must map steps to days")
            for step, days in value.items():
                if step not in f.levels:
                    raise Invalid(f"{f.name}: unknown step {step}")
                if isinstance(days, bool) or not isinstance(days, int) or days < 0:
                    raise Invalid(
                        f"{f.name}: the days for {step} must be a whole number, 0 or more"
                    )
            return {s: value[s] for s in f.levels if s in value}


def check_values(fields: tuple[Field, ...], values: JsonObject) -> JsonObject:
    """The values, checked and normalised; Invalid for an unknown field, a missing
    required one, or a value its type refuses. None leaves an optional field empty."""
    known = {f.name: f for f in fields}
    unknown = sorted(set(values) - set(known))
    if unknown:
        raise Invalid(f"Unknown fields: {', '.join(unknown)}")
    checked: JsonObject = {}
    for f in fields:
        value = values.get(f.name)
        if value is None:
            if f.required:
                raise Invalid(f"{f.name} is required")
            continue
        checked[f.name] = _value(f, value)
    return checked


def coverage(fields: tuple[Field, ...], needs: tuple[Field, ...]) -> list[Gap]:
    """What a case type lacks for a model: a field missing, of another type, optional where
    the model needs it, or with levels the model does not accept."""
    known = {f.name: f for f in fields}
    gaps: list[Gap] = []
    for need in needs:
        have = known.get(need.name)
        if have is None:
            gaps.append(Gap(field=need.name, problem=f"missing ({need.type.value})"))
        elif have.type is not need.type:
            gaps.append(
                Gap(field=need.name, problem=f"is {have.type.value}, needs {need.type.value}")
            )
        elif need.required and not have.required:
            gaps.append(Gap(field=need.name, problem="must be required"))
        elif extra := [level for level in have.levels if level not in need.levels]:
            gaps.append(Gap(field=need.name, problem=f"levels not accepted: {', '.join(extra)}"))
    return gaps


def describe(gaps: list[Gap]) -> str:
    return "; ".join(f"{g.field} {g.problem}" for g in gaps)


def compatible(old: tuple[Field, ...], new: tuple[Field, ...]) -> list[str]:
    """Why a schema change would break saved cases: only new optional fields and new
    levels are allowed."""
    problems: list[str] = []
    after = {f.name: f for f in new}
    for f in old:
        g = after.get(f.name)
        if g is None:
            problems.append(f"{f.name} is removed")
            continue
        if g.type is not f.type:
            problems.append(f"{f.name} changes type")
        if g.required and not f.required:
            problems.append(f"{f.name} becomes required")
        if missing := [level for level in f.levels if level not in g.levels]:
            problems.append(f"{f.name} loses levels {', '.join(missing)}")
    before = {f.name for f in old}
    problems.extend(
        f"{f.name} is new and required" for f in new if f.name not in before and f.required
    )
    return problems
