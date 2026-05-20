"""Windows Task Scheduler management.

Uses ``schtasks.exe`` (built into all Windows versions) to create daily
sync + analysis tasks.  Two tasks are registered so weekdays and weekends
can run at different times:

* ``GarminSync-Weekday`` — Mon-Fri at ``weekday_hour``
* ``GarminSync-Weekend`` — Sat-Sun at ``weekend_hour``

A small batch wrapper is written to the log directory so that output can
be captured to a log file (Task Scheduler itself has no built-in stdout
redirection).
"""

import csv
import io
import shutil
import subprocess
from pathlib import Path

TASK_WEEKDAY = "GarminSync-Weekday"
TASK_WEEKEND = "GarminSync-Weekend"
TASK_NAMES = (TASK_WEEKDAY, TASK_WEEKEND)

BAT_TEMPLATE = """\
@echo off
echo %date% %time%: Starting daily sync... >> "{log_file}" 2>&1
"{garmin_sync_path}" sync all --days 1 --detailed >> "{log_file}" 2>&1
"{garmin_sync_path}" analyze >> "{log_file}" 2>&1
echo %date% %time%: Done. >> "{log_file}" 2>&1
"""


_BATCH_UNSAFE = set('"&|<>^%!')


def _validate_batch_path(path: str, label: str) -> None:
    """Raise if a path contains characters that could break a batch script."""
    bad = _BATCH_UNSAFE & set(path)
    if bad:
        raise ValueError(
            f"{label} contains unsafe characters for a batch script: {bad!r}"
        )


def _write_batch_script(
    garmin_sync_path: str,
    log_dir: Path,
) -> Path:
    """Write (or overwrite) the batch wrapper and return its path."""
    _validate_batch_path(garmin_sync_path, "garmin-sync path")
    _validate_batch_path(str(log_dir), "log directory")

    log_file = log_dir / "sync.log"
    bat_path = log_dir / "garmin-sync-daily.bat"
    bat_path.write_text(
        BAT_TEMPLATE.format(
            garmin_sync_path=garmin_sync_path,
            log_file=str(log_file),
        ),
        encoding="utf-8",
    )
    return bat_path


def install(
    log_dir: Path,
    weekday_hour: int = 7,
    weekend_hour: int = 10,
) -> tuple[bool, str]:
    """Create Windows scheduled tasks for daily sync + analysis.

    Returns:
        Tuple of (success, message)
    """
    garmin_sync_path = shutil.which("garmin-sync")
    if not garmin_sync_path:
        return False, "garmin-sync not found in PATH. Ensure it's installed."

    log_dir.mkdir(parents=True, exist_ok=True)
    bat_path = _write_batch_script(garmin_sync_path, log_dir)

    weekday_time = f"{weekday_hour:02d}:00"
    weekend_time = f"{weekend_hour:02d}:00"

    tasks = [
        (TASK_WEEKDAY, "MON,TUE,WED,THU,FRI", weekday_time),
        (TASK_WEEKEND, "SAT,SUN", weekend_time),
    ]

    for task_name, days, start_time in tasks:
        result = subprocess.run(
            [
                "schtasks", "/Create",
                "/TN", task_name,
                "/TR", str(bat_path),
                "/SC", "WEEKLY",
                "/D", days,
                "/ST", start_time,
                "/F",  # force overwrite if exists
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return False, f"Failed to create task {task_name}: {result.stderr.strip()}"

    return True, f"Installed successfully. Tasks: {', '.join(TASK_NAMES)}"


def uninstall() -> tuple[bool, str]:
    """Remove the Windows scheduled tasks."""
    errors = []
    for task_name in TASK_NAMES:
        result = subprocess.run(
            ["schtasks", "/Delete", "/TN", task_name, "/F"],
            capture_output=True,
            text=True,
        )
        # Return code 1 with "cannot find" means it wasn't there — that's OK
        if result.returncode != 0 and "cannot find" not in result.stderr.lower():
            errors.append(f"{task_name}: {result.stderr.strip()}")

    if errors:
        return False, "Errors removing tasks: " + "; ".join(errors)
    return True, "Uninstalled successfully"


def _query_task(task_name: str) -> dict | None:
    """Query a single task and return parsed info, or None if not found."""
    result = subprocess.run(
        ["schtasks", "/Query", "/TN", task_name, "/FO", "CSV", "/V"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None

    reader = csv.DictReader(io.StringIO(result.stdout))
    for row in reader:
        return {
            "task_name": row.get("TaskName", task_name),
            "status": row.get("Status", "Unknown"),
            "next_run": row.get("Next Run Time", "N/A"),
            "last_run": row.get("Last Run Time", "N/A"),
            "last_result": row.get("Last Result", "N/A"),
        }
    return None


def get_status() -> dict:
    """Get current scheduler status."""
    weekday_info = _query_task(TASK_WEEKDAY)
    weekend_info = _query_task(TASK_WEEKEND)

    installed = weekday_info is not None or weekend_info is not None

    status: dict = {
        "installed": installed,
        "loaded": installed,  # Windows tasks are always "loaded" if they exist
        "schedule": None,
        "tasks": {},
    }

    if weekday_info:
        status["tasks"]["weekday"] = weekday_info
    if weekend_info:
        status["tasks"]["weekend"] = weekend_info

    if installed:
        status["schedule"] = {
            "weekday_time": weekday_info["next_run"] if weekday_info else "N/A",
            "weekend_time": weekend_info["next_run"] if weekend_info else "N/A",
        }

    return status
