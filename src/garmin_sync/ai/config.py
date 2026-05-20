"""AI configuration management."""

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

from garmin_sync.config.paths import default_config_path

DEFAULT_CONFIG_PATH = default_config_path()

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


def load_config(path: Optional[Path] = None) -> AIConfig:
    """Load AI config from TOML file.

    Args:
        path: Path to config file (defaults to ~/.config/garmin-sync/config.toml)

    Returns:
        AIConfig instance with loaded values or defaults
    """
    if path is None:
        path = DEFAULT_CONFIG_PATH

    if not path.exists():
        return AIConfig()

    if tomllib is None:
        # Fallback if neither tomllib nor tomli is available
        return AIConfig()

    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)

        openai_section = data.get("openai", {})
        analysis_section = data.get("analysis", {})
        hevy_section = data.get("hevy", {})

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
            schedule=analysis_section.get("schedule", DEFAULT_SCHEDULE),
            user_context=analysis_section.get("user_context", ""),
            timezone=analysis_section.get("timezone", "America/New_York"),
            hevy=hevy_config,
        )
    except Exception:
        return AIConfig()


def save_config(config: AIConfig, path: Optional[Path] = None) -> None:
    """Save AI config to TOML file.

    Args:
        config: AIConfig instance to save
        path: Path to config file (defaults to ~/.config/garmin-sync/config.toml)
    """
    if path is None:
        path = DEFAULT_CONFIG_PATH

    # Ensure directory exists
    path.parent.mkdir(parents=True, exist_ok=True)

    data = {
        "openai": {
            "api_key": config.api_key or "",
            "model": config.model,
            "enabled": config.enabled,
            "use_tools": config.use_tools,
        },
        "analysis": {
            "schedule": config.schedule,
            "user_context": config.user_context,
            "timezone": config.timezone,
        },
        "hevy": {
            "api_key": config.hevy.api_key or "",
            "enabled": config.hevy.enabled,
            "sync_days": config.hevy.sync_days,
        },
    }

    with open(path, "wb") as f:
        tomli_w.dump(data, f)

    try:
        path.chmod(0o600)
        path.parent.chmod(0o700)
    except OSError as e:
        print(f"Warning: could not tighten permissions on {path}: {e}", file=sys.stderr)
