"""Application settings using Pydantic."""

from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from garmin_sync.config.paths import (
    default_config_dir,
    default_data_dir,
    default_token_dir,
)


class Settings(BaseSettings):
    """Application settings with environment variable support.

    Settings are loaded from (in order of priority):
    1. Environment variables (prefixed with GARMIN_SYNC_)
    2. .env file
    3. Default values
    """

    model_config = SettingsConfigDict(
        env_prefix="GARMIN_SYNC_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Paths
    data_dir: Path = Field(
        default_factory=default_data_dir,
        description="Directory for storing data files",
    )
    token_dir: Path = Field(
        default_factory=default_token_dir,
        description="Directory for Garmin OAuth tokens",
        # Accepts GARMIN_SYNC_TOKEN_DIR (primary), the constructor kwarg
        # `token_dir`, and the legacy env var GARMIN_SYNC_GARTH_TOKEN_DIR.
        validation_alias=AliasChoices(
            "token_dir",
            "GARMIN_SYNC_TOKEN_DIR",
            "GARMIN_SYNC_GARTH_TOKEN_DIR",
        ),
    )
    config_dir: Path = Field(
        default_factory=default_config_dir,
        description="Directory for config.toml and profile.toml "
                    "(override with GARMIN_SYNC_CONFIG_DIR)",
    )

    @field_validator("data_dir", "token_dir", "config_dir", mode="after")
    @classmethod
    def _expand_user_paths(cls, v: Path) -> Path:
        """Expand ~ so e.g. GARMIN_SYNC_DATA_DIR=~/foo resolves to $HOME/foo
        instead of a literal './~/foo' under the current directory."""
        return v.expanduser()

    # Database
    database_name: str = Field(
        default="garmin.db",
        description="SQLite database filename",
    )

    # Sync settings
    default_sync_days: int = Field(
        default=30,
        ge=1,
        le=365,
        description="Default number of days to sync",
    )
    download_fit_files: bool = Field(
        default=True,
        description="Whether to download FIT files for activities",
    )

    # API settings
    api_timeout_seconds: int = Field(
        default=30,
        ge=5,
        le=120,
        description="API request timeout in seconds",
    )
    rate_limit_calls_per_minute: int = Field(
        default=15,
        ge=1,
        le=60,
        description="Maximum API calls per minute",
    )

    # Report settings
    default_report_format: str = Field(
        default="markdown",
        pattern="^(markdown|text|json)$",
        description="Default report output format",
    )
    llm_mode_default: bool = Field(
        default=False,
        description="Enable LLM-optimized output by default",
    )

    @property
    def database_path(self) -> Path:
        """Full path to the SQLite database."""
        return self.data_dir / self.database_name

    @property
    def fit_files_dir(self) -> Path:
        """Directory for storing FIT files."""
        return self.data_dir / "fit_files"

    @property
    def exports_dir(self) -> Path:
        """Directory for export files."""
        return self.data_dir / "exports"

    @property
    def logs_dir(self) -> Path:
        """Directory for log files."""
        return self.data_dir / "logs"

    @property
    def reports_dir(self) -> Path:
        """Directory for AI analysis reports."""
        return self.data_dir / "reports"

    @property
    def ai_config_path(self) -> Path:
        """Path to AI configuration file (secrets + technical settings)."""
        return self.config_dir / "config.toml"

    @property
    def profile_path(self) -> Path:
        """Path to training profile file (schedule, goals, timezone)."""
        return self.config_dir / "profile.toml"

    def ensure_directories(self) -> None:
        """Create all required directories if they don't exist."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.fit_files_dir.mkdir(parents=True, exist_ok=True)
        self.exports_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.token_dir.mkdir(parents=True, exist_ok=True)
        # The token dir holds OAuth credentials — keep it owner-only, not at
        # the process umask (login() also tightens it, but this covers the
        # window before the first login).
        try:
            self.token_dir.chmod(0o700)
        except OSError:
            pass  # e.g. Windows


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
