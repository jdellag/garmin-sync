"""macOS launchd scheduler management."""

import logging
import plistlib
import shlex
import shutil
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from garmin_sync.config.paths import default_data_dir

logger = logging.getLogger(__name__)

PLIST_NAME = "com.garmin-sync.daily.plist"
LABEL = "com.garmin-sync.daily"


def get_plist_path() -> Path:
    """Get path to launchd plist file."""
    return Path.home() / "Library" / "LaunchAgents" / PLIST_NAME


def generate_plist(
    garmin_sync_path: str,
    log_dir: Path,
    weekday_hour: int = 7,
    weekend_hour: int = 10,
) -> dict:
    """Generate launchd plist configuration.

    Args:
        garmin_sync_path: Full path to garmin-sync executable
        log_dir: Directory for log files
        weekday_hour: Hour to run on weekdays (Mon-Fri)
        weekend_hour: Hour to run on weekends (Sat-Sun)

    The scheduled task runs sync followed by analyze (if configured),
    then shows a notification and opens the report.

    Includes catch-up logic: if the Mac was asleep during the scheduled
    time, the job will run when the Mac wakes up (via StartInterval backup).
    The command checks if today's analysis already exists to avoid duplicates.
    """
    reports_dir_q = shlex.quote(str(default_data_dir() / "reports"))
    gs_q = shlex.quote(garmin_sync_path)

    # Build command with idempotency check:
    # 1. Check if today's analysis already exists - if so, skip
    # 2. Run sync and analyze
    # 3. Show notification and open report
    # This allows both scheduled runs AND catch-up runs without duplication
    command = (
        f'REPORT={reports_dir_q}/analysis-$(date +%Y-%m-%d).md; '
        f'if [ -f "$REPORT" ]; then '
        f'echo "$(date): Analysis already exists for today, skipping."; '
        f'exit 0; '
        f'fi; '
        f'echo "$(date): Starting daily sync..."; '
        f'{gs_q} sync all --days 1 --detailed && '
        f'{gs_q} analyze && '
        f'{gs_q} analyze post-sync-check && '
        f'open "$REPORT"'
    )

    return {
        "Label": LABEL,
        "ProgramArguments": [
            "/bin/bash",
            "-c",
            command,
        ],
        "StartCalendarInterval": [
            # Weekdays (Mon=1 to Fri=5) at weekday_hour
            {"Weekday": 1, "Hour": weekday_hour, "Minute": 0},
            {"Weekday": 2, "Hour": weekday_hour, "Minute": 0},
            {"Weekday": 3, "Hour": weekday_hour, "Minute": 0},
            {"Weekday": 4, "Hour": weekday_hour, "Minute": 0},
            {"Weekday": 5, "Hour": weekday_hour, "Minute": 0},
            # Weekends (Sat=6, Sun=0) at weekend_hour
            {"Weekday": 6, "Hour": weekend_hour, "Minute": 0},
            {"Weekday": 0, "Hour": weekend_hour, "Minute": 0},
        ],
        # Backup interval: check every 2 hours in case scheduled run was missed
        # (e.g., Mac was asleep at 7 AM). The idempotency check prevents duplicates.
        "StartInterval": 7200,  # 2 hours in seconds
        "StandardOutPath": str(log_dir / "sync.log"),
        "StandardErrorPath": str(log_dir / "sync-error.log"),
        "RunAtLoad": False,
        "EnvironmentVariables": {
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "HOME": str(Path.home()),  # Ensure HOME is set for config paths
        },
    }


def install(log_dir: Path) -> tuple[bool, str]:
    """Install the launchd scheduled task.

    Returns:
        Tuple of (success, message)
    """
    # Find garmin-sync executable
    garmin_sync_path = shutil.which("garmin-sync")
    if not garmin_sync_path:
        return False, "garmin-sync not found in PATH. Ensure it's installed."

    plist_path = get_plist_path()

    # Unload existing if present
    if plist_path.exists():
        subprocess.run(
            ["launchctl", "unload", str(plist_path)],
            capture_output=True,
        )

    # Ensure directories exist
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)

    # Generate and write plist
    plist_data = generate_plist(garmin_sync_path, log_dir)
    with open(plist_path, "wb") as f:
        plistlib.dump(plist_data, f)

    # Load the plist
    result = subprocess.run(
        ["launchctl", "load", str(plist_path)],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        return False, f"Failed to load plist: {result.stderr}"

    return True, f"Installed successfully. Plist: {plist_path}"


def uninstall() -> tuple[bool, str]:
    """Remove the launchd scheduled task."""
    plist_path = get_plist_path()

    if not plist_path.exists():
        return True, "Not installed (nothing to remove)"

    # Unload
    subprocess.run(
        ["launchctl", "unload", str(plist_path)],
        capture_output=True,
    )

    # Remove file
    plist_path.unlink()

    return True, "Uninstalled successfully"


def get_status() -> dict:
    """Get current scheduler status including next run time and last sync info."""
    plist_path = get_plist_path()

    status = {
        "installed": plist_path.exists(),
        "plist_path": str(plist_path),
        "loaded": False,
        "schedule": None,
        "last_exit_status": None,
        "next_run": None,
        "last_sync_age": None,
    }

    if not plist_path.exists():
        return status

    # Check if loaded and get last exit status
    result = subprocess.run(
        ["launchctl", "list", LABEL],
        capture_output=True,
        text=True,
    )
    status["loaded"] = result.returncode == 0

    # Parse LastExitStatus from launchctl list output
    if result.returncode == 0 and result.stdout:
        for line in result.stdout.splitlines():
            if "LastExitStatus" in line:
                try:
                    # Format: "    "LastExitStatus" = 0;"
                    val = line.split("=")[-1].strip().rstrip(";")
                    status["last_exit_status"] = int(val)
                except (ValueError, IndexError):
                    pass

    # Parse schedule from plist
    intervals = []
    try:
        with open(plist_path, "rb") as f:
            plist_data = plistlib.load(f)

        intervals = plist_data.get("StartCalendarInterval", [])
        weekday_hour = None
        weekend_hour = None

        for interval in intervals:
            if interval.get("Weekday") in [1, 2, 3, 4, 5]:
                weekday_hour = interval.get("Hour")
            elif interval.get("Weekday") in [0, 6]:
                weekend_hour = interval.get("Hour")

        status["schedule"] = {
            "weekday_time": _format_hour(weekday_hour) if weekday_hour is not None else None,
            "weekend_time": _format_hour(weekend_hour) if weekend_hour is not None else None,
        }

        # Compute next run time from schedule
        status["next_run"] = _compute_next_run(intervals)

        # Get last sync age from log file
        log_path = plist_data.get("StandardOutPath")
        if log_path:
            status["last_sync_age"] = _get_last_sync_age(Path(log_path))

    except Exception:
        logger.debug("Failed to parse plist for status", exc_info=True)

    return status


def _compute_next_run(intervals: list[dict]) -> str | None:
    """Compute the next fire time from StartCalendarInterval entries.

    Launchd weekdays: 0=Sunday, 1=Monday, ..., 6=Saturday.
    Python weekdays: 0=Monday, ..., 6=Sunday.
    """
    if not intervals:
        return None

    now = datetime.now()
    # Python weekday (Mon=0) → launchd weekday (Sun=0)
    py_to_launchd = {0: 1, 1: 2, 2: 3, 3: 4, 4: 5, 5: 6, 6: 0}
    launchd_today = py_to_launchd[now.weekday()]

    candidates: list[datetime] = []
    for interval in intervals:
        target_day = interval.get("Weekday")
        target_hour = interval.get("Hour", 0)
        target_minute = interval.get("Minute", 0)

        if target_day is None:
            continue

        # Days until next occurrence of this weekday
        day_diff = (target_day - launchd_today) % 7
        candidate = now.replace(
            hour=target_hour, minute=target_minute, second=0, microsecond=0,
        ) + timedelta(days=day_diff)

        # If it's today but already passed, push to next week
        if candidate <= now:
            candidate += timedelta(days=7)

        candidates.append(candidate)

    if not candidates:
        return None

    next_fire = min(candidates)
    return next_fire.strftime("%Y-%m-%d %H:%M")


def _try_parse_date(text: str) -> datetime | None:
    """Try to parse a date string from $(date) or ISO format.

    Python's ``strptime(%Z)`` only recognises the *current system's*
    timezone abbreviations.  ``$(date)`` always uses the local timezone,
    so on the machine that wrote the log this works.  But to be safe we
    also try stripping the timezone token and parsing without it.
    """
    for fmt in ("%a %b %d %H:%M:%S %Z %Y", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except (ValueError, IndexError):
            continue

    # Fallback: strip the timezone token from BSD date(1) output.
    # "Mon May 26 07:00:00 PDT 2026" → "Mon May 26 07:00:00 2026"
    parts = text.split()
    if len(parts) == 6:
        no_tz = " ".join(parts[:4] + parts[5:])
        try:
            return datetime.strptime(no_tz, "%a %b %d %H:%M:%S %Y")
        except (ValueError, IndexError):
            pass

    return None


def _get_last_sync_age(log_path: Path) -> str | None:
    """Parse the last timestamp from the sync log and return a human-readable age."""
    if not log_path.exists():
        return None

    try:
        # Read last few lines (log starts each run with a date line)
        text = log_path.read_text().strip()
        if not text:
            return None

        # Find the most recent line starting with a date-like pattern.
        # The bash wrapper writes: "$(date): Starting daily sync..."
        # $(date) output length varies by timezone name (EDT=3, AEST=4, etc.)
        for line in reversed(text.splitlines()):
            line = line.strip()
            if not line:
                continue
            # Split on ": " to isolate the date prefix from the log message
            date_part = line.split(": ", 1)[0] if ": " in line else line
            ts = _try_parse_date(date_part)
            if ts is not None:
                delta = datetime.now() - ts
                return _format_timedelta(delta)

    except Exception:
        logger.debug("Failed to parse sync log age", exc_info=True)

    return None


def _format_hour(hour: int) -> str:
    """Format a 24-hour integer as a 12-hour time string."""
    if hour == 0:
        return "12:00 AM"
    if hour < 12:
        return f"{hour}:00 AM"
    if hour == 12:
        return "12:00 PM"
    return f"{hour - 12}:00 PM"


def _format_timedelta(delta: timedelta) -> str:
    """Format a timedelta as a human-readable age string."""
    total_seconds = int(delta.total_seconds())
    if total_seconds < 0:
        return "just now"
    if total_seconds < 60:
        return f"{total_seconds}s ago"
    minutes = total_seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    return f"{days}d ago"
