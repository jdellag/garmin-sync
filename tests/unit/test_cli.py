"""Tests for CLI commands."""

from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from garmin_sync.cli import app


runner = CliRunner()


class TestMainCLI:
    """Test main CLI commands."""

    def test_version(self):
        """Test --version flag."""
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert "garmin-sync version" in result.output
        assert "0.1.0" in result.output

    def test_help(self):
        """Test --help flag."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "Garmin Connect data sync and analysis tool" in result.output
        assert "auth" in result.output
        assert "sync" in result.output
        assert "report" in result.output
        assert "stats" in result.output

    def test_auth_help(self):
        """Test auth subcommand help."""
        result = runner.invoke(app, ["auth", "--help"])
        assert result.exit_code == 0
        assert "login" in result.output
        assert "status" in result.output
        assert "logout" in result.output

    def test_sync_help(self):
        """Test sync subcommand help."""
        result = runner.invoke(app, ["sync", "--help"])
        assert result.exit_code == 0
        assert "all" in result.output
        assert "activities" in result.output
        assert "health" in result.output

    def test_report_help(self):
        """Test report subcommand help."""
        result = runner.invoke(app, ["report", "--help"])
        assert result.exit_code == 0
        assert "weekly" in result.output
        assert "monthly" in result.output


class TestAuthCommands:
    """Test auth CLI commands."""

    @patch("garmin_sync.cli.get_auth_manager")
    @patch("garmin_sync.cli.get_settings")
    def test_auth_status_not_authenticated(self, mock_settings, mock_get_auth):
        """Test auth status when not authenticated."""
        mock_auth = MagicMock()
        mock_auth.get_status.return_value = {
            "authenticated": False,
            "has_tokens": False,
            "token_dir": "/home/user/.garminconnect",
        }
        mock_get_auth.return_value = mock_auth

        result = runner.invoke(app, ["auth", "status"])

        assert result.exit_code == 0
        assert "No" in result.output  # Not authenticated
        assert "garmin-sync auth login" in result.output

    @patch("garmin_sync.cli.get_auth_manager")
    @patch("garmin_sync.cli.get_settings")
    def test_auth_status_authenticated(self, mock_settings, mock_get_auth):
        """Test auth status when authenticated."""
        mock_auth = MagicMock()
        mock_auth.get_status.return_value = {
            "authenticated": True,
            "has_tokens": True,
            "token_dir": "/home/user/.garminconnect",
        }
        mock_get_auth.return_value = mock_auth

        result = runner.invoke(app, ["auth", "status"])

        assert result.exit_code == 0
        # Should show authenticated status without login prompt

    @patch("garmin_sync.cli.get_auth_manager")
    @patch("garmin_sync.cli.get_settings")
    def test_auth_logout_no_tokens(self, mock_settings, mock_get_auth):
        """Test logout when no tokens exist."""
        mock_auth = MagicMock()
        mock_auth.has_tokens.return_value = False
        mock_get_auth.return_value = mock_auth

        result = runner.invoke(app, ["auth", "logout"])

        assert result.exit_code == 0
        assert "No tokens to remove" in result.output

    @patch("garmin_sync.cli.get_auth_manager")
    @patch("garmin_sync.cli.get_settings")
    def test_auth_logout_with_force(self, mock_settings, mock_get_auth):
        """Test logout with --force flag."""
        mock_auth = MagicMock()
        mock_auth.has_tokens.return_value = True
        mock_get_auth.return_value = mock_auth

        result = runner.invoke(app, ["auth", "logout", "--force"])

        assert result.exit_code == 0
        assert "Successfully logged out" in result.output
        mock_auth.logout.assert_called_once()

    @patch("garmin_sync.cli.get_auth_manager")
    @patch("garmin_sync.cli.get_settings")
    def test_auth_logout_cancelled(self, mock_settings, mock_get_auth):
        """Test logout cancelled by user."""
        mock_auth = MagicMock()
        mock_auth.has_tokens.return_value = True
        mock_get_auth.return_value = mock_auth

        result = runner.invoke(app, ["auth", "logout"], input="n\n")

        assert result.exit_code == 0
        assert "Cancelled" in result.output
        mock_auth.logout.assert_not_called()

    @patch("garmin_sync.cli.Prompt")
    @patch("garmin_sync.cli.get_auth_manager")
    @patch("garmin_sync.cli.get_settings")
    def test_auth_login_success(self, mock_settings, mock_get_auth, mock_prompt):
        """Test successful login."""
        mock_auth = MagicMock()
        mock_get_auth.return_value = mock_auth
        mock_prompt.ask.side_effect = ["test@example.com", "password123"]

        result = runner.invoke(app, ["auth", "login"])

        assert result.exit_code == 0
        assert "Successfully logged in" in result.output
        mock_auth.login.assert_called_once()

    @patch("garmin_sync.cli.Prompt")
    @patch("garmin_sync.cli.get_auth_manager")
    @patch("garmin_sync.cli.get_settings")
    def test_auth_login_with_email_option(self, mock_settings, mock_get_auth, mock_prompt):
        """Test login with --email option."""
        mock_auth = MagicMock()
        mock_get_auth.return_value = mock_auth
        mock_prompt.ask.return_value = "password123"

        result = runner.invoke(app, ["auth", "login", "--email", "test@example.com"])

        assert result.exit_code == 0
        # Email should not be prompted since it was provided
        # Only password should be prompted
        mock_auth.login.assert_called_once_with("test@example.com", "password123")

    @patch("garmin_sync.cli.Prompt")
    @patch("garmin_sync.cli.get_auth_manager")
    @patch("garmin_sync.cli.get_settings")
    def test_auth_login_failure(self, mock_settings, mock_get_auth, mock_prompt):
        """Test failed login."""
        from garmin_sync.auth.garmin_auth import AuthenticationError

        mock_auth = MagicMock()
        mock_auth.login.side_effect = AuthenticationError("Invalid credentials")
        mock_get_auth.return_value = mock_auth
        mock_prompt.ask.side_effect = ["test@example.com", "wrongpassword"]

        result = runner.invoke(app, ["auth", "login"])

        assert result.exit_code == 1
        assert "Login failed" in result.output


class TestSyncCommands:
    """Test sync CLI commands."""

    @patch("garmin_sync.cli.get_auth_manager")
    @patch("garmin_sync.cli.get_settings")
    def test_sync_all_not_authenticated(self, mock_settings, mock_get_auth):
        """Test sync all when not authenticated."""
        mock_auth = MagicMock()
        mock_auth.has_tokens.return_value = False
        mock_get_auth.return_value = mock_auth

        result = runner.invoke(app, ["sync", "all"])

        assert result.exit_code == 1
        assert "Not authenticated" in result.output

    @patch("garmin_sync.cli._get_sync_manager")
    @patch("garmin_sync.cli.get_auth_manager")
    @patch("garmin_sync.cli.get_settings")
    def test_sync_all_success(self, mock_settings, mock_get_auth, mock_get_sync):
        """Test sync all with successful sync."""
        from garmin_sync.sync.sync_manager import SyncResult

        mock_auth = MagicMock()
        mock_auth.has_tokens.return_value = True
        mock_get_auth.return_value = mock_auth

        mock_sync = MagicMock()
        mock_result = SyncResult("activities")
        mock_result.records_synced = 5
        mock_sync.sync_all.return_value = {"activities": mock_result}
        mock_get_sync.return_value = mock_sync

        result = runner.invoke(app, ["sync", "all", "--days", "7"])

        assert result.exit_code == 0
        mock_sync.sync_all.assert_called_once()

    @patch("garmin_sync.cli.get_auth_manager")
    @patch("garmin_sync.cli.get_settings")
    def test_sync_activities_not_authenticated(self, mock_settings, mock_get_auth):
        """Test sync activities when not authenticated."""
        mock_auth = MagicMock()
        mock_auth.has_tokens.return_value = False
        mock_get_auth.return_value = mock_auth

        result = runner.invoke(app, ["sync", "activities"])

        assert result.exit_code == 1
        assert "Not authenticated" in result.output

    @patch("garmin_sync.cli.get_auth_manager")
    @patch("garmin_sync.cli.get_settings")
    def test_sync_health_not_authenticated(self, mock_settings, mock_get_auth):
        """Test sync health when not authenticated."""
        mock_auth = MagicMock()
        mock_auth.has_tokens.return_value = False
        mock_get_auth.return_value = mock_auth

        result = runner.invoke(app, ["sync", "health"])

        assert result.exit_code == 1
        assert "Not authenticated" in result.output

    @patch("garmin_sync.cli._get_sync_manager")
    @patch("garmin_sync.cli.get_auth_manager")
    @patch("garmin_sync.cli.get_settings")
    def test_sync_activities_exits_nonzero_on_failure(self, mock_settings, mock_get_auth, mock_get_sync):
        """A failed activities sync must exit non-zero so scheduled runs notice."""
        from garmin_sync.sync.sync_manager import SyncResult

        mock_auth = MagicMock()
        mock_auth.has_tokens.return_value = True
        mock_get_auth.return_value = mock_auth

        bad = SyncResult("activities")
        bad.add_error("Garmin 500")
        mock_sync = MagicMock()
        mock_sync.sync_activities.return_value = bad
        mock_get_sync.return_value = mock_sync

        result = runner.invoke(app, ["sync", "activities", "--days", "7"])
        assert result.exit_code == 1

    @patch("garmin_sync.cli._get_sync_manager")
    @patch("garmin_sync.cli.get_auth_manager")
    @patch("garmin_sync.cli.get_settings")
    def test_sync_activities_clean_error_on_exception(self, mock_settings, mock_get_auth, mock_get_sync):
        """A non-auth exception is reported cleanly (no traceback), exit 1."""
        mock_auth = MagicMock()
        mock_auth.has_tokens.return_value = True
        mock_get_auth.return_value = mock_auth

        mock_sync = MagicMock()
        mock_sync.sync_activities.side_effect = RuntimeError("Garmin API 500")
        mock_get_sync.return_value = mock_sync

        result = runner.invoke(app, ["sync", "activities", "--days", "7"])
        assert result.exit_code == 1
        assert "Sync failed" in result.output
        # The RuntimeError was caught, not leaked as an uncaught traceback.
        assert not isinstance(result.exception, RuntimeError)

    @patch("garmin_sync.cli._get_sync_manager")
    @patch("garmin_sync.cli.get_auth_manager")
    @patch("garmin_sync.cli.get_settings")
    def test_sync_health_exits_nonzero_on_failure(self, mock_settings, mock_get_auth, mock_get_sync):
        """A failed health-metric sync must exit non-zero."""
        from garmin_sync.sync.sync_manager import SyncResult

        mock_auth = MagicMock()
        mock_auth.has_tokens.return_value = True
        mock_get_auth.return_value = mock_auth

        ok = SyncResult("ok")
        bad = SyncResult("sleep")
        bad.add_error("boom")
        mock_sync = MagicMock()
        for name in ("sync_daily_summaries", "sync_heart_rate", "sync_stress",
                     "sync_hrv", "sync_body_battery", "sync_respiration", "sync_spo2"):
            getattr(mock_sync, name).return_value = ok
        mock_sync.sync_sleep.return_value = bad
        mock_get_sync.return_value = mock_sync

        result = runner.invoke(app, ["sync", "health", "--days", "7"])
        assert result.exit_code == 1

    @patch("garmin_sync.cli._get_sync_manager")
    @patch("garmin_sync.cli.get_auth_manager")
    @patch("garmin_sync.cli.get_settings")
    def test_sync_all_exits_nonzero_on_partial_failure(self, mock_settings, mock_get_auth, mock_get_sync):
        """sync all must exit non-zero if any Garmin data type failed."""
        from garmin_sync.sync.sync_manager import SyncResult

        mock_auth = MagicMock()
        mock_auth.has_tokens.return_value = True
        mock_get_auth.return_value = mock_auth

        ok = SyncResult("activities")
        bad = SyncResult("sleep")
        bad.add_error("boom")
        mock_sync = MagicMock()
        mock_sync.sync_all.return_value = {"activities": ok, "sleep": bad}
        mock_get_sync.return_value = mock_sync

        result = runner.invoke(app, ["sync", "all", "--days", "7"])
        assert result.exit_code == 1


class TestReportCommands:
    """Test report CLI commands."""

    @patch("garmin_sync.cli._get_report_generator")
    def test_report_weekly(self, mock_get_generator):
        """Test weekly report command."""
        mock_generator = MagicMock()
        mock_generator.generate_weekly_report.return_value = "# Weekly Report\nTest content"
        mock_get_generator.return_value = mock_generator

        result = runner.invoke(app, ["report", "weekly"])

        assert result.exit_code == 0
        assert "Weekly Report" in result.output
        mock_generator.generate_weekly_report.assert_called_once()

    @patch("garmin_sync.cli._get_report_generator")
    def test_report_weekly_llm(self, mock_get_generator):
        """Test weekly report with --llm flag."""
        mock_generator = MagicMock()
        mock_generator.generate_weekly_report.return_value = "# Report"
        mock_get_generator.return_value = mock_generator

        result = runner.invoke(app, ["report", "weekly", "--llm"])

        assert result.exit_code == 0
        mock_generator.generate_weekly_report.assert_called_once_with(llm_mode=True, format="markdown")

    @patch("garmin_sync.cli._get_report_generator")
    def test_report_monthly(self, mock_get_generator):
        """Test monthly report command."""
        mock_generator = MagicMock()
        mock_generator.generate_monthly_report.return_value = "# Monthly Report"
        mock_get_generator.return_value = mock_generator

        result = runner.invoke(app, ["report", "monthly"])

        assert result.exit_code == 0
        mock_generator.generate_monthly_report.assert_called_once()

    @patch("garmin_sync.cli._get_report_generator")
    def test_report_weekly_json_format(self, mock_get_generator):
        """Test weekly report with --format json outputs valid JSON."""
        mock_generator = MagicMock()
        mock_generator.generate_weekly_report.return_value = {
            "meta": {"report_type": "weekly"},
            "summary": {"activities": 5},
        }
        mock_get_generator.return_value = mock_generator

        result = runner.invoke(app, ["report", "weekly", "--format", "json"])

        assert result.exit_code == 0
        mock_generator.generate_weekly_report.assert_called_once_with(llm_mode=False, format="json")
        # Verify output is valid JSON
        import json
        parsed = json.loads(result.output)
        assert parsed["meta"]["report_type"] == "weekly"

    @patch("garmin_sync.cli._get_report_generator")
    def test_report_monthly_json_format(self, mock_get_generator):
        """Test monthly report with --format json outputs valid JSON."""
        mock_generator = MagicMock()
        mock_generator.generate_monthly_report.return_value = {
            "meta": {"report_type": "monthly"},
            "summary": {"activities": 10},
        }
        mock_get_generator.return_value = mock_generator

        result = runner.invoke(app, ["report", "monthly", "--format", "json", "--year", "2024", "--month", "1"])

        assert result.exit_code == 0
        mock_generator.generate_monthly_report.assert_called_once_with(
            year=2024, month=1, llm_mode=False, format="json"
        )
        import json
        parsed = json.loads(result.output)
        assert parsed["meta"]["report_type"] == "monthly"

    @patch("garmin_sync.cli._get_report_generator")
    def test_report_weekly_json_with_llm_flag(self, mock_get_generator):
        """Test that --format json with --llm flag works (llm flag is passed but JSON always includes full data)."""
        mock_generator = MagicMock()
        mock_generator.generate_weekly_report.return_value = {
            "meta": {"report_type": "weekly"},
            "recovery": {"hrv": {"baseline_7d": 65}},
        }
        mock_get_generator.return_value = mock_generator

        result = runner.invoke(app, ["report", "weekly", "--format", "json", "--llm"])

        assert result.exit_code == 0
        # Both format=json and llm_mode=True should be passed
        mock_generator.generate_weekly_report.assert_called_once_with(llm_mode=True, format="json")


class TestExportCommands:
    """Test export CLI commands."""

    @patch("garmin_sync.cli._get_report_generator")
    @patch("garmin_sync.cli.get_settings")
    def test_export_activities_json(self, mock_settings, mock_get_generator):
        """Test exporting activities to JSON."""
        mock_generator = MagicMock()
        mock_generator.export_activities_json.return_value = 5
        mock_get_generator.return_value = mock_generator

        result = runner.invoke(app, ["export", "activities", "-o", "/tmp/test.json"])

        assert result.exit_code == 0
        assert "Exported 5 activities" in result.output

    @patch("garmin_sync.cli._get_report_generator")
    @patch("garmin_sync.cli.get_settings")
    def test_export_activities_csv(self, mock_settings, mock_get_generator):
        """Test exporting activities to CSV."""
        mock_generator = MagicMock()
        mock_generator.export_activities_csv.return_value = 3
        mock_get_generator.return_value = mock_generator

        result = runner.invoke(app, ["export", "activities", "-f", "csv", "-o", "/tmp/test.csv"])

        assert result.exit_code == 0
        assert "Exported 3 activities" in result.output


class TestStatsCommands:
    """Test stats CLI commands."""

    @patch("garmin_sync.cli._get_report_generator")
    def test_stats_today(self, mock_get_generator):
        """Test today stats command."""
        mock_generator = MagicMock()
        mock_generator.generate_today_stats.return_value = "# Today\nSteps: 5000"
        mock_get_generator.return_value = mock_generator

        result = runner.invoke(app, ["stats", "today"])

        assert result.exit_code == 0
        assert "Steps" in result.output

    @patch("garmin_sync.cli._get_report_generator")
    def test_stats_week(self, mock_get_generator):
        """Test week stats command."""
        mock_generator = MagicMock()
        mock_generator.generate_week_stats.return_value = "# Weekly Summary"
        mock_get_generator.return_value = mock_generator

        result = runner.invoke(app, ["stats", "week"])

        assert result.exit_code == 0
        assert "Weekly Summary" in result.output
