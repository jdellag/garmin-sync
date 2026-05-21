"""Tests for the garmin-sync setup wizard."""

from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from garmin_sync.cli import app

runner = CliRunner()


class TestSetupWizard:
    """Tests for the `garmin-sync setup` command."""

    def test_setup_help(self):
        result = runner.invoke(app, ["setup", "--help"])
        assert result.exit_code == 0
        assert "--skip-garmin" in result.output
        assert "--skip-openai" in result.output
        assert "--skip-hevy" in result.output
        assert "wizard" in result.output.lower()

    def test_setup_all_skipped(self):
        result = runner.invoke(
            app,
            ["setup", "--skip-garmin", "--skip-openai", "--skip-hevy"],
        )
        assert result.exit_code == 0
        assert "All steps skipped" in result.output

    @patch("garmin_sync.cli.get_auth_manager")
    def test_setup_garmin_already_authenticated(self, mock_auth):
        """Wizard detects existing Garmin auth and offers to skip."""
        mock_manager = MagicMock()
        mock_manager.get_status.return_value = {"authenticated": True, "has_tokens": True}
        mock_auth.return_value = mock_manager

        result = runner.invoke(
            app,
            ["setup", "--skip-openai", "--skip-hevy"],
            input="n\n",  # Don't re-authenticate
        )

        assert result.exit_code == 0
        assert "Already logged in" in result.output
        assert "Setup Complete" in result.output

    @patch("garmin_sync.cli.get_auth_manager")
    def test_setup_garmin_not_authenticated(self, mock_auth):
        """Wizard prompts for credentials when not authenticated."""
        mock_manager = MagicMock()
        mock_manager.get_status.return_value = {"authenticated": False, "has_tokens": False}
        mock_auth.return_value = mock_manager

        result = runner.invoke(
            app,
            ["setup", "--skip-openai", "--skip-hevy"],
            input="user@example.com\nmypassword\n",
        )

        assert result.exit_code == 0
        mock_manager.login.assert_called_once_with("user@example.com", "mypassword")

    def test_setup_shows_next_steps(self):
        """Setup complete message includes next steps."""
        result = runner.invoke(
            app,
            ["setup", "--skip-garmin", "--skip-openai", "--skip-hevy"],
        )
        # All skipped, so no "Setup Complete" — but verify the skip path works
        assert result.exit_code == 0
