"""Continuity between daily reports, with every day resolved to a date.

Earlier reports are never fed back in as prose. Their numbers go stale when
Garmin revises a day after a report ran (a mid-morning resting HR of 75 that
settles at 47), and their "today"/"tomorrow" wording means something else a
day later. Instead, each report saves the numbers it used to
``analysis-YYYY-MM-DD.json`` beside its markdown, and the next report gets a
section built in code: recent one-line calls, activity recorded since the
previous report, that report's plan with dates resolved, and values revised
since it ran.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable

from garmin_sync import temporal

logger = logging.getLogger(__name__)

# The report format mandates a `Today: <call>` line; this also matches older
# "## Today: **Yellow — easy only**" headings. Reports without one contribute
# no verdict.
_VERDICT_RE = re.compile(
    r"^[#>\s*\d).-]*today['’]?s?(?:\s+call)?\s*:\s*(.+)$",
    re.IGNORECASE | re.MULTILINE,
)
_WEEK_AHEAD_RE = re.compile(r"\bweek\s+ahead\b", re.IGNORECASE)
# A section title written as a standalone bold line, e.g. "**Week ahead**"
_BOLD_TITLE_RE = re.compile(r"^(?:\d+[.)]\s*)?\*\*[^*]+\*\*:?$")
# "- Tuesday: ...", "- Tue Sep 15: ...", "- Tomorrow: ..." (bold markers removed first)
_PLAN_BULLET_RE = re.compile(
    r"^(?:[-*•]|\d+[.)])\s+"
    r"(?P<label>[A-Za-z]{3,9}\.?(?:,?\s+[A-Za-z]{3,9}\.?\s+\d{1,2})?)"
    r"(?:\s*:|\s+[—–-])\s*(?P<text>\S.*)$"
)
# "Morning signal that changes the plan: ...", "What would change the plan: ..."
_CRITERIA_RE = re.compile(
    r"^[^:]{0,60}\bchang\w*\s+(?:the\s+|this\s+)?plan[^:]*:\s*(?P<text>\S.*)$",
    re.IGNORECASE,
)

# metric: (detailed_7d series, value field, smallest change worth reporting, label, format)
_TRACKED_METRICS: dict[str, tuple[str, str, float, str, str]] = {
    "resting_hr": ("daily_rhr", "value", 3, "resting HR", "{:.0f} bpm"),
    "hrv": ("daily_hrv", "value", 5, "HRV", "{:.0f} ms"),
    "sleep_hours": ("daily_sleep", "hours", 0.5, "sleep", "{:.1f} h"),
    "body_battery_morning": ("daily_body_battery", "morning", 10, "morning body battery", "{:.0f}"),
    "training_load": ("daily_training_load", "load", 25, "training load", "{:.0f}"),
}


def report_path(reports_dir: Path, day: date) -> Path:
    return reports_dir / f"analysis-{day.isoformat()}.md"


def snapshot_path(reports_dir: Path, day: date) -> Path:
    return reports_dir / f"analysis-{day.isoformat()}.json"


def extract_verdict(report_text: str) -> str | None:
    """Pull the one-line daily verdict out of a saved analysis report."""
    match = _VERDICT_RE.search(report_text)
    if not match:
        return None
    verdict = match.group(1).replace("*", "").replace("`", "").strip(" .:-—")
    return _truncate(verdict, 140) if verdict else None


def extract_plan(report_text: str, written_on: date) -> list[tuple[date, str]]:
    """Day-labelled bullets from a report's "Week ahead" section, dates resolved.

    Weekday labels ("Tuesday") resolve to the next such day after the report
    date; dated labels ("Tue Sep 15") are taken as written. Relative words in
    the bullet text are pinned to the report date.
    """
    plan: list[tuple[date, str]] = []
    section_level: int | None = None
    for raw in report_text.splitlines():
        stripped = raw.strip()
        level = _title_level(stripped)
        line = stripped.replace("**", "")
        if level is not None:
            if _WEEK_AHEAD_RE.search(line):
                section_level = level
            elif section_level is not None and level <= section_level:
                section_level = None
            continue
        if section_level is None:
            continue
        if line.startswith("---"):
            section_level = None
            continue
        match = _PLAN_BULLET_RE.match(line)
        day = _resolve_label(match.group("label"), written_on) if match else None
        if day is None:
            continue
        text = temporal.annotate_relative_words(_clean(match.group("text")), written_on)
        plan.append((day, _truncate(text, 240)))
    return plan


def extract_plan_criteria(report_text: str, written_on: date) -> str | None:
    """The report's closing "signal that changes the plan" line, relative words pinned."""
    for raw in reversed(report_text.splitlines()):
        match = _CRITERIA_RE.match(raw.replace("**", "").strip())
        if match:
            text = temporal.annotate_relative_words(_clean(match.group("text")), written_on)
            return _truncate(text, 400)
    return None


def summarize_decisions(report_text: str, written_on: date, ref: date) -> str | None:
    """A report's decisions without its numbers: the daily call and the dated plan."""
    lines = []
    verdict = extract_verdict(report_text)
    if verdict:
        lines.append(f"- Call for {temporal.day_label(written_on, ref)}: {verdict}")
    lines.extend(
        f"- Planned {temporal.day_label(day, ref)}: {text}"
        for day, text in extract_plan(report_text, written_on)
    )
    criteria = extract_plan_criteria(report_text, written_on)
    if criteria:
        lines.append(f"- Plan-change criteria: {criteria}")
    return "\n".join(lines) or None


def build_snapshot(
    detailed_7d: dict[str, Any], report_date: date, generated_at: datetime
) -> dict[str, Any]:
    """The per-day numbers a report was built from, for comparison the next day."""
    metrics = {
        key: {row["date"]: row.get(field) for row in detailed_7d.get(series) or [] if row.get("date")}
        for key, (series, field, *_rest) in _TRACKED_METRICS.items()
    }
    return {
        "report_date": report_date.isoformat(),
        "generated_at": generated_at.isoformat(timespec="seconds"),
        "metrics": metrics,
    }


def save_snapshot(reports_dir: Path, snapshot: dict[str, Any]) -> Path:
    path = snapshot_path(reports_dir, date.fromisoformat(snapshot["report_date"]))
    path.write_text(json.dumps(snapshot, indent=2))
    return path


def load_snapshot(reports_dir: Path, day: date) -> dict[str, Any] | None:
    path = snapshot_path(reports_dir, day)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        logger.warning("Ignoring unreadable report snapshot %s", path)
        return None
    return data if isinstance(data, dict) and "metrics" in data else None


def find_revisions(previous: dict[str, Any], current: dict[str, Any], ref: date) -> list[str]:
    """Values that changed materially after the previous report captured them."""
    previous_report_day = previous.get("report_date", "")
    lines: list[str] = []
    for key, (_series, _field, min_change, label, fmt) in _TRACKED_METRICS.items():
        before = previous.get("metrics", {}).get(key, {})
        after = current.get("metrics", {}).get(key, {})
        for day_str in sorted(set(before) & set(after)):
            if key == "training_load" and day_str >= previous_report_day:
                continue  # load on the report's own day was still accumulating
            old, new = before[day_str], after[day_str]
            if old is None and new is None:
                continue
            if old is None:
                change = f"not recorded at report time, now {fmt.format(new)}"
            elif new is None:
                change = f"{fmt.format(old)} at report time, now missing"
            elif abs(new - old) >= min_change:
                change = f"{fmt.format(old)} at report time, now {fmt.format(new)}"
            else:
                continue
            in_progress = day_str == previous_report_day
            note = " (that day was still in progress when the report ran)" if in_progress else ""
            label_day = temporal.day_label(date.fromisoformat(day_str), ref)
            lines.append(f"{label_day} {label}: {change}{note}")
    return lines


def build_continuity_section(
    reports_dir: Path,
    today: date,
    current_snapshot: dict[str, Any],
    activities_on: Callable[[date], Iterable[Any]],
    tz_name: str | None = None,
    lookback_days: int = 7,
) -> str | None:
    """Render the continuity section for today's report; None without prior reports.

    Args:
        reports_dir: Directory holding ``analysis-*.md`` and ``analysis-*.json``
        today: Date of the report being generated
        current_snapshot: ``build_snapshot`` output for today's data
        activities_on: Returns the activities recorded on a local date
        tz_name: Configured timezone, used to label when earlier reports ran
        lookback_days: How many prior days of reports to consider
    """
    reports: list[tuple[date, str]] = []
    for offset in range(lookback_days, 0, -1):
        day = today - timedelta(days=offset)
        path = report_path(reports_dir, day)
        if not path.exists():
            continue
        try:
            reports.append((day, path.read_text()))
        except OSError:
            logger.debug("Could not read previous analysis %s", path)
    if not reports:
        return None

    parts = [
        "## Continuity",
        "Computed from saved reports and synced data. Numbers quoted in earlier "
        "reports can be revised later; trust the current data sections below.",
        "",
    ]

    calls = [(day, verdict) for day, text in reports if (verdict := extract_verdict(text))]
    if calls:
        parts.append("Recent daily calls (oldest first):")
        parts.extend(f"- {temporal.day_label(day, today)}: {verdict}" for day, verdict in calls)
        parts.append("")

    previous_day, previous_text = reports[-1]

    recorded = []
    day = max(previous_day, today - timedelta(days=3))
    while day < today:
        recorded.append(
            f"- {temporal.day_label(day, today)}: {_describe_activities(activities_on(day))}"
        )
        day += timedelta(days=1)
    so_far = list(activities_on(today))
    if so_far:
        recorded.append(
            f"- {temporal.day_label(today, today)}, so far: {_describe_activities(so_far)}"
        )
    if recorded:
        parts.append(f"Activity recorded from {temporal.short_date(previous_day)} onward:")
        parts.extend(recorded)
        parts.append("")

    previous_snapshot = load_snapshot(reports_dir, previous_day)
    plan = [
        (day, text)
        for day, text in extract_plan(previous_text, previous_day)
        if day <= today + timedelta(days=3)
    ]
    criteria = extract_plan_criteria(previous_text, previous_day)
    if plan or criteria:
        written = _written_label(reports_dir, previous_day, previous_snapshot, tz_name)
        parts.append(f'<previous_plan written="{written}">')
        parts.extend(f"- {temporal.day_label(day, today)}: {text}" for day, text in plan)
        if criteria:
            parts.append(f"Plan-change criteria: {criteria}")
        parts.append("</previous_plan>")
        parts.append("")

    if previous_snapshot:
        revisions = find_revisions(previous_snapshot, current_snapshot, today)
        if revisions:
            parts.append(f"Values revised since the {temporal.short_date(previous_day)} report ran:")
            parts.extend(f"- {line}" for line in revisions)
            parts.append("")

    return "\n".join(parts).rstrip()


def _title_level(line: str) -> int | None:
    """Depth of a section title: its markdown heading level, 7 for a bold title line."""
    if line.startswith("#"):
        return len(line) - len(line.lstrip("#"))
    if _BOLD_TITLE_RE.match(line):
        return 7  # nests below any markdown heading
    return None


def _resolve_label(label: str, written_on: date) -> date | None:
    tokens = label.replace(",", " ").split()
    first = tokens[0].lower().rstrip(".")
    if first == "today":
        return written_on
    if first == "tomorrow":
        return written_on + timedelta(days=1)
    if len(tokens) == 3 and tokens[2].isdigit():
        dated = temporal.resolve_month_day(tokens[1], int(tokens[2]), written_on)
        if dated is not None:
            return dated
    return temporal.next_weekday(tokens[0], written_on)


def _describe_activities(activities: Iterable[Any]) -> str:
    items = []
    total_load = 0.0
    for act in sorted(activities, key=lambda a: a.start_time_local or a.start_time or ""):
        kind = (act.activity_type or "activity").replace("_", " ")
        minutes = round((act.duration_seconds or 0) / 60)
        started = temporal.parse_iso(act.start_time_local)
        at = f" at {temporal.clock_time(started)}" if started else ""
        items.append(f"{kind} {minutes} min{at}")
        total_load += act.training_load or 0
    if not items:
        return "no activities recorded"
    load = f" (total load {total_load:.0f})" if total_load else ""
    return "; ".join(items) + load


def _written_label(
    reports_dir: Path, day: date, snapshot: dict[str, Any] | None, tz_name: str | None
) -> str:
    generated = temporal.from_local_naive((snapshot or {}).get("generated_at"), tz_name)
    if generated is None:
        try:
            mtime = report_path(reports_dir, day).stat().st_mtime
        except OSError:
            return temporal.short_date(day)
        generated = datetime.fromtimestamp(mtime, tz=temporal.get_zone(tz_name))
    return temporal.timestamp_label(generated)


def _clean(text: str) -> str:
    return " ".join(text.replace("`", "").split())


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"
