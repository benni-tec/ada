"""Pushing a run's time range down to a source: asking it for the requested periods only
(spec: Time ranges), and deciding which stored periods are still fresh.

The `pushdown` key of `DataSource.options` says how the source takes periods:

    {"param": "years"}
        A query parameter, repeated once per period: Sotkanet's
        ...&years=2022&years=2023. It replaces a parameter of that name in the address.
    {"body": "query.2.selection.values"}
        A dot path into the request body (request sources) whose value becomes the list of
        periods, e.g. the time selection of a PxWeb query. Digits index arrays.
    {"format": "{year}"}
        Optional, with either: how a period is written, using {year}, {quarter} and
        {month}. The default follows the grain: 2024, 2024Q1, 2024M03.

Pushdown needs the declared schema to have a time role with a grain, which says which
periods exist, and the source's rows to carry their period in the role's columns (a
`period` shaping option makes them from a year column). The source must answer for
exactly the periods asked for; the answer is split by period and each period stored as a
snapshot of its own, keyed `period:<start>/<end>`.

Freshness by period. A stored period is fetched again when it is stale:

- the newest periods, from the latest stored period that has rows onwards, after
  `latest_period_ttl_seconds` when the policy sets one: they are the ones still revised;
- every period after `ttl_seconds` under a time-to-live policy;
- under a probe policy, all of them when the probe's token changed. The probe runs at
  most every `ttl_seconds`, as for the whole source; a changed token also retires every
  other stored snapshot of the source, which is fetched again when next asked for.

Manual and push policies keep stored periods until a forced refresh retires them.
"""

import copy
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from typing import Any

from pydantic import ValidationError, model_validator

from ada.core.models.base import DomainModel, JsonObject
from ada.core.models.errors import Invalid
from ada.core.models.runs import Snapshot
from ada.core.models.schema import TimeRole
from ada.core.models.sources import AccessKind, DataSource, FreshnessKind
from ada.core.models.time import Grain, Interval
from ada.core.services.schema.time import label, year


class PushdownOptions(DomainModel):
    param: str | None = None
    body: str | None = None
    format: str | None = None

    @model_validator(mode="after")
    def _one_way(self) -> PushdownOptions:
        if (self.param is None) == (self.body is None):
            raise ValueError("pushdown takes either `param` or `body`")
        return self


def pushdown_options(options: JsonObject) -> PushdownOptions | None:
    """The source's pushdown option, if it has one. Raises Invalid when it is malformed."""
    if options.get("pushdown") is None:
        return None
    try:
        return PushdownOptions.model_validate(options["pushdown"])
    except ValidationError as error:
        raise Invalid(f"Invalid pushdown option: {error}") from None


def time_role(source: DataSource) -> TimeRole | None:
    """The time role pushdown splits by: declared, with a grain."""
    declared = source.declared_schema
    role = declared.roles.time if declared else None
    return role if role is not None and role.grain is not None else None


def check_pushdown(source: DataSource) -> None:
    """Raises Invalid for a pushdown option that cannot work, at registration rather than
    at the first run."""
    pushdown = pushdown_options(source.options)
    if pushdown is None:
        return
    role = time_role(source)
    if role is None or role.grain is None:
        raise Invalid(
            "Pushdown needs a declared schema with a time role that has a grain, so the "
            "platform knows which periods to ask for"
        )
    if pushdown.body is not None and source.access_kind is not AccessKind.REQUEST:
        raise Invalid("Pushdown into the body needs a request source; use `param` for a URL")
    # Asking for one period shows whether the format and the body path work.
    request(source, pushdown, (year(2024),), role.grain)


def request(
    source: DataSource, pushdown: PushdownOptions, periods: Sequence[Interval], grain: Grain
) -> DataSource:
    """The source as it must be read to answer for just these periods: its options with
    the periods in the query parameter or the body. The readers then fetch it as usual."""
    try:
        labels = [label(period, grain, pushdown.format) for period in periods]
    except (KeyError, IndexError, ValueError) as error:
        raise Invalid(f"The pushdown format {pushdown.format!r} does not work: {error}") from None
    options = copy.deepcopy(source.options)
    if pushdown.param is not None:
        options["params"] = {**options.get("params", {}), pushdown.param: labels}
    else:
        assert pushdown.body is not None
        options["body"] = _replace(options.get("body"), pushdown.body, labels)
    return source.model_copy(update={"options": options})


def is_stale(
    source: DataSource, period: Interval, snapshot: Snapshot, newest: date | None, now: datetime
) -> bool:
    """Whether a stored period is old enough to fetch again by its age. `newest` is where
    the newest periods begin: the start of the latest stored period that has rows."""
    policy = source.freshness
    is_newest = newest is None or period.start >= newest
    lifetime = None
    if is_newest and policy.latest_period_ttl_seconds is not None:
        lifetime = policy.latest_period_ttl_seconds
    elif policy.kind is FreshnessKind.TTL:
        lifetime = policy.ttl_seconds
    if lifetime is None:
        return False
    return now - snapshot.fetched_at >= timedelta(seconds=lifetime)


def _replace(body: Any, path: str, value: Any) -> Any:
    if not isinstance(body, dict | list):
        raise Invalid("Pushdown into the body needs a JSON body")
    body = copy.deepcopy(body)
    *parents, last = path.split(".")
    found: Any = body
    for segment in parents:
        found = _step(found, segment, path)
    if isinstance(found, dict) and last in found:
        found[last] = value
    elif isinstance(found, list) and last.isdigit() and int(last) < len(found):
        found[int(last)] = value
    else:
        raise Invalid(f"The body has nothing at {path!r} to put the periods in")
    return body


def _step(found: Any, segment: str, path: str) -> Any:
    if isinstance(found, dict) and segment in found:
        return found[segment]
    if isinstance(found, list) and segment.isdigit() and int(segment) < len(found):
        return found[int(segment)]
    raise Invalid(f"The body has nothing at {path!r} to put the periods in")
