"""macOS launchd scheduler management."""

import plistlib
import shlex
import shutil
import subprocess
from pathlib import Path

from garmin_sync.config.paths import default_data_dir

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
        f'(osascript -e \'display notification "Your daily fitness analysis is ready" with title "Garmin Sync" sound name "Glass"\' || true) && '
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
    """Get current scheduler status."""
    plist_path = get_plist_path()

    status = {
        "installed": plist_path.exists(),
        "plist_path": str(plist_path),
        "loaded": False,
        "schedule": None,
    }

    if not plist_path.exists():
        return status

    # Check if loaded
    result = subprocess.run(
        ["launchctl", "list", LABEL],
        capture_output=True,
        text=True,
    )
    status["loaded"] = result.returncode == 0

    # Parse schedule from plist
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
            "weekday_time": f"{weekday_hour}:00 AM" if weekday_hour else None,
            "weekend_time": f"{weekend_hour}:00 AM" if weekend_hour else None,
        }
    except Exception:
        pass

    return status
