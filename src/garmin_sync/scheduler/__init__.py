"""Scheduler management for automatic syncing.

Provides a platform-aware factory that returns the correct scheduler
backend: ``launchd`` on macOS, ``windows_task`` on Windows, or ``None``
on unsupported platforms (Linux users can set up crontab manually).

Each backend exposes the same three functions::

    install(log_dir: Path) -> tuple[bool, str]
    uninstall()           -> tuple[bool, str]
    get_status()          -> dict
"""

import platform
from types import ModuleType
from typing import Optional


def get_scheduler() -> Optional[ModuleType]:
    """Return the scheduler module for the current OS, or None."""
    system = platform.system()
    if system == "Darwin":
        from garmin_sync.scheduler import launchd
        return launchd
    elif system == "Windows":
        from garmin_sync.scheduler import windows_task
        return windows_task
    return None
