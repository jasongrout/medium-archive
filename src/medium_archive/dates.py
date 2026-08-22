"""Date parsing and the --start/--end window check."""

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime


def parse_date(text: str | None) -> datetime | None:
    """ISO-8601 (sitemap/JSON-LD) or RFC-2822 (RSS) -> aware UTC datetime."""
    if not text:
        return None
    text = text.strip()
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            dt = parsedate_to_datetime(text)
        except (TypeError, ValueError):
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def in_window(dt: datetime | None, start: datetime, end: datetime | None) -> bool:
    if dt is None:
        return True
    if dt > start:
        return False
    if end is not None and dt < end:
        return False
    return True
