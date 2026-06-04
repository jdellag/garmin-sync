"""Tests for configuration management."""

import os
from pathlib import Path

import pytest

from garmin_sync.config.settings import Settings


class TestSettings:
    """Test Settings class."""

    def test_default_values(self):
        """Test that default values are set correctly."""
        settings = Settings()

        assert settings.default_sync_days == 30
        assert settings.download_fit_files is True
        assert settings.api_timeout_seconds == 30
        assert settings.rate_limit_calls_per_minute == 15
        assert settings.default_report_format == "markdown"
        assert settings.llm_mode_default is False
        assert settings.database_name == "garmin.db"

    def test_default_paths(self):
        """Test that default paths match the platform-aware helpers."""
        from garmin_sync.config.paths import default_data_dir, default_token_dir

        settings = Settings()

        assert settings.data_dir == default_data_dir()
        assert settings.token_dir == default_token_dir()

    def test_computed_paths(self):
        """Test computed path properties."""
        settings = Settings()

        assert settings.database_path == settings.data_dir / "garmin.db"
        assert settings.fit_files_dir == settings.data_dir / "fit_files"
        assert settings.exports_dir == settings.data_dir / "exports"

    def test_custom_data_dir(self, temp_dir):
        """Test custom data directory."""
        settings = Settings(data_dir=temp_dir)

        assert settings.data_dir == temp_dir
        assert settings.database_path == temp_dir / "garmin.db"
        assert settings.fit_files_dir == temp_dir / "fit_files"

    def test_env_var_override(self, monkeypatch):
        """Test that environment variables override defaults."""
        monkeypatch.setenv("GARMIN_SYNC_DEFAULT_SYNC_DAYS", "90")
        monkeypatch.setenv("GARMIN_SYNC_DOWNLOAD_FIT_FILES", "false")
        monkeypatch.setenv("GARMIN_SYNC_API_TIMEOUT_SECONDS", "60")

        settings = Settings()

        assert settings.default_sync_days == 90
        assert settings.download_fit_files is False
        assert settings.api_timeout_seconds == 60

    def test_env_var_path_override(self, temp_dir, monkeypatch):
        """Test that path environment variables work correctly."""
        monkeypatch.setenv("GARMIN_SYNC_DATA_DIR", str(temp_dir))

        settings = Settings()

        assert settings.data_dir == temp_dir

    def test_config_dir_override_and_config_paths(self, temp_dir, monkeypatch):
        """config.toml/profile.toml follow config_dir, which is independently
        overridable (so relocating data_dir doesn't orphan config)."""
        monkeypatch.setenv("GARMIN_SYNC_DATA_DIR", str(temp_dir / "data"))
        monkeypatch.setenv("GARMIN_SYNC_CONFIG_DIR", str(temp_dir / "cfg"))

        settings = Settings()

        assert settings.config_dir == temp_dir / "cfg"
        assert settings.ai_config_path == temp_dir / "cfg" / "config.toml"
        assert settings.profile_path == temp_dir / "cfg" / "profile.toml"

    def test_path_env_vars_expand_user(self, monkeypatch):
        """A ~ in a path env var expands to $HOME, not a literal './~' dir."""
        monkeypatch.setenv("GARMIN_SYNC_DATA_DIR", "~/gs_data_test")
        monkeypatch.setenv("GARMIN_SYNC_CONFIG_DIR", "~/gs_cfg_test")

        settings = Settings()

        assert settings.data_dir == Path.home() / "gs_data_test"
        assert settings.config_dir == Path.home() / "gs_cfg_test"
        assert "~" not in str(settings.data_dir)

    def test_ensure_directories(self, temp_dir):
        """Test that ensure_directories creates required directories."""
        settings = Settings(
            data_dir=temp_dir / "data",
            token_dir=temp_dir / "tokens",
        )

        # Directories should not exist yet
        assert not settings.data_dir.exists()
        assert not settings.token_dir.exists()

        settings.ensure_directories()

        # Now they should exist
        assert settings.data_dir.exists()
        assert settings.fit_files_dir.exists()
        assert settings.exports_dir.exists()
        assert settings.token_dir.exists()

    def test_sync_days_validation(self):
        """Test that sync_days is validated."""
        # Valid values should work
        settings = Settings(default_sync_days=1)
        assert settings.default_sync_days == 1

        settings = Settings(default_sync_days=365)
        assert settings.default_sync_days == 365

        # Invalid values should raise
        with pytest.raises(ValueError):
            Settings(default_sync_days=0)

        with pytest.raises(ValueError):
            Settings(default_sync_days=366)

    def test_report_format_validation(self):
        """Test that report format is validated."""
        # Valid formats
        for fmt in ["markdown", "text", "json"]:
            settings = Settings(default_report_format=fmt)
            assert settings.default_report_format == fmt

        # Invalid format should raise
        with pytest.raises(ValueError):
            Settings(default_report_format="invalid")

    def test_custom_database_name(self, temp_dir):
        """Test custom database name."""
        settings = Settings(
            data_dir=temp_dir,
            database_name="custom.db",
        )

        assert settings.database_path == temp_dir / "custom.db"
