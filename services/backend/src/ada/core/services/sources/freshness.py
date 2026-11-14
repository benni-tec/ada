"""When a source's snapshot stops being fresh, by its policy (spec: Invalidation)."""

from datetime import datetime, timedelta

from ada.core.models.errors import Invalid
from ada.core.models.runs import Snapshot
from ada.core.models.sources import DataSource, FreshnessKind, FreshnessPolicy

# Policies the scheduler acts on. The others wait to be asked: manual by a person or an
# agent, push by a webhook that does not exist yet.
SCHEDULED = frozenset({FreshnessKind.TTL, FreshnessKind.PROBE})


def check_policy(policy: FreshnessPolicy) -> None:
    """Raises Invalid for a policy that cannot work."""
    for name in ("ttl_seconds", "latest_period_ttl_seconds"):
        value = getattr(policy, name)
        if value is not None and value <= 0:
            raise Invalid(f"{name} must be positive")
    if policy.kind is FreshnessKind.TTL and policy.ttl_seconds is None:
        raise Invalid("A time-to-live policy needs ttl_seconds")


def wants_check(source: DataSource, current: Snapshot | None, now: datetime) -> bool:
    """Whether a refresh that is not forced should look at the source now: fetch it, or
    probe it first. A source without a snapshot always wants one, whatever its policy."""
    if current is None:
        return True
    if source.freshness.kind not in SCHEDULED:
        return False
    # Measured from the last check, not from the snapshot: a refetch that found the same
    # content writes no new snapshot but still counts. A failed check counts too, so a
    # broken source is retried once per period instead of on every run.
    checked = source.last_checked_at or current.fetched_at
    ttl = source.freshness.ttl_seconds
    # A probe policy without a lifetime probes on every refresh; the scheduler's sweep then
    # sets the pace.
    return ttl is None or now - checked >= timedelta(seconds=ttl)


def is_due(source: DataSource, current: Snapshot | None, now: datetime) -> bool:
    """Whether the scheduler should refresh the source now."""
    return source.freshness.kind in SCHEDULED and wants_check(source, current, now)
