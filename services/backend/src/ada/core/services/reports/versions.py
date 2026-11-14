"""Semantic versions of a report, and which level a change needs (docs/spec.md, "Versions").

The platform can tell the level itself, because it knows what changed between two
versions: the pipelines behind the widgets, the run or time range, or only static parts.
"""

import re
from dataclasses import dataclass

from ada.core.models.base import Id
from ada.core.models.errors import Invalid
from ada.core.models.operators import OperatorId
from ada.core.models.reports import VersionBump
from ada.core.models.time import TimeRange

FIRST = "1.0.0"

_SEMVER = re.compile(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)")

# Higher means less comparable with the previous version.
_RANK = {VersionBump.PATCH: 0, VersionBump.MINOR: 1, VersionBump.MAJOR: 2}


def parse_version(version: str) -> tuple[int, int, int]:
    match = _SEMVER.fullmatch(version)
    if match is None:
        raise Invalid(f"{version!r} is not a version like 1.2.0")
    major, minor, patch = (int(part) for part in match.groups())
    return major, minor, patch


def bumped(version: str, bump: VersionBump) -> str:
    major, minor, patch = parse_version(version)
    match bump:
        case VersionBump.MAJOR:
            return f"{major + 1}.0.0"
        case VersionBump.MINOR:
            return f"{major}.{minor + 1}.0"
        case VersionBump.PATCH:
            return f"{major}.{minor}.{patch + 1}"


@dataclass(frozen=True)
class State:
    """What decides the level of a change: the widgets' pipelines, the run and its time
    range, and the static content (the stored blocks, each widget named by what it shows:
    every version shows copies of its own)."""

    operators: frozenset[OperatorId]
    run_id: Id
    time_range: TimeRange
    blocks: list[object]


def required(previous: State, next: State) -> VersionBump | None:
    """The least level the change from `previous` to `next` needs; None when nothing
    changed at all.

    - Major: the set of operators behind the widgets changed. An operator's id is its
      identity, which covers its whole pipeline, so an edited SQL upstream counts too.
    - Minor: the same pipelines on another run or time range.
    - Patch: the same run and pipelines; only the static parts, the widgets' settings or
      the arrangement of widgets changed.
    """
    if previous.operators != next.operators:
        return VersionBump.MAJOR
    if previous.run_id != next.run_id or previous.time_range != next.time_range:
        return VersionBump.MINOR
    if previous.blocks != next.blocks:
        return VersionBump.PATCH
    return None


def decide(previous_version: str, need: VersionBump, given: VersionBump | None) -> str:
    """The next version number. A given level may be higher than needed, e.g. a major
    version for a changed definition the platform cannot see; never lower, since a lower
    level would claim numbers comparable that are not."""
    if given is not None and _RANK[given] < _RANK[need]:
        raise Invalid(
            f"A {given.value} version is too small for this change: {_REASONS[need]}, "
            f"so it needs at least a {need.value} version"
        )
    return bumped(previous_version, given or need)


_REASONS = {
    VersionBump.MAJOR: "the widgets' pipelines changed",
    VersionBump.MINOR: "the run or the time range changed",
    VersionBump.PATCH: "only static content changed",
}
