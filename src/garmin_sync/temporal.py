"""Temporal grounding: one clock, with all date math done in code.

Models are unreliable at calendar arithmetic and at resolving relative words
("today", "tomorrow") in text written on a different day. Prompts therefore
receive labels computed here, such as "Sun Sep 13 (yesterday)", rather than
raw dates the model has to reason about.

"Now" comes from the configured IANA timezone (profile ``timezone``), not the
host clock. Stored timestamps follow two conventions, both handled on read:

- SQLite ``CURRENT_TIMESTAMP`` columns (``created_at``, ``updated_at``) hold
  naive UTC.
- ``sync_metadata.last_sync_timestamp`` holds naive local wall-clock time.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

logger = logging.getLogger(__name__)

DEFAULT_TIMEZONE = "America/New_York"

_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_WEEKDAY_INDEX: dict[str, int] = {}
for _index, _name in enumerate(_WEEKDAYS):
    _WEEKDAY_INDEX[_name] = _index
    _WEEKDAY_INDEX[_name[:3]] = _index
_WEEKDAY_INDEX.update({"tues": 1, "thur": 3, "thurs": 3})

_MONTHS = {
    name: number
    for number, name in enumerate(
        ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"),
        start=1,
    )
}

_RELATIVE_OFFSETS = {"today": 0, "tonight": 0, "tomorrow": 1, "yesterday": -1}
_RELATIVE_WORD_RE = re.compile(r"\b(today|tonight|tomorrow|yesterday)\b", re.IGNORECASE)
_SCHEDULE_LINE_RE = re.compile(r"^\s*[-*•]?\s*([A-Za-z]+)\s*[:–—-]\s*(\S.*?)\s*$")


def get_zone(tz_name: str | None) -> tzinfo:
    """Resolve an IANA zone name, falling back to the host's local zone."""
    try:
        return ZoneInfo(tz_name or DEFAULT_TIMEZONE)
    except (ZoneInfoNotFoundError, ValueError):
        # e.g. Windows without the tzdata package installed
        logger.warning("Timezone %r unavailable; using the host clock's zone", tz_name)
        return datetime.now().astimezone().tzinfo or timezone.utc


def now(tz_name: str | None = None) -> datetime:
    """Current time as an aware datetime in the configured zone."""
    return datetime.now(get_zone(tz_name))


def today(tz_name: str | None = None) -> date:
    """Current date in the configured zone."""
    return now(tz_name).date()


def parse_iso(value: str | None) -> datetime | None:
    """Parse an ISO-8601 timestamp (naive or aware); None if unparseable."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError):
        return None


def from_utc_naive(value: str | None, tz_name: str | None = None) -> datetime | None:
    """Parse a naive-UTC timestamp (SQLite CURRENT_TIMESTAMP) into local time."""
    parsed = parse_iso(value)
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(get_zone(tz_name))


def from_local_naive(value: str | None, tz_name: str | None = None) -> datetime | None:
    """Parse a naive local wall-clock timestamp (e.g. sync_metadata) as local time."""
    parsed = parse_iso(value)
    if parsed is None:
        return None
    zone = get_zone(tz_name)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=zone)
    return parsed.astimezone(zone)


def short_date(d: date) -> str:
    """'Mon Sep 14' (built by hand because %-d isn't portable to Windows)."""
    return f"{d:%a} {d:%b} {d.day}"


def relative_day(d: date, ref: date) -> str:
    """'today', 'tomorrow', 'yesterday', '3 days ago', or 'in 3 days'."""
    delta = (d - ref).days
    if delta == 0:
        return "today"
    if delta == 1:
        return "tomorrow"
    if delta == -1:
        return "yesterday"
    return f"in {delta} days" if delta > 0 else f"{-delta} days ago"


def day_label(d: date, ref: date) -> str:
    """'Sun Sep 13 (yesterday)'."""
    return f"{short_date(d)} ({relative_day(d, ref)})"


def clock_time(dt: datetime) -> str:
    """'8:41 PM'."""
    return dt.strftime("%I:%M %p").lstrip("0")


def timestamp_label(dt: datetime) -> str:
    """'Fri Sep 11, 8:41 PM EDT'."""
    return f"{short_date(dt.date())}, {clock_time(dt)} {dt.strftime('%Z')}".rstrip()


def age_phrase(then: datetime, ref: datetime) -> str:
    """Coarse elapsed time: 'just now', '40 min ago', '9 hours ago', '2.5 days ago'."""
    seconds = (ref - then).total_seconds()
    if seconds < 90:
        return "just now"
    minutes = seconds / 60
    if minutes < 90:
        return f"{minutes:.0f} min ago"
    hours = minutes / 60
    if hours < 36:
        return f"{hours:.0f} hours ago"
    return f"{hours / 24:.1f} days ago"


def weekday_index(name: str) -> int | None:
    """0 for Monday through 6 for Sunday; accepts full or abbreviated English names."""
    return _WEEKDAY_INDEX.get(name.strip().rstrip(".,").lower())


def next_weekday(name: str, after: date) -> date | None:
    """The first date strictly after `after` that falls on weekday `name`."""
    index = weekday_index(name)
    if index is None:
        return None
    return after + timedelta(days=(index - after.weekday()) % 7 or 7)


def resolve_month_day(month: str, day: int, near: date) -> date | None:
    """Resolve 'Sep 15' to the matching date closest to `near` (handles year rollover)."""
    month_number = _MONTHS.get(month.strip().rstrip(".,")[:3].lower())
    if month_number is None:
        return None
    candidates = []
    for year in (near.year - 1, near.year, near.year + 1):
        try:
            candidates.append(date(year, month_number, day))
        except ValueError:
            continue
    return min(candidates, key=lambda c: abs((c - near).days)) if candidates else None


def map_schedule_to_dates(schedule: str, start: date, days: int = 7) -> list[tuple[date, str]]:
    """Map 'Monday: Rest'-style lines onto the `days` dates beginning at `start`.

    Returns [] when no line names a weekday, so callers can fall back to the
    raw schedule text.
    """
    by_weekday: dict[int, str] = {}
    for line in schedule.splitlines():
        match = _SCHEDULE_LINE_RE.match(line)
        if match and (index := weekday_index(match.group(1))) is not None:
            by_weekday[index] = match.group(2)
    if not by_weekday:
        return []
    dates = (start + timedelta(days=offset) for offset in range(days))
    return [(d, by_weekday[d.weekday()]) for d in dates if d.weekday() in by_weekday]


def annotate_relative_words(text: str, written_on: date) -> str:
    """Pin 'today'/'tomorrow'/'yesterday' to the dates they meant when written.

    'If today feels normal', written on Mon Sep 14, becomes
    'If today [Mon Sep 14] feels normal'.
    """

    def pin(match: re.Match) -> str:
        word = match.group(1)
        meant = written_on + timedelta(days=_RELATIVE_OFFSETS[word.lower()])
        return f"{word} [{short_date(meant)}]"

    return _RELATIVE_WORD_RE.sub(pin, text)
