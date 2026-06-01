"""Platform-aware default paths.

Uses ``platformdirs`` for Windows/Linux, but preserves the existing
XDG-style layout on macOS for backward compatibility (the database and
config have lived at ``~/.local/share/garmin-sync`` and
``~/.config/garmin-sync`` since day one).

* **macOS**: ``~/.local/share/garmin-sync`` (data),
  ``~/.config/garmin-sync`` (config) — unchanged from the original.
* **Windows**: ``%%LOCALAPPDATA%%\\garmin-sync`` for both.
* **Linux**: ``~/.local/share/garmin-sync`` (data),
  ``~/.config/garmin-sync`` (config) — via platformdirs XDG.

Every other module that needs a default path imports from here instead of
hard-coding ``Path.home() / ".local/share/..."``.
"""

import sys
from pathlib import Path

from platformdirs import user_config_dir, user_data_dir


def default_data_dir() -> Path:
    """Return the platform-native data directory for garmin-sync."""
    if sys.platform == "darwin":
        # Preserve existing XDG layout — the DB and reports have always
        # lived here; switching to ~/Library/Application Support would
        # orphan existing data.
        return Path.home() / ".local" / "share" / "garmin-sync"
    # appauthor=False avoids platformdirs' default of repeating the app name as
    # the author segment on Windows (…\garmin-sync\garmin-sync).
    return Path(user_data_dir("garmin-sync", appauthor=False, ensure_exists=False))


def default_config_dir() -> Path:
    """Return the platform-native config directory for garmin-sync."""
    if sys.platform == "darwin":
        return Path.home() / ".config" / "garmin-sync"
    return Path(user_config_dir("garmin-sync", appauthor=False, ensure_exists=False))


def default_config_path() -> Path:
    """Return the platform-native path to ``config.toml``."""
    return default_config_dir() / "config.toml"


def default_profile_path() -> Path:
    """Return the platform-native path to ``profile.toml``.

    The profile file stores training schedule, goals, and timezone —
    non-secret data that is safe to share or version-control.
    """
    return default_config_dir() / "profile.toml"


def default_garth_token_dir() -> Path:
    """Return the default directory for garth OAuth tokens.

    The ``garth`` library itself writes to ``~/.garminconnect`` on every
    platform, so we keep that convention.  Moving it would break token
    discovery after ``garmin-sync auth login``.  Users who need a
    different location can override via the
    ``GARMIN_SYNC_GARTH_TOKEN_DIR`` environment variable.
    """
    return Path.home() / ".garminconnect"
