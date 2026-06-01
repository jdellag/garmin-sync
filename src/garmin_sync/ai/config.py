"""AI configuration management.

Configuration is split across two files:

* ``config.toml`` — API keys and technical settings (chmod 0o600).
* ``profile.toml`` — training schedule, goals, timezone (chmod 0o644).

For backward compatibility, ``load_config`` falls back to reading
``[analysis]`` from ``config.toml`` when ``profile.toml`` is absent.
"""

import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

import tomli_w

# tomllib is built-in for Python 3.11+, use tomli as fallback
if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomli as tomllib
    except ImportError:
        tomllib = None  # type: ignore[assignment]

from garmin_sync.config.paths import default_config_path, default_profile_path

DEFAULT_CONFIG_PATH = default_config_path()
DEFAULT_PROFILE_PATH = default_profile_path()

DEFAULT_SCHEDULE = """Monday: Rest day or easy recovery
Tuesday: Speed/interval workout
Wednesday: Easy run
Thursday: Tempo or threshold run
Friday: Rest or cross-training
Saturday: Long run
Sunday: Easy run or rest"""


# Science-backed weekly set targets per muscle group (moderate general fitness).
# Sources: Schoenfeld (2017), Renaissance Periodization volume landmarks.
# Users can override any group in profile.toml [strength] section.
DEFAULT_WEEKLY_SET_TARGETS: dict[str, int] = {
    "quadriceps": 10,
    "hamstrings": 8,
    "glutes": 10,
    "chest": 10,
    "lats": 10,
    "shoulders": 10,
    "upper_back": 8,
    "biceps": 6,
    "triceps": 6,
    "traps": 6,
    "calves": 6,
    "abdominals": 8,
    "forearms": 4,
    "adductors": 4,
    "abductors": 4,
    "lower_back": 4,
}

# Fallback for any muscle group not in the defaults
_DEFAULT_FALLBACK_SETS = 6


@dataclass
class StrengthConfig:
    """Configuration for strength training targets."""

    weekly_set_targets: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_WEEKLY_SET_TARGETS))

    def get_target(self, muscle_group: str) -> int:
        """Get weekly set target for a muscle group."""
        return self.weekly_set_targets.get(muscle_group, _DEFAULT_FALLBACK_SETS)


@dataclass
class HevyConfig:
    """Configuration for HEVY integration."""

    api_key: Optional[str] = None
    enabled: bool = True
    sync_days: int = 30

    def is_configured(self) -> bool:
        """Check if HEVY is properly configured with an API key."""
        return bool(self.api_key)


@dataclass
class AIConfig:
    """Configuration for AI analysis."""

    api_key: Optional[str] = None
    model: str = "o3-mini"
    enabled: bool = True
    use_tools: bool = True  # Enable tool calling in chat
    schedule: str = field(default_factory=lambda: DEFAULT_SCHEDULE)
    user_context: str = ""
    timezone: str = "America/New_York"
    hevy: HevyConfig = field(default_factory=HevyConfig)
    strength: StrengthConfig = field(default_factory=StrengthConfig)

    def is_configured(self) -> bool:
        """Check if AI is properly configured with an API key."""
        return bool(self.api_key)


def _read_toml(path: Path) -> dict:
    """Read a TOML file, returning an empty dict on any failure."""
    if not path.exists() or tomllib is None:
        return {}
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except Exception:
        logger.debug("Failed to read TOML file %s", path, exc_info=True)
        return {}


def load_config(
    path: Optional[Path] = None,
    profile_path: Optional[Path] = None,
) -> AIConfig:
    """Load AI config from TOML files.

    Secrets and technical settings come from *config.toml*; training
    profile data comes from *profile.toml*.  When *profile.toml* does
    not exist the loader falls back to the ``[analysis]`` section in
    *config.toml* (the pre-split layout).

    Args:
        path: Path to config.toml (defaults to platform default).
        profile_path: Path to profile.toml (defaults to platform default).

    Returns:
        AIConfig instance with loaded values or defaults.
    """
    if path is None:
        path = DEFAULT_CONFIG_PATH
    if profile_path is None:
        profile_path = DEFAULT_PROFILE_PATH

    config_data = _read_toml(path)
    if not config_data and not profile_path.exists():
        return AIConfig()

    openai_section = config_data.get("openai", {})
    hevy_section = config_data.get("hevy", {})

    # Profile: prefer profile.toml, fall back to [analysis] in config.toml
    profile_data = _read_toml(profile_path)
    training_section = profile_data.get("training", {})
    if not training_section:
        # Legacy fallback — old single-file layout
        training_section = config_data.get("analysis", {})

    # Handle empty strings as None for api_key
    api_key = openai_section.get("api_key")
    if api_key == "":
        api_key = None

    hevy_api_key = hevy_section.get("api_key")
    if hevy_api_key == "":
        hevy_api_key = None

    hevy_config = HevyConfig(
        api_key=hevy_api_key,
        enabled=hevy_section.get("enabled", True),
        sync_days=hevy_section.get("sync_days", 30),
    )

    # Strength: merge user overrides from [strength] over defaults.
    # Accept only positive ints — reject booleans (isinstance(True, int) is
    # True in Python) and non-positive targets, which would otherwise poison
    # the muscle-group target comparisons and AI prompt.
    strength_section = profile_data.get("strength", {})
    merged_targets = dict(DEFAULT_WEEKLY_SET_TARGETS)
    for group, sets in strength_section.items():
        if isinstance(sets, bool) or not isinstance(sets, int) or sets <= 0:
            logger.warning("Ignoring invalid strength target for %r: %r", group, sets)
            continue
        merged_targets[group] = sets
    strength_config = StrengthConfig(weekly_set_targets=merged_targets)

    return AIConfig(
        api_key=api_key,
        model=openai_section.get("model", "o3-mini"),
        enabled=openai_section.get("enabled", True),
        use_tools=openai_section.get("use_tools", True),
        schedule=training_section.get("schedule", DEFAULT_SCHEDULE),
        user_context=training_section.get("user_context", ""),
        timezone=training_section.get("timezone", "America/New_York"),
        hevy=hevy_config,
        strength=strength_config,
    )


def _write_secret_toml(path: Path, data: dict) -> None:
    """Write a TOML file that contains secrets with owner-only (0o600) perms.

    The descriptor is tightened to 0o600 *before* the secret is written, so the
    API key is never momentarily present in a world-readable file — this also
    covers re-saving over a pre-existing loose-mode (0o644) file, which
    ``open()`` + later ``chmod()`` would leave briefly exposed.
    """
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        try:
            os.fchmod(fd, 0o600)
        except (AttributeError, OSError):
            pass  # fchmod unavailable (e.g. Windows) — fall back to chmod below
        tomli_w.dump(data, f)
    try:
        path.chmod(0o600)
    except OSError as e:
        print(f"Warning: could not tighten permissions on {path}: {e}", file=sys.stderr)


def save_config(
    config: AIConfig,
    path: Optional[Path] = None,
    profile_path: Optional[Path] = None,
) -> None:
    """Save AI config to split TOML files.

    Secrets go to *config.toml* (0o600); training profile goes to
    *profile.toml* (0o644).  If the old ``[analysis]`` section exists
    in *config.toml* it is stripped on save.

    Args:
        config: AIConfig instance to save.
        path: Path to config.toml (defaults to platform default).
        profile_path: Path to profile.toml (defaults to platform default).
    """
    if path is None:
        path = DEFAULT_CONFIG_PATH
    if profile_path is None:
        profile_path = DEFAULT_PROFILE_PATH

    # --- config.toml (secrets + technical) ---
    path.parent.mkdir(parents=True, exist_ok=True)

    config_data = {
        "openai": {
            "api_key": config.api_key or "",
            "model": config.model,
            "enabled": config.enabled,
            "use_tools": config.use_tools,
        },
        "hevy": {
            "api_key": config.hevy.api_key or "",
            "enabled": config.hevy.enabled,
            "sync_days": config.hevy.sync_days,
        },
    }

    _write_secret_toml(path, config_data)

    try:
        path.parent.chmod(0o700)
    except OSError as e:
        print(f"Warning: could not tighten permissions on {path.parent}: {e}", file=sys.stderr)

    # --- profile.toml (training profile) ---
    profile_path.parent.mkdir(parents=True, exist_ok=True)

    # Only save strength overrides that differ from defaults
    strength_overrides = {
        group: sets
        for group, sets in config.strength.weekly_set_targets.items()
        if sets != DEFAULT_WEEKLY_SET_TARGETS.get(group, _DEFAULT_FALLBACK_SETS)
    }

    profile_data = {
        "training": {
            "schedule": config.schedule,
            "user_context": config.user_context,
            "timezone": config.timezone,
        },
    }
    if strength_overrides:
        profile_data["strength"] = strength_overrides

    with open(profile_path, "wb") as f:
        tomli_w.dump(profile_data, f)

    try:
        profile_path.chmod(0o644)
    except OSError as e:
        print(
            f"Warning: could not set permissions on {profile_path}: {e}",
            file=sys.stderr,
        )


def migrate_config_if_needed(
    config_path: Optional[Path] = None,
    profile_path: Optional[Path] = None,
) -> bool:
    """Migrate old single config.toml to the split layout.

    If *config.toml* contains an ``[analysis]`` section and
    *profile.toml* does not yet exist, the ``[analysis]`` data is
    written to *profile.toml* and removed from *config.toml*.

    Returns:
        ``True`` if migration was performed, ``False`` otherwise.
    """
    if config_path is None:
        config_path = DEFAULT_CONFIG_PATH
    if profile_path is None:
        profile_path = DEFAULT_PROFILE_PATH

    if profile_path.exists():
        return False

    config_data = _read_toml(config_path)
    analysis = config_data.get("analysis")
    if not analysis:
        return False

    # Write profile.toml from the old [analysis] section
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_data = {"training": analysis}
    with open(profile_path, "wb") as f:
        tomli_w.dump(profile_data, f)

    try:
        profile_path.chmod(0o644)
    except OSError:
        pass

    # Rewrite config.toml without [analysis] (secrets — write at 0o600).
    del config_data["analysis"]
    _write_secret_toml(config_path, config_data)

    return True
