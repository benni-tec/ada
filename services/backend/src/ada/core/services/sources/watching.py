"""Checking the signature of a page monitor's webhook delivery."""

import hashlib
import hmac
from datetime import datetime, timedelta

# As in Tell me when: a delivery whose timestamp is further from now is a replay.
TOLERANCE = timedelta(seconds=300)
MAX_STAMP_DIGITS = 12


def signature_matches(secret: str, raw_body: bytes, header: str | None, now: datetime) -> bool:
    """Whether `header` (`t=<unix>,v1=<hex>`) is the HMAC-SHA256 of `<t>.<raw_body>` under
    `secret`, made within the tolerance of `now`. Any malformed header is a mismatch."""
    if not header:
        return False
    parts = dict(part.strip().partition("=")[::2] for part in header.split(","))
    stamp, given = parts.get("t", ""), parts.get("v1", "")
    if not (stamp.isascii() and stamp.isdigit() and given.isascii() and given):
        return False
    # Bounded before the conversion: a huge number of digits must not raise.
    if len(stamp) > MAX_STAMP_DIGITS:
        return False
    if abs(now.timestamp() - int(stamp)) > TOLERANCE.total_seconds():
        return False
    wanted = hmac.new(secret.encode(), f"{stamp}.".encode() + raw_body, hashlib.sha256)
    return hmac.compare_digest(wanted.hexdigest().encode(), given.lower().encode())
