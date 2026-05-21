"""AI configuration management.

Configuration is split across two files:

* ``config.toml`` — API keys and technical settings (chmod 0o600).
* ``profile.toml`` — training schedule, goals, timezone (chmod 0o644).

For backward compatibility, ``load_config`` falls back to reading
``[analysis]`` from ``config.toml`` when ``profile.toml`` is absent.
"""

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

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

    return AIConfig(
        api_key=api_key,
        model=openai_section.get("model", "o3-mini"),
        enabled=openai_section.get("enabled", True),
        use_tools=openai_section.get("use_tools", True),
        schedule=training_section.get("schedule", DEFAULT_SCHEDULE),
        user_context=training_section.get("user_context", ""),
        timezone=training_section.get("timezone", "America/New_York"),
        hevy=hevy_config,
    )


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

    with open(path, "wb") as f:
        tomli_w.dump(config_data, f)

    try:
        path.chmod(0o600)
        path.parent.chmod(0o700)
    except OSError as e:
        print(f"Warning: could not tighten permissions on {path}: {e}", file=sys.stderr)

    # --- profile.toml (training profile) ---
    profile_path.parent.mkdir(parents=True, exist_ok=True)

    profile_data = {
        "training": {
            "schedule": config.schedule,
            "user_context": config.user_context,
            "timezone": config.timezone,
        },
    }

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

    # Rewrite config.toml without [analysis]
    del config_data["analysis"]
    with open(config_path, "wb") as f:
        tomli_w.dump(config_data, f)

    try:
        config_path.chmod(0o600)
    except OSError:
        pass

    return True
