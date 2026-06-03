"""Tests for scheduler module."""

import plistlib
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from garmin_sync.cli import app
from garmin_sync.scheduler import launchd


runner = CliRunner()


class TestLaunchdModule:
    """Test launchd scheduler functions."""

    def test_get_plist_path(self):
        """Test plist path generation."""
        path = launchd.get_plist_path()
        assert path.name == "com.garmin-sync.daily.plist"
        assert "Library/LaunchAgents" in str(path)

    def test_generate_plist_default_hours(self, tmp_path):
        """Test plist generation with default hours."""
        log_dir = tmp_path / "logs"
        plist = launchd.generate_plist("/usr/local/bin/garmin-sync", log_dir)

        assert plist["Label"] == "com.garmin-sync.daily"
        # Uses bash -c to chain sync, analyze, notify, and open report
        assert plist["ProgramArguments"][0] == "/bin/bash"
        assert plist["ProgramArguments"][1] == "-c"
        command = plist["ProgramArguments"][2]
        assert "sync all --days 1 --detailed" in command
        assert "analyze" in command
        assert "post-sync-check" in command  # notification via anomaly check
        assert "open" in command  # open report
        assert plist["RunAtLoad"] is False
        assert plist["StandardOutPath"] == str(log_dir / "sync.log")
        assert plist["StandardErrorPath"] == str(log_dir / "sync-error.log")

        # Check schedule intervals
        intervals = plist["StartCalendarInterval"]
        assert len(intervals) == 7  # 5 weekdays + 2 weekend days

        # Check weekdays (Mon-Fri at 8:30)
        weekday_intervals = [i for i in intervals if i.get("Weekday") in [1, 2, 3, 4, 5]]
        assert len(weekday_intervals) == 5
        for interval in weekday_intervals:
            assert interval["Hour"] == 8
            assert interval["Minute"] == 30

        # Check weekends (Sat=6, Sun=0 at 10:00)
        weekend_intervals = [i for i in intervals if i.get("Weekday") in [0, 6]]
        assert len(weekend_intervals) == 2
        for interval in weekend_intervals:
            assert interval["Hour"] == 10
            assert interval["Minute"] == 0

    def test_generate_plist_custom_hours(self, tmp_path):
        """Test plist generation with custom hours."""
        log_dir = tmp_path / "logs"
        plist = launchd.generate_plist(
            "/usr/local/bin/garmin-sync",
            log_dir,
            weekday_hour=6,
            weekend_hour=9,
        )

        intervals = plist["StartCalendarInterval"]

        # Check weekdays at 6:00
        weekday_intervals = [i for i in intervals if i.get("Weekday") in [1, 2, 3, 4, 5]]
        for interval in weekday_intervals:
            assert interval["Hour"] == 6

        # Check weekends at 9:00
        weekend_intervals = [i for i in intervals if i.get("Weekday") in [0, 6]]
        for interval in weekend_intervals:
            assert interval["Hour"] == 9

    @patch("garmin_sync.scheduler.launchd.subprocess.run")
    @patch("garmin_sync.scheduler.launchd.shutil.which")
    @patch("garmin_sync.scheduler.launchd.get_plist_path")
    def test_install_success(self, mock_plist_path, mock_which, mock_run, tmp_path):
        """Test successful installation."""
        plist_path = tmp_path / "Library" / "LaunchAgents" / "com.garmin-sync.daily.plist"
        mock_plist_path.return_value = plist_path
        mock_which.return_value = "/usr/local/bin/garmin-sync"
        mock_run.return_value = MagicMock(returncode=0, stderr="")

        log_dir = tmp_path / "logs"
        success, message = launchd.install(log_dir)

        assert success is True
        assert "Installed successfully" in message
        assert plist_path.exists()

        # Verify plist content
        with open(plist_path, "rb") as f:
            plist_data = plistlib.load(f)
        assert plist_data["Label"] == "com.garmin-sync.daily"

    @patch("garmin_sync.scheduler.launchd.shutil.which")
    def test_install_garmin_sync_not_found(self, mock_which, tmp_path):
        """Test installation fails when garmin-sync not in PATH."""
        mock_which.return_value = None

        log_dir = tmp_path / "logs"
        success, message = launchd.install(log_dir)

        assert success is False
        assert "not found in PATH" in message

    @patch("garmin_sync.scheduler.launchd.subprocess.run")
    @patch("garmin_sync.scheduler.launchd.shutil.which")
    @patch("garmin_sync.scheduler.launchd.get_plist_path")
    def test_install_launchctl_fails(self, mock_plist_path, mock_which, mock_run, tmp_path):
        """Test installation fails when launchctl load fails."""
        plist_path = tmp_path / "Library" / "LaunchAgents" / "com.garmin-sync.daily.plist"
        mock_plist_path.return_value = plist_path
        mock_which.return_value = "/usr/local/bin/garmin-sync"
        mock_run.return_value = MagicMock(returncode=1, stderr="Permission denied")

        log_dir = tmp_path / "logs"
        success, message = launchd.install(log_dir)

        assert success is False
        assert "Failed to load plist" in message

    @patch("garmin_sync.scheduler.launchd.subprocess.run", side_effect=FileNotFoundError())
    @patch("garmin_sync.scheduler.launchd.shutil.which")
    @patch("garmin_sync.scheduler.launchd.get_plist_path")
    def test_install_handles_missing_launchctl(self, mock_plist_path, mock_which, mock_run, tmp_path):
        """A missing launchctl binary yields a clean failure, not a traceback."""
        plist_path = tmp_path / "Library" / "LaunchAgents" / "com.garmin-sync.daily.plist"
        mock_plist_path.return_value = plist_path
        mock_which.return_value = "/usr/local/bin/garmin-sync"

        success, message = launchd.install(tmp_path / "logs")

        assert success is False
        assert "not found" in message.lower()

    @patch("garmin_sync.scheduler.launchd.subprocess.run")
    @patch("garmin_sync.scheduler.launchd.get_plist_path")
    def test_uninstall_success(self, mock_plist_path, mock_run, tmp_path):
        """Test successful uninstallation."""
        plist_path = tmp_path / "com.garmin-sync.daily.plist"
        plist_path.write_text("test")
        mock_plist_path.return_value = plist_path
        mock_run.return_value = MagicMock(returncode=0)

        success, message = launchd.uninstall()

        assert success is True
        assert "Uninstalled successfully" in message
        assert not plist_path.exists()

    @patch("garmin_sync.scheduler.launchd.get_plist_path")
    def test_uninstall_not_installed(self, mock_plist_path, tmp_path):
        """Test uninstall when not installed."""
        plist_path = tmp_path / "nonexistent.plist"
        mock_plist_path.return_value = plist_path

        success, message = launchd.uninstall()

        assert success is True
        assert "Not installed" in message

    @patch("garmin_sync.scheduler.launchd.get_plist_path")
    def test_get_status_not_installed(self, mock_plist_path, tmp_path):
        """Test status when not installed."""
        plist_path = tmp_path / "nonexistent.plist"
        mock_plist_path.return_value = plist_path

        status = launchd.get_status()

        assert status["installed"] is False
        assert status["loaded"] is False
        assert status["schedule"] is None

    @patch("garmin_sync.scheduler.launchd.subprocess.run")
    @patch("garmin_sync.scheduler.launchd.get_plist_path")
    def test_get_status_installed_and_loaded(self, mock_plist_path, mock_run, tmp_path):
        """Test status when installed and loaded."""
        plist_path = tmp_path / "com.garmin-sync.daily.plist"

        # Write a valid plist
        plist_data = launchd.generate_plist("/usr/local/bin/garmin-sync", tmp_path / "logs")
        with open(plist_path, "wb") as f:
            plistlib.dump(plist_data, f)

        mock_plist_path.return_value = plist_path
        mock_run.return_value = MagicMock(returncode=0)  # launchctl list succeeds

        status = launchd.get_status()

        assert status["installed"] is True
        assert status["loaded"] is True
        assert status["schedule"]["weekday_time"] == "8:30 AM"
        assert status["schedule"]["weekend_time"] == "10:00 AM"


class TestFormatHour:
    """Test the _format_hour helper for 12-hour display."""

    def test_midnight(self):
        assert launchd._format_hour(0) == "12:00 AM"

    def test_morning(self):
        assert launchd._format_hour(7) == "7:00 AM"

    def test_noon(self):
        assert launchd._format_hour(12) == "12:00 PM"

    def test_afternoon(self):
        assert launchd._format_hour(14) == "2:00 PM"

    def test_late_evening(self):
        assert launchd._format_hour(22) == "10:00 PM"


class TestGetLastSyncAge:
    """Test _get_last_sync_age log parsing."""

    def test_parses_date_with_3char_tz(self, tmp_path):
        """Standard 3-char timezone like EDT."""
        log = tmp_path / "sync.log"
        log.write_text("Mon May 26 07:00:00 EDT 2026: Starting daily sync...\n")
        result = launchd._get_last_sync_age(log)
        assert result is not None

    def test_parses_date_with_4char_tz(self, tmp_path):
        """4-char timezone like AEST should still parse."""
        log = tmp_path / "sync.log"
        log.write_text("Mon May 26 07:00:00 AEST 2026: Starting daily sync...\n")
        result = launchd._get_last_sync_age(log)
        assert result is not None

    def test_empty_log_returns_none(self, tmp_path):
        log = tmp_path / "sync.log"
        log.write_text("")
        assert launchd._get_last_sync_age(log) is None

    def test_missing_log_returns_none(self, tmp_path):
        log = tmp_path / "sync.log"
        assert launchd._get_last_sync_age(log) is None


class TestScheduleCLI:
    """Test schedule CLI commands."""

    def test_schedule_help(self):
        """Test schedule subcommand help."""
        result = runner.invoke(app, ["schedule", "--help"])
        assert result.exit_code == 0
        assert "install" in result.output
        assert "uninstall" in result.output
        assert "status" in result.output
        assert "logs" in result.output

    @patch("garmin_sync.scheduler.get_scheduler")
    def test_schedule_install_unsupported_os(self, mock_get_sched):
        """Test install shows crontab instructions on unsupported OS."""
        mock_get_sched.return_value = None

        result = runner.invoke(app, ["schedule", "install"])

        assert result.exit_code == 1
        assert "not supported" in result.output
        assert "crontab" in result.output

    @patch("garmin_sync.scheduler.get_scheduler")
    @patch("garmin_sync.cli.get_auth_manager")
    @patch("garmin_sync.cli.get_settings")
    def test_schedule_install_not_authenticated(self, mock_settings, mock_get_auth, mock_get_sched):
        """Test install fails when not authenticated."""
        mock_get_sched.return_value = MagicMock()  # any scheduler
        mock_auth = MagicMock()
        mock_auth.has_tokens.return_value = False
        mock_get_auth.return_value = mock_auth

        result = runner.invoke(app, ["schedule", "install"])

        assert result.exit_code == 1
        assert "Not authenticated" in result.output

    @patch("garmin_sync.scheduler.get_scheduler")
    @patch("garmin_sync.cli.get_auth_manager")
    @patch("garmin_sync.cli.get_settings")
    def test_schedule_install_success(self, mock_settings, mock_get_auth, mock_get_sched):
        """Test successful install."""
        mock_sched = MagicMock()
        mock_sched.install.return_value = (True, "Installed successfully.")
        mock_get_sched.return_value = mock_sched
        mock_auth = MagicMock()
        mock_auth.has_tokens.return_value = True
        mock_get_auth.return_value = mock_auth

        result = runner.invoke(app, ["schedule", "install"])

        assert result.exit_code == 0
        assert "Installed successfully" in result.output
        assert "8:30 AM" in result.output
        assert "10:00 AM" in result.output

    @patch("garmin_sync.scheduler.get_scheduler")
    @patch("garmin_sync.cli.get_auth_manager")
    @patch("garmin_sync.cli.get_settings")
    def test_schedule_install_failure(self, mock_settings, mock_get_auth, mock_get_sched):
        """Test install failure."""
        mock_sched = MagicMock()
        mock_sched.install.return_value = (False, "garmin-sync not found in PATH")
        mock_get_sched.return_value = mock_sched
        mock_auth = MagicMock()
        mock_auth.has_tokens.return_value = True
        mock_get_auth.return_value = mock_auth

        result = runner.invoke(app, ["schedule", "install"])

        assert result.exit_code == 1
        assert "garmin-sync not found" in result.output

    @patch("garmin_sync.scheduler.get_scheduler")
    def test_schedule_uninstall_unsupported_os(self, mock_get_sched):
        """Test uninstall on unsupported OS."""
        mock_get_sched.return_value = None

        result = runner.invoke(app, ["schedule", "uninstall"])

        assert result.exit_code == 0
        assert "crontab" in result.output.lower()

    @patch("garmin_sync.scheduler.get_scheduler")
    def test_schedule_uninstall_success(self, mock_get_sched):
        """Test successful uninstall."""
        mock_sched = MagicMock()
        mock_sched.uninstall.return_value = (True, "Uninstalled successfully")
        mock_get_sched.return_value = mock_sched

        result = runner.invoke(app, ["schedule", "uninstall"])

        assert result.exit_code == 0
        assert "Uninstalled successfully" in result.output

    @patch("garmin_sync.scheduler.get_scheduler")
    def test_schedule_status_unsupported_os(self, mock_get_sched):
        """Test status on unsupported OS."""
        mock_get_sched.return_value = None

        result = runner.invoke(app, ["schedule", "status"])

        assert result.exit_code == 0
        assert "not supported" in result.output

    @patch("garmin_sync.scheduler.get_scheduler")
    @patch("garmin_sync.cli.get_settings")
    def test_schedule_status_not_installed(self, mock_settings, mock_get_sched, tmp_path):
        """Test status when not installed."""
        mock_sched = MagicMock()
        mock_sched.get_status.return_value = {
            "installed": False,
            "plist_path": str(tmp_path / "plist"),
            "loaded": False,
            "schedule": None,
        }
        mock_get_sched.return_value = mock_sched
        mock_settings_instance = MagicMock()
        mock_settings_instance.logs_dir = tmp_path / "logs"
        mock_settings.return_value = mock_settings_instance

        result = runner.invoke(app, ["schedule", "status"])

        assert result.exit_code == 0
        assert "No" in result.output  # Not installed

    @patch("garmin_sync.scheduler.get_scheduler")
    @patch("garmin_sync.cli.get_settings")
    def test_schedule_status_installed(self, mock_settings, mock_get_sched, tmp_path):
        """Test status when installed."""
        mock_sched = MagicMock()
        mock_sched.get_status.return_value = {
            "installed": True,
            "plist_path": str(tmp_path / "plist"),
            "loaded": True,
            "schedule": {
                "weekday_time": "7:00 AM",
                "weekend_time": "10:00 AM",
            },
        }
        mock_get_sched.return_value = mock_sched
        mock_settings_instance = MagicMock()
        mock_settings_instance.logs_dir = tmp_path / "logs"
        mock_settings.return_value = mock_settings_instance

        result = runner.invoke(app, ["schedule", "status"])

        assert result.exit_code == 0
        assert "7:00 AM" in result.output
        assert "10:00 AM" in result.output

    @patch("garmin_sync.cli.get_settings")
    def test_schedule_logs_no_file(self, mock_settings, tmp_path):
        """Test logs when no log file exists."""
        mock_settings_instance = MagicMock()
        mock_settings_instance.logs_dir = tmp_path / "logs"
        mock_settings.return_value = mock_settings_instance

        result = runner.invoke(app, ["schedule", "logs"])

        assert result.exit_code == 0
        assert "No log file found" in result.output

    @patch("garmin_sync.cli.get_settings")
    def test_schedule_logs_with_file(self, mock_settings, tmp_path):
        """Test logs when log file exists."""
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir(parents=True)
        log_file = logs_dir / "sync.log"
        log_file.write_text("Line 1\nLine 2\nLine 3\n")

        mock_settings_instance = MagicMock()
        mock_settings_instance.logs_dir = logs_dir
        mock_settings.return_value = mock_settings_instance

        result = runner.invoke(app, ["schedule", "logs"])

        assert result.exit_code == 0
        assert "Line 1" in result.output
        assert "Line 2" in result.output
        assert "Line 3" in result.output

    @patch("garmin_sync.cli.get_settings")
    def test_schedule_logs_error_log(self, mock_settings, tmp_path):
        """Test viewing error logs."""
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir(parents=True)
        error_log = logs_dir / "sync-error.log"
        error_log.write_text("Error 1\nError 2\n")

        mock_settings_instance = MagicMock()
        mock_settings_instance.logs_dir = logs_dir
        mock_settings.return_value = mock_settings_instance

        result = runner.invoke(app, ["schedule", "logs", "--errors"])

        assert result.exit_code == 0
        assert "Error 1" in result.output
        assert "Error 2" in result.output

    @patch("garmin_sync.cli.get_settings")
    def test_schedule_logs_with_lines_option(self, mock_settings, tmp_path):
        """Test logs with custom line count."""
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir(parents=True)
        log_file = logs_dir / "sync.log"
        log_file.write_text("\n".join([f"Line {i}" for i in range(100)]))

        mock_settings_instance = MagicMock()
        mock_settings_instance.logs_dir = logs_dir
        mock_settings.return_value = mock_settings_instance

        result = runner.invoke(app, ["schedule", "logs", "--lines", "5"])

        assert result.exit_code == 0
        # Should only show last 5 lines
        assert "Line 99" in result.output
        assert "Line 95" in result.output
        assert "Line 50" not in result.output


class TestGetScheduler:
    """Test the scheduler factory function."""

    @patch("platform.system")
    def test_returns_launchd_on_darwin(self, mock_platform):
        """Factory returns launchd module on macOS."""
        mock_platform.return_value = "Darwin"
        from garmin_sync.scheduler import get_scheduler

        sched = get_scheduler()

        from garmin_sync.scheduler import launchd
        assert sched is launchd

    @patch("platform.system")
    def test_returns_windows_task_on_windows(self, mock_platform):
        """Factory returns windows_task module on Windows."""
        mock_platform.return_value = "Windows"
        from garmin_sync.scheduler import get_scheduler

        sched = get_scheduler()

        from garmin_sync.scheduler import windows_task
        assert sched is windows_task

    @patch("platform.system")
    def test_returns_none_on_linux(self, mock_platform):
        """Factory returns None on Linux (unsupported)."""
        mock_platform.return_value = "Linux"
        from garmin_sync.scheduler import get_scheduler

        assert get_scheduler() is None
