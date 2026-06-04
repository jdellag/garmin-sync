"""Tests for platform-aware path defaults."""

from pathlib import Path
from unittest.mock import patch

import pytest

from garmin_sync.config import paths


class TestDefaultDataDir:
    """Test default_data_dir()."""

    def test_returns_path_object(self):
        """Result is a Path."""
        result = paths.default_data_dir()
        assert isinstance(result, Path)

    def test_contains_garmin_sync(self):
        """Path ends with 'garmin-sync'."""
        result = paths.default_data_dir()
        assert "garmin-sync" in str(result)

    @patch("garmin_sync.config.paths.sys")
    def test_macos_uses_xdg(self, mock_sys):
        """macOS preserves the existing ~/.local/share layout."""
        mock_sys.platform = "darwin"

        result = paths.default_data_dir()

        assert result == Path.home() / ".local" / "share" / "garmin-sync"

    @patch("garmin_sync.config.paths.sys")
    @patch("garmin_sync.config.paths.user_data_dir")
    def test_windows_uses_platformdirs(self, mock_user_data, mock_sys):
        """Windows delegates to platformdirs (returns AppData path)."""
        mock_sys.platform = "win32"
        mock_user_data.return_value = r"C:\Users\testuser\AppData\Local\garmin-sync"

        result = paths.default_data_dir()

        mock_user_data.assert_called_once_with("garmin-sync", appauthor=False, ensure_exists=False)
        assert "AppData" in str(result)
        assert "garmin-sync" in str(result)

    @patch("garmin_sync.config.paths.sys")
    @patch("garmin_sync.config.paths.user_data_dir")
    def test_linux_uses_platformdirs(self, mock_user_data, mock_sys):
        """Linux delegates to platformdirs (returns XDG path)."""
        mock_sys.platform = "linux"
        mock_user_data.return_value = "/home/testuser/.local/share/garmin-sync"

        result = paths.default_data_dir()

        mock_user_data.assert_called_once_with("garmin-sync", appauthor=False, ensure_exists=False)
        assert result == Path("/home/testuser/.local/share/garmin-sync")


class TestDefaultConfigDir:
    """Test default_config_dir()."""

    def test_returns_path_object(self):
        """Result is a Path."""
        result = paths.default_config_dir()
        assert isinstance(result, Path)

    @patch("garmin_sync.config.paths.sys")
    def test_macos_uses_xdg(self, mock_sys):
        """macOS preserves the existing ~/.config layout."""
        mock_sys.platform = "darwin"

        result = paths.default_config_dir()

        assert result == Path.home() / ".config" / "garmin-sync"

    @patch("garmin_sync.config.paths.sys")
    @patch("garmin_sync.config.paths.user_config_dir")
    def test_windows_uses_platformdirs(self, mock_user_config, mock_sys):
        """Windows delegates to platformdirs."""
        mock_sys.platform = "win32"
        mock_user_config.return_value = r"C:\Users\testuser\AppData\Local\garmin-sync"

        result = paths.default_config_dir()

        mock_user_config.assert_called_once_with("garmin-sync", appauthor=False, ensure_exists=False)
        assert "AppData" in str(result)


class TestDefaultConfigPath:
    """Test default_config_path()."""

    def test_ends_with_config_toml(self):
        """Path ends with config.toml."""
        result = paths.default_config_path()
        assert result.name == "config.toml"

    @patch("garmin_sync.config.paths.sys")
    def test_macos_full_path(self, mock_sys):
        """macOS config path is under ~/.config."""
        mock_sys.platform = "darwin"

        result = paths.default_config_path()

        assert result == Path.home() / ".config" / "garmin-sync" / "config.toml"


class TestDefaultGarthTokenDir:
    """Test default_token_dir()."""

    def test_always_returns_home_garminconnect(self):
        """Garth token dir is always ~/.garminconnect regardless of platform."""
        result = paths.default_token_dir()
        assert result == Path.home() / ".garminconnect"
        assert result.name == ".garminconnect"

    @patch("garmin_sync.config.paths.sys")
    def test_same_on_windows(self, mock_sys):
        """Garth token dir is the same even on Windows (garth convention)."""
        mock_sys.platform = "win32"

        result = paths.default_token_dir()

        assert result == Path.home() / ".garminconnect"
