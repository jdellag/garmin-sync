"""Tests for Windows Task Scheduler module.

All tests mock subprocess.run so they can run on any platform.
"""

from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from garmin_sync.scheduler import windows_task


class TestWindowsTaskInstall:
    """Test windows_task.install()."""

    @patch("garmin_sync.scheduler.windows_task.subprocess.run")
    @patch("garmin_sync.scheduler.windows_task.shutil.which")
    def test_install_success(self, mock_which, mock_run, tmp_path):
        """Install creates two scheduled tasks and a batch wrapper."""
        mock_which.return_value = r"C:\Python\Scripts\garmin-sync.exe"
        mock_run.return_value = MagicMock(returncode=0, stderr="")

        log_dir = tmp_path / "logs"
        success, message = windows_task.install(log_dir)

        assert success is True
        assert "Installed successfully" in message
        assert "GarminSync-Weekday" in message
        assert "GarminSync-Weekend" in message

        # Batch wrapper written
        bat = log_dir / "garmin-sync-daily.bat"
        assert bat.exists()
        content = bat.read_text()
        assert "garmin-sync.exe" in content
        assert "sync all --days 1 --detailed" in content
        assert "analyze" in content

        # Two schtasks /Create calls
        assert mock_run.call_count == 2
        first_args = mock_run.call_args_list[0][0][0]
        assert "/Create" in first_args
        assert "GarminSync-Weekday" in first_args
        assert "MON,TUE,WED,THU,FRI" in first_args

        second_args = mock_run.call_args_list[1][0][0]
        assert "GarminSync-Weekend" in second_args
        assert "SAT,SUN" in second_args

    @patch("garmin_sync.scheduler.windows_task.shutil.which")
    def test_install_garmin_sync_not_found(self, mock_which, tmp_path):
        """Install fails if garmin-sync is not in PATH."""
        mock_which.return_value = None

        success, message = windows_task.install(tmp_path / "logs")

        assert success is False
        assert "not found in PATH" in message

    @patch("garmin_sync.scheduler.windows_task.subprocess.run")
    @patch("garmin_sync.scheduler.windows_task.shutil.which")
    def test_install_schtasks_failure(self, mock_which, mock_run, tmp_path):
        """Install fails if schtasks returns non-zero."""
        mock_which.return_value = r"C:\Python\Scripts\garmin-sync.exe"
        mock_run.return_value = MagicMock(returncode=1, stderr="Access denied")

        success, message = windows_task.install(tmp_path / "logs")

        assert success is False
        assert "Access denied" in message

    @patch("garmin_sync.scheduler.windows_task.subprocess.run")
    @patch("garmin_sync.scheduler.windows_task.shutil.which")
    def test_install_custom_hours(self, mock_which, mock_run, tmp_path):
        """Install passes custom hours to schtasks."""
        mock_which.return_value = r"C:\Python\Scripts\garmin-sync.exe"
        mock_run.return_value = MagicMock(returncode=0, stderr="")

        windows_task.install(tmp_path / "logs", weekday_hour=6, weekend_hour=9)

        first_args = mock_run.call_args_list[0][0][0]
        assert "06:00" in first_args

        second_args = mock_run.call_args_list[1][0][0]
        assert "09:00" in second_args


class TestWindowsTaskUninstall:
    """Test windows_task.uninstall()."""

    @patch("garmin_sync.scheduler.windows_task.subprocess.run")
    def test_uninstall_success(self, mock_run):
        """Uninstall deletes both tasks."""
        mock_run.return_value = MagicMock(returncode=0, stderr="")

        success, message = windows_task.uninstall()

        assert success is True
        assert "Uninstalled successfully" in message
        assert mock_run.call_count == 2

        # Both tasks deleted
        names = [c[0][0][3] for c in mock_run.call_args_list]
        assert "GarminSync-Weekday" in names
        assert "GarminSync-Weekend" in names

    @patch("garmin_sync.scheduler.windows_task.subprocess.run")
    def test_uninstall_task_not_found(self, mock_run):
        """Uninstall succeeds if tasks don't exist (already removed)."""
        mock_run.return_value = MagicMock(
            returncode=1, stderr="ERROR: The system cannot find the file specified."
        )

        success, message = windows_task.uninstall()

        # "cannot find" is treated as success (task wasn't there)
        assert success is True

    @patch("garmin_sync.scheduler.windows_task.subprocess.run")
    def test_uninstall_real_error(self, mock_run):
        """Uninstall fails on a real error."""
        mock_run.return_value = MagicMock(
            returncode=1, stderr="Access is denied."
        )

        success, message = windows_task.uninstall()

        assert success is False
        assert "Access is denied" in message


class TestWindowsTaskGetStatus:
    """Test windows_task.get_status()."""

    @patch("garmin_sync.scheduler.windows_task._query_task")
    def test_status_installed(self, mock_query):
        """Status with both tasks present."""
        mock_query.side_effect = [
            {
                "task_name": "GarminSync-Weekday",
                "status": "Ready",
                "next_run": "5/21/2026 7:00:00 AM",
                "last_run": "5/20/2026 7:00:00 AM",
                "last_result": "0",
            },
            {
                "task_name": "GarminSync-Weekend",
                "status": "Ready",
                "next_run": "5/24/2026 10:00:00 AM",
                "last_run": "5/18/2026 10:00:00 AM",
                "last_result": "0",
            },
        ]

        status = windows_task.get_status()

        assert status["installed"] is True
        assert status["loaded"] is True
        assert "weekday" in status["tasks"]
        assert "weekend" in status["tasks"]
        assert status["tasks"]["weekday"]["status"] == "Ready"

    @patch("garmin_sync.scheduler.windows_task._query_task")
    def test_status_not_installed(self, mock_query):
        """Status when no tasks exist."""
        mock_query.return_value = None

        status = windows_task.get_status()

        assert status["installed"] is False
        assert status["loaded"] is False
        assert status["schedule"] is None
        assert status["tasks"] == {}

    @patch("garmin_sync.scheduler.windows_task.subprocess.run")
    def test_query_task_parses_csv(self, mock_run):
        """_query_task correctly parses schtasks CSV output."""
        csv_output = (
            '"TaskName","Next Run Time","Status","Last Run Time","Last Result"\r\n'
            '"\\GarminSync-Weekday","5/21/2026 7:00:00 AM","Ready",'
            '"5/20/2026 7:00:00 AM","0"\r\n'
        )
        mock_run.return_value = MagicMock(returncode=0, stdout=csv_output)

        result = windows_task._query_task("GarminSync-Weekday")

        assert result is not None
        assert result["status"] == "Ready"
        assert "5/21/2026" in result["next_run"]

    @patch("garmin_sync.scheduler.windows_task.subprocess.run")
    def test_query_task_not_found(self, mock_run):
        """_query_task returns None when task doesn't exist."""
        mock_run.return_value = MagicMock(returncode=1, stdout="")

        result = windows_task._query_task("GarminSync-Weekday")

        assert result is None
