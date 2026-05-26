"""Tests for sync manager."""

from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch
import json

import pytest

from garmin_sync.db.database import Database
from garmin_sync.db.repository import Repository
from garmin_sync.sync.sync_manager import (
    FRESHNESS_DAYS,
    SyncManager,
    SyncResult,
    HR_DRIFT_ACTIVITY_TYPES,
    HR_DRIFT_MIN_DURATION,
    FIT_PARSE_MIN_DURATION,
)
from garmin_sync.sync.fit_parser import (
    compute_hr_drift_from_fit,
    extract_hr_samples,
    FitParseResult,
)


class TestSyncResult:
    """Test SyncResult class."""

    def test_initial_state(self):
        """Test initial SyncResult state."""
        result = SyncResult("activities")

        assert result.data_type == "activities"
        assert result.records_synced == 0
        assert result.records_skipped == 0
        assert result.errors == []
        assert result.success is True

    def test_add_error(self):
        """Test adding errors."""
        result = SyncResult("activities")
        result.add_error("Test error")

        assert len(result.errors) == 1
        assert "Test error" in result.errors
        assert result.success is False

    def test_repr(self):
        """Test string representation."""
        result = SyncResult("activities")
        result.records_synced = 5
        result.records_skipped = 2

        repr_str = repr(result)
        assert "activities" in repr_str
        assert "synced=5" in repr_str
        assert "skipped=2" in repr_str


class TestSyncManager:
    """Test SyncManager class."""

    @pytest.fixture
    def db(self):
        """Create in-memory database."""
        db = Database(":memory:")
        db.initialize()
        return db

    @pytest.fixture
    def mock_client(self):
        """Create mock Garmin client."""
        return MagicMock()

    @pytest.fixture
    def sync_manager(self, db, mock_client):
        """Create SyncManager with mocked dependencies."""
        console = MagicMock()
        return SyncManager(db=db, client=mock_client, console=console)

    def test_sync_activities(self, sync_manager, mock_client):
        """Test syncing activities."""
        mock_client.get_activities_by_date.return_value = [
            {
                "activityId": "12345",
                "activityName": "Morning Run",
                "activityType": {"typeKey": "running"},
                "startTimeGMT": "2024-01-15T07:00:00.0",
                "duration": 3600.0,
                "distance": 10000.0,
            },
            {
                "activityId": "12346",
                "activityName": "Afternoon Ride",
                "activityType": {"typeKey": "cycling"},
                "startTimeGMT": "2024-01-15T14:00:00.0",
                "duration": 5400.0,
                "distance": 30000.0,
            },
        ]

        result = sync_manager.sync_activities(
            start_date=date(2024, 1, 10),
            end_date=date(2024, 1, 15),
        )

        assert result.success is True
        assert result.records_synced == 2
        assert result.records_skipped == 0

        # Verify activities were saved
        repo = Repository(sync_manager.db)
        activities = repo.get_activities()
        assert len(activities) == 2

    def test_sync_activities_incremental(self, sync_manager, mock_client):
        """Test that incremental sync skips existing activities."""
        # First sync
        mock_client.get_activities_by_date.return_value = [
            {
                "activityId": "12345",
                "activityName": "Morning Run",
                "activityType": {"typeKey": "running"},
                "startTimeGMT": "2024-01-15T07:00:00.0",
            },
        ]

        result1 = sync_manager.sync_activities(
            start_date=date(2024, 1, 10),
            end_date=date(2024, 1, 15),
        )
        assert result1.records_synced == 1

        # Second sync with same activity
        result2 = sync_manager.sync_activities(
            start_date=date(2024, 1, 10),
            end_date=date(2024, 1, 15),
        )
        assert result2.records_synced == 0
        assert result2.records_skipped == 1

    def test_sync_activities_force(self, sync_manager, mock_client):
        """Test force sync re-downloads existing activities."""
        mock_client.get_activities_by_date.return_value = [
            {
                "activityId": "12345",
                "activityName": "Morning Run",
                "activityType": {"typeKey": "running"},
                "startTimeGMT": "2024-01-15T07:00:00.0",
            },
        ]

        # First sync
        sync_manager.sync_activities(
            start_date=date(2024, 1, 10),
            end_date=date(2024, 1, 15),
        )

        # Force sync
        result = sync_manager.sync_activities(
            start_date=date(2024, 1, 10),
            end_date=date(2024, 1, 15),
            force=True,
        )

        assert result.records_synced == 1
        assert result.records_skipped == 0

    def test_sync_sleep(self, sync_manager, mock_client):
        """Test syncing sleep data using batch endpoint."""
        mock_client.get_daily_sleep_batch.return_value = [
            {"calendarDate": "2024-01-15", "sleepScore": 85}
        ]

        result = sync_manager.sync_sleep(
            start_date=date(2024, 1, 15),
            end_date=date(2024, 1, 15),
        )

        assert result.success is True
        assert result.records_synced == 1

        # Verify data was saved
        repo = Repository(sync_manager.db)
        sleep = repo.get_sleep("2024-01-15")
        assert sleep is not None
        assert sleep.sleep_score == 85

    def test_sync_heart_rate(self, sync_manager, mock_client):
        """Test syncing heart rate data."""
        mock_client.get_heart_rates.return_value = {
            "calendarDate": "2024-01-15",
            "restingHeartRate": 52,
            "maxHeartRate": 180,
            "minHeartRate": 45,
        }

        result = sync_manager.sync_heart_rate(
            start_date=date(2024, 1, 15),
            end_date=date(2024, 1, 15),
        )

        assert result.success is True
        assert result.records_synced == 1

    def test_sync_stress(self, sync_manager, mock_client):
        """Test syncing stress data using batch endpoint."""
        mock_client.get_daily_stress_batch.return_value = [
            {"calendarDate": "2024-01-15", "avgStress": 30}
        ]

        result = sync_manager.sync_stress(
            start_date=date(2024, 1, 15),
            end_date=date(2024, 1, 15),
        )

        assert result.success is True
        assert result.records_synced == 1

    def test_sync_hrv(self, sync_manager, mock_client):
        """Test syncing HRV data using batch endpoint."""
        mock_client.get_daily_hrv_batch.return_value = [
            {"calendarDate": "2024-01-15", "hrvValue": 45}
        ]

        result = sync_manager.sync_hrv(
            start_date=date(2024, 1, 15),
            end_date=date(2024, 1, 15),
        )

        assert result.success is True
        assert result.records_synced == 1

    def test_sync_body_battery(self, sync_manager, mock_client):
        """Test syncing body battery data using batch endpoint."""
        # Batch endpoint returns list of daily summary dicts
        mock_client.get_body_battery_batch.return_value = [
            {
                "date": "2024-01-15",
                "charged": 63,
                "drained": 68,
                "bodyBatteryValuesArray": [
                    [1705305600000, 41],
                    [1705320000000, 100],
                    [1705334400000, 60],
                ],
            }
        ]

        result = sync_manager.sync_body_battery(
            start_date=date(2024, 1, 15),
            end_date=date(2024, 1, 15),
        )

        assert result.success is True
        assert result.records_synced == 1

    def test_sync_daily_summaries(self, sync_manager, mock_client):
        """Test syncing daily summaries using batch endpoint."""
        # Batch endpoint returns list of daily step data
        mock_client.get_daily_steps_batch.return_value = [
            {
                "calendarDate": "2024-01-15",
                "totalSteps": 10000,
                "stepGoal": 8000,
                "totalDistance": 8000.0,
                "totalCalories": 2500,
            }
        ]

        result = sync_manager.sync_daily_summaries(
            start_date=date(2024, 1, 15),
            end_date=date(2024, 1, 15),
        )

        assert result.success is True
        assert result.records_synced == 1

        repo = Repository(sync_manager.db)
        summary = repo.get_daily_summary("2024-01-15")
        assert summary is not None
        assert summary.total_steps == 10000

    def test_sync_multiple_days(self, sync_manager, mock_client):
        """Test syncing multiple days of data using batch endpoint."""
        # Batch endpoint returns all days in a single call
        mock_client.get_daily_steps_batch.return_value = [
            {"calendarDate": "2024-01-10", "totalSteps": 10100},
            {"calendarDate": "2024-01-11", "totalSteps": 10200},
            {"calendarDate": "2024-01-12", "totalSteps": 10300},
            {"calendarDate": "2024-01-13", "totalSteps": 10400},
            {"calendarDate": "2024-01-14", "totalSteps": 10500},
            {"calendarDate": "2024-01-15", "totalSteps": 10600},
        ]

        result = sync_manager.sync_daily_summaries(
            start_date=date(2024, 1, 10),
            end_date=date(2024, 1, 15),
        )

        assert result.success is True
        assert result.records_synced == 6  # 6 days

    def test_sync_handles_empty_response(self, sync_manager, mock_client):
        """Test that empty API responses are handled gracefully."""
        # Batch endpoint returns empty list when no data
        mock_client.get_daily_sleep_batch.return_value = []

        result = sync_manager.sync_sleep(
            start_date=date(2024, 1, 15),
            end_date=date(2024, 1, 15),
        )

        assert result.success is True
        assert result.records_synced == 0

    def test_sync_handles_api_error(self, sync_manager, mock_client):
        """Test that API errors are handled gracefully."""
        mock_client.get_activities_by_date.side_effect = Exception("API Error")

        result = sync_manager.sync_activities(
            start_date=date(2024, 1, 15),
            end_date=date(2024, 1, 15),
        )

        assert result.success is False
        assert len(result.errors) > 0

    def test_sync_metadata_updated(self, sync_manager, mock_client):
        """Test that sync metadata is updated after sync."""
        mock_client.get_activities_by_date.return_value = [
            {
                "activityId": "12345",
                "activityName": "Run",
                "startTimeGMT": "2024-01-15T07:00:00.0",
            },
        ]

        sync_manager.sync_activities(
            start_date=date(2024, 1, 15),
            end_date=date(2024, 1, 15),
        )

        repo = Repository(sync_manager.db)
        metadata = repo.get_sync_metadata("activities")

        assert metadata is not None
        assert metadata.sync_status == "success"
        assert metadata.records_synced == 1

    def test_sync_training_readiness(self, sync_manager, mock_client):
        """Test syncing training readiness data."""
        mock_client.get_training_readiness.return_value = {
            "calendarDate": "2024-01-15",
            "score": 75,
            "level": "MODERATE",
        }

        result = sync_manager.sync_training_readiness(
            start_date=date(2024, 1, 15),
            end_date=date(2024, 1, 15),
        )

        assert result.success is True
        assert result.records_synced == 1

    def test_sync_all_default_uses_batch(self, sync_manager, mock_client):
        """Default sync uses batch endpoints for efficiency."""
        # Setup batch endpoint responses
        mock_client.get_activities_by_date.return_value = []
        mock_client.get_daily_steps_batch.return_value = []
        mock_client.get_daily_sleep_batch.return_value = []
        mock_client.get_heart_rates.return_value = {}
        mock_client.get_daily_stress_batch.return_value = []
        mock_client.get_daily_hrv_batch.return_value = []
        mock_client.get_body_battery_batch.return_value = []
        mock_client.get_training_readiness.return_value = {}

        sync_manager.sync_all(days=7, detailed=False)

        # Batch endpoints should be called
        mock_client.get_daily_sleep_batch.assert_called()
        mock_client.get_daily_stress_batch.assert_called()
        mock_client.get_daily_hrv_batch.assert_called()

        # Per-day endpoints should NOT be called
        mock_client.get_sleep_data.assert_not_called()
        mock_client.get_stress_data.assert_not_called()
        mock_client.get_hrv_data.assert_not_called()

    def test_sync_all_detailed_uses_per_day(self, sync_manager, mock_client):
        """Detailed sync uses per-day endpoints for full data."""
        # Setup per-day endpoint responses
        mock_client.get_activities_by_date.return_value = []
        mock_client.get_daily_steps_batch.return_value = []
        mock_client.get_sleep_data.return_value = {}
        mock_client.get_heart_rates.return_value = {}
        mock_client.get_stress_data.return_value = {}
        mock_client.get_hrv_data.return_value = {}
        mock_client.get_body_battery_batch.return_value = []
        mock_client.get_training_readiness.return_value = {}

        sync_manager.sync_all(days=3, detailed=True)

        # Per-day endpoints should be called
        mock_client.get_sleep_data.assert_called()
        mock_client.get_stress_data.assert_called()
        mock_client.get_hrv_data.assert_called()

        # Batch endpoints for sleep/stress/hrv should NOT be called
        mock_client.get_daily_sleep_batch.assert_not_called()
        mock_client.get_daily_stress_batch.assert_not_called()
        mock_client.get_daily_hrv_batch.assert_not_called()

    def test_sync_sleep_detailed(self, sync_manager, mock_client):
        """Test syncing sleep data using per-day endpoints."""
        mock_client.get_sleep_data.return_value = {
            "dailySleepDTO": {
                "calendarDate": "2024-01-15",
                "sleepTimeSeconds": 28800,
                "deepSleepSeconds": 5400,
                "lightSleepSeconds": 14400,
                "remSleepSeconds": 7200,
                "awakeSleepSeconds": 1800,
            },
            "sleepScores": {
                "overall": {"value": 85, "qualifierKey": "GOOD"}
            }
        }

        result = sync_manager.sync_sleep_detailed(
            start_date=date(2024, 1, 15),
            end_date=date(2024, 1, 15),
        )

        assert result.success is True
        assert result.records_synced == 1
        mock_client.get_sleep_data.assert_called()

    def test_sync_stress_detailed(self, sync_manager, mock_client):
        """Test syncing stress data using per-day endpoints."""
        mock_client.get_stress_data.return_value = {
            "calendarDate": "2024-01-15",
            "overallStressLevel": 35,
            "avgStressLevel": 28,
            "maxStressLevel": 72,
            "restStressDuration": 14400,
            "lowStressDuration": 21600,
            "mediumStressDuration": 7200,
            "highStressDuration": 1800,
        }

        result = sync_manager.sync_stress_detailed(
            start_date=date(2024, 1, 15),
            end_date=date(2024, 1, 15),
        )

        assert result.success is True
        assert result.records_synced == 1
        mock_client.get_stress_data.assert_called()

    def test_sync_hrv_detailed(self, sync_manager, mock_client):
        """Test syncing HRV data using per-day endpoints."""
        mock_client.get_hrv_data.return_value = {
            "hrvSummary": {
                "calendarDate": "2024-01-15",
                "weeklyAvg": 65,
                "lastNightAvg": 68,
                "status": "BALANCED",
                "baseline": {
                    "lowUpper": 45,
                    "balancedLow": 55,
                    "balancedUpper": 75,
                }
            }
        }

        result = sync_manager.sync_hrv_detailed(
            start_date=date(2024, 1, 15),
            end_date=date(2024, 1, 15),
        )

        assert result.success is True
        assert result.records_synced == 1
        mock_client.get_hrv_data.assert_called()


class TestFitParser:
    """Test FIT file parsing utilities."""

    def test_compute_hr_drift_positive(self):
        """Positive HR drift when second half HR is higher."""
        # Mock HR samples: first half avg 140, second half avg 150
        # Drift = (150-140)/140 = 0.0714
        with patch("garmin_sync.sync.fit_parser.extract_hr_samples") as mock_extract:
            mock_extract.return_value = [140] * 600 + [150] * 600
            drift = compute_hr_drift_from_fit(b"mock_fit_data")

            assert drift == pytest.approx(0.0714, rel=0.01)

    def test_compute_hr_drift_negative(self):
        """Negative HR drift when second half HR is lower."""
        # Mock HR samples: first half avg 150, second half avg 140
        # Drift = (140-150)/150 = -0.0667
        with patch("garmin_sync.sync.fit_parser.extract_hr_samples") as mock_extract:
            mock_extract.return_value = [150] * 600 + [140] * 600
            drift = compute_hr_drift_from_fit(b"mock_fit_data")

            assert drift == pytest.approx(-0.0667, rel=0.01)

    def test_compute_hr_drift_zero(self):
        """Zero HR drift when both halves have same average."""
        with patch("garmin_sync.sync.fit_parser.extract_hr_samples") as mock_extract:
            mock_extract.return_value = [145] * 1200
            drift = compute_hr_drift_from_fit(b"mock_fit_data")

            assert drift == pytest.approx(0.0)

    def test_compute_hr_drift_returns_none_for_insufficient_samples(self):
        """Returns None when too few HR samples."""
        with patch("garmin_sync.sync.fit_parser.extract_hr_samples") as mock_extract:
            mock_extract.return_value = [140, 145]  # Only 2 samples
            assert compute_hr_drift_from_fit(b"mock_fit_data") is None

    def test_compute_hr_drift_returns_none_for_empty_samples(self):
        """Returns None when no HR samples."""
        with patch("garmin_sync.sync.fit_parser.extract_hr_samples") as mock_extract:
            mock_extract.return_value = []
            assert compute_hr_drift_from_fit(b"mock_fit_data") is None

    def test_compute_hr_drift_handles_parse_error(self):
        """Returns None for invalid FIT data."""
        # Invalid bytes should not crash
        assert compute_hr_drift_from_fit(b"not a fit file") is None


class TestSyncManagerHRDrift:
    """Test HR drift integration in sync manager."""

    @pytest.fixture
    def db(self):
        """Create in-memory database."""
        db = Database(":memory:")
        db.initialize()
        return db

    @pytest.fixture
    def mock_client(self):
        """Create mock Garmin client."""
        return MagicMock()

    @pytest.fixture
    def sync_manager(self, db, mock_client):
        """Create SyncManager with mocked dependencies."""
        console = MagicMock()
        return SyncManager(db=db, client=mock_client, console=console)

    def test_hr_drift_activity_types_defined(self):
        """HR drift activity types are properly defined."""
        assert "running" in HR_DRIFT_ACTIVITY_TYPES
        assert "treadmill_running" in HR_DRIFT_ACTIVITY_TYPES
        assert "elliptical" in HR_DRIFT_ACTIVITY_TYPES

    def test_hr_drift_min_duration(self):
        """HR drift minimum duration is 20 minutes (1200 seconds)."""
        assert HR_DRIFT_MIN_DURATION == 1200

    @patch("garmin_sync.sync.sync_manager.get_settings")
    @patch("garmin_sync.sync.sync_manager.parse_fit_full")
    def test_sync_activities_computes_hr_drift_for_qualifying(
        self, mock_parse, mock_settings, sync_manager, mock_client, temp_dir
    ):
        """HR drift is computed via full FIT parse for qualifying activities."""
        # Setup settings mock
        mock_settings_obj = MagicMock()
        mock_settings_obj.fit_files_dir = temp_dir / "fit_files"
        mock_settings_obj.download_fit_files = True
        mock_settings.return_value = mock_settings_obj

        # Setup parse_fit_full mock
        mock_parse.return_value = FitParseResult(laps=[], splits=[], hr_drift=0.05)

        # Setup FIT download
        mock_client.download_activity_fit.return_value = b"mock_fit_data"

        # Activity that qualifies: running, >5min, has HR
        mock_client.get_activities_by_date.return_value = [
            {
                "activityId": "12345",
                "activityName": "Morning Run",
                "activityType": {"typeKey": "running"},
                "startTimeGMT": "2024-01-15T07:00:00.0",
                "duration": 2400.0,  # 40 minutes
                "averageHR": 145,
            },
        ]

        result = sync_manager.sync_activities(
            start_date=date(2024, 1, 10),
            end_date=date(2024, 1, 15),
        )

        assert result.success is True
        assert result.records_synced == 1

        # Verify FIT was downloaded
        mock_client.download_activity_fit.assert_called_once_with("12345")

        # Verify activity has HR drift and fit_parsed flag
        repo = Repository(sync_manager.db)
        activity = repo.get_activity("12345")
        assert activity.hr_drift == pytest.approx(0.05)
        assert activity.has_fit_file is True
        assert activity.fit_parsed is True

    @patch("garmin_sync.sync.sync_manager.get_settings")
    def test_sync_activities_skips_fit_parse_for_short_activities(
        self, mock_settings, sync_manager, mock_client, temp_dir
    ):
        """FIT files are not downloaded for activities shorter than 5 minutes."""
        mock_settings_obj = MagicMock()
        mock_settings_obj.fit_files_dir = temp_dir / "fit_files"
        mock_settings_obj.download_fit_files = True
        mock_settings.return_value = mock_settings_obj

        # Activity too short (< 5 min / FIT_PARSE_MIN_DURATION)
        mock_client.get_activities_by_date.return_value = [
            {
                "activityId": "12345",
                "activityName": "Short Run",
                "activityType": {"typeKey": "running"},
                "startTimeGMT": "2024-01-15T07:00:00.0",
                "duration": 240.0,  # 4 minutes — below threshold
                "averageHR": 145,
            },
        ]

        sync_manager.sync_activities(
            start_date=date(2024, 1, 10),
            end_date=date(2024, 1, 15),
        )

        # FIT should NOT be downloaded for short activity
        mock_client.download_activity_fit.assert_not_called()

        repo = Repository(sync_manager.db)
        activity = repo.get_activity("12345")
        assert activity.hr_drift is None
        assert activity.fit_parsed is False

    @patch("garmin_sync.sync.sync_manager.get_settings")
    @patch("garmin_sync.sync.sync_manager.parse_fit_full")
    def test_sync_activities_parses_fit_for_all_activity_types(
        self, mock_parse, mock_settings, sync_manager, mock_client, temp_dir
    ):
        """FIT files are parsed for all activity types (not just running)."""
        mock_settings_obj = MagicMock()
        mock_settings_obj.fit_files_dir = temp_dir / "fit_files"
        mock_settings_obj.download_fit_files = True
        mock_settings.return_value = mock_settings_obj

        mock_parse.return_value = FitParseResult(laps=[], splits=[], hr_drift=None)
        mock_client.download_activity_fit.return_value = b"mock_fit_data"

        # Strength training now gets FIT parsed (for laps/splits)
        mock_client.get_activities_by_date.return_value = [
            {
                "activityId": "12345",
                "activityName": "Gym Session",
                "activityType": {"typeKey": "strength_training"},
                "startTimeGMT": "2024-01-15T07:00:00.0",
                "duration": 3600.0,  # 60 minutes
                "averageHR": 120,
            },
        ]

        sync_manager.sync_activities(
            start_date=date(2024, 1, 10),
            end_date=date(2024, 1, 15),
        )

        # FIT IS now downloaded for all activity types >= 5 min
        mock_client.download_activity_fit.assert_called_once_with("12345")

        repo = Repository(sync_manager.db)
        activity = repo.get_activity("12345")
        assert activity.has_fit_file is True
        assert activity.fit_parsed is True

    @patch("garmin_sync.sync.sync_manager.get_settings")
    @patch("garmin_sync.sync.sync_manager.parse_fit_full")
    def test_sync_activities_parses_fit_even_without_hr(
        self, mock_parse, mock_settings, sync_manager, mock_client, temp_dir
    ):
        """FIT files are parsed even for activities without HR data (for laps/splits)."""
        mock_settings_obj = MagicMock()
        mock_settings_obj.fit_files_dir = temp_dir / "fit_files"
        mock_settings_obj.download_fit_files = True
        mock_settings.return_value = mock_settings_obj

        mock_parse.return_value = FitParseResult(laps=[], splits=[], hr_drift=None)
        mock_client.download_activity_fit.return_value = b"mock_fit_data"

        # No averageHR field — FIT is still downloaded for laps/splits
        mock_client.get_activities_by_date.return_value = [
            {
                "activityId": "12345",
                "activityName": "Morning Run",
                "activityType": {"typeKey": "running"},
                "startTimeGMT": "2024-01-15T07:00:00.0",
                "duration": 3600.0,
            },
        ]

        sync_manager.sync_activities(
            start_date=date(2024, 1, 10),
            end_date=date(2024, 1, 15),
        )

        mock_client.download_activity_fit.assert_called_once_with("12345")

        repo = Repository(sync_manager.db)
        activity = repo.get_activity("12345")
        assert activity.has_fit_file is True
        assert activity.hr_drift is None  # No HR data in FIT

    @patch("garmin_sync.sync.sync_manager.get_settings")
    def test_sync_activities_handles_fit_download_error(
        self, mock_settings, sync_manager, mock_client, temp_dir
    ):
        """Activity sync continues if FIT download fails."""
        mock_settings_obj = MagicMock()
        mock_settings_obj.fit_files_dir = temp_dir / "fit_files"
        mock_settings_obj.download_fit_files = True
        mock_settings.return_value = mock_settings_obj

        # FIT download fails
        mock_client.download_activity_fit.side_effect = Exception("Download failed")

        mock_client.get_activities_by_date.return_value = [
            {
                "activityId": "12345",
                "activityName": "Morning Run",
                "activityType": {"typeKey": "running"},
                "startTimeGMT": "2024-01-15T07:00:00.0",
                "duration": 2400.0,
                "averageHR": 145,
            },
        ]

        result = sync_manager.sync_activities(
            start_date=date(2024, 1, 10),
            end_date=date(2024, 1, 15),
        )

        # Activity should still sync successfully
        assert result.success is True
        assert result.records_synced == 1

        # HR drift should be None since FIT download failed
        repo = Repository(sync_manager.db)
        activity = repo.get_activity("12345")
        assert activity.hr_drift is None

    @patch("garmin_sync.sync.sync_manager.get_settings")
    def test_download_and_store_fit_caches(
        self, mock_settings, sync_manager, mock_client, temp_dir
    ):
        """FIT file is stored and reused on subsequent calls."""
        fit_dir = temp_dir / "fit_files"
        mock_settings_obj = MagicMock()
        mock_settings_obj.fit_files_dir = fit_dir
        mock_settings.return_value = mock_settings_obj

        mock_client.download_activity_fit.return_value = b"mock_fit_data"

        # First call should download
        path1 = sync_manager._download_and_store_fit("12345")
        assert path1 is not None
        assert path1.exists()
        assert mock_client.download_activity_fit.call_count == 1

        # Second call should use cached file
        path2 = sync_manager._download_and_store_fit("12345")
        assert path2 == path1
        assert mock_client.download_activity_fit.call_count == 1  # Not called again


class TestFreshnessDaysBoundary:
    """Test FRESHNESS_DAYS skip logic boundary conditions.

    The _sync_daily_metric method skips dates older than FRESHNESS_DAYS
    when a record already exists, unless force=True. These tests verify
    the boundary behavior using sync_training_readiness which delegates
    to _sync_daily_metric with table="training_readiness".
    """

    @pytest.fixture
    def fixed_today(self):
        """Return a fixed 'today' date for deterministic tests."""
        return date(2026, 5, 26)

    @pytest.fixture
    def db(self):
        """Create in-memory database."""
        db = Database(":memory:")
        db.initialize()
        db.migrate()
        return db

    @pytest.fixture
    def repo(self, db):
        """Create repository."""
        return Repository(db)

    @pytest.fixture
    def mock_client(self):
        """Create mock Garmin client."""
        client = MagicMock()
        client.get_training_readiness.return_value = {
            "calendarDate": "2026-05-18",
            "score": 75,
            "level": "MODERATE",
        }
        return client

    @pytest.fixture
    def sync_manager(self, db, mock_client):
        """Create SyncManager with mocked client."""
        console = MagicMock()
        return SyncManager(db=db, client=mock_client, console=console)

    def _insert_training_readiness(self, repo, date_str):
        """Insert a training readiness record for the given date."""
        from garmin_sync.db.models import TrainingReadiness

        model = TrainingReadiness(
            date=date_str,
            score=70,
            level="MODERATE",
        )
        repo.upsert_training_readiness(model)

    @patch("garmin_sync.sync.sync_manager.date")
    def test_date_before_cutoff_skips_existing(
        self, mock_date, sync_manager, repo, mock_client, fixed_today
    ):
        """Date 8 days ago with existing record should be skipped."""
        mock_date.today.return_value = fixed_today
        mock_date.side_effect = lambda *args, **kw: date(*args, **kw)

        target = fixed_today - timedelta(days=8)
        self._insert_training_readiness(repo, target.isoformat())

        mock_client.get_training_readiness.return_value = {
            "calendarDate": target.isoformat(),
            "score": 80,
            "level": "HIGH",
        }

        result = sync_manager.sync_training_readiness(
            start_date=target,
            end_date=target,
        )

        assert result.records_skipped == 1
        assert result.records_synced == 0

    @patch("garmin_sync.sync.sync_manager.date")
    def test_date_at_cutoff_re_fetches(
        self, mock_date, sync_manager, repo, mock_client, fixed_today
    ):
        """Date exactly FRESHNESS_DAYS ago should NOT be skipped."""
        mock_date.today.return_value = fixed_today
        mock_date.side_effect = lambda *args, **kw: date(*args, **kw)

        target = fixed_today - timedelta(days=FRESHNESS_DAYS)
        self._insert_training_readiness(repo, target.isoformat())

        mock_client.get_training_readiness.return_value = {
            "calendarDate": target.isoformat(),
            "score": 80,
            "level": "HIGH",
        }

        result = sync_manager.sync_training_readiness(
            start_date=target,
            end_date=target,
        )

        assert result.records_synced == 1

    @patch("garmin_sync.sync.sync_manager.date")
    def test_date_within_window_re_fetches(
        self, mock_date, sync_manager, repo, mock_client, fixed_today
    ):
        """Date 3 days ago (within freshness window) should always re-fetch."""
        mock_date.today.return_value = fixed_today
        mock_date.side_effect = lambda *args, **kw: date(*args, **kw)

        target = fixed_today - timedelta(days=3)
        self._insert_training_readiness(repo, target.isoformat())

        mock_client.get_training_readiness.return_value = {
            "calendarDate": target.isoformat(),
            "score": 80,
            "level": "HIGH",
        }

        result = sync_manager.sync_training_readiness(
            start_date=target,
            end_date=target,
        )

        assert result.records_synced == 1

    @patch("garmin_sync.sync.sync_manager.date")
    def test_force_bypasses_skip(
        self, mock_date, sync_manager, repo, mock_client, fixed_today
    ):
        """force=True should always re-fetch even for old existing records."""
        mock_date.today.return_value = fixed_today
        mock_date.side_effect = lambda *args, **kw: date(*args, **kw)

        target = fixed_today - timedelta(days=8)
        self._insert_training_readiness(repo, target.isoformat())

        mock_client.get_training_readiness.return_value = {
            "calendarDate": target.isoformat(),
            "score": 80,
            "level": "HIGH",
        }

        result = sync_manager.sync_training_readiness(
            start_date=target,
            end_date=target,
            force=True,
        )

        assert result.records_synced == 1

    @patch("garmin_sync.sync.sync_manager.date")
    def test_no_existing_record_always_fetches(
        self, mock_date, sync_manager, mock_client, fixed_today
    ):
        """Date 8 days ago with no existing record should still fetch."""
        mock_date.today.return_value = fixed_today
        mock_date.side_effect = lambda *args, **kw: date(*args, **kw)

        target = fixed_today - timedelta(days=8)

        mock_client.get_training_readiness.return_value = {
            "calendarDate": target.isoformat(),
            "score": 80,
            "level": "HIGH",
        }

        result = sync_manager.sync_training_readiness(
            start_date=target,
            end_date=target,
        )

        assert result.records_synced == 1


class TestDryRunPlan:
    """Test SyncManager.dry_run_plan() previews sync without API calls."""

    @pytest.fixture
    def db(self):
        db = Database(":memory:")
        db.initialize()
        db.migrate()
        return db

    @pytest.fixture
    def sync_manager(self, db):
        console = MagicMock()
        client = MagicMock()  # Should never be called
        return SyncManager(db=db, client=client, console=console)

    def test_dry_run_returns_expected_keys(self, sync_manager):
        """Plan dict contains all expected top-level keys."""
        plan = sync_manager.dry_run_plan(days=3)
        assert "date_range" in plan
        assert "types" in plan
        assert "estimated_api_calls" in plan
        assert plan["date_range"]["days"] == 3

    def test_dry_run_counts_existing_records(self, sync_manager, db):
        """Existing DB records show up in the plan."""
        from garmin_sync.db.models import TrainingReadiness

        today = date.today()
        repo = Repository(db)
        tr = TrainingReadiness(date=today.isoformat(), score=70, level="MODERATE")
        repo.upsert_training_readiness(tr)

        plan = sync_manager.dry_run_plan(days=1)
        assert plan["types"]["training_readiness"]["existing"] >= 1

    def test_dry_run_no_api_calls_made(self, sync_manager):
        """dry_run_plan must not call any API methods."""
        plan = sync_manager.dry_run_plan(days=5)
        # The mock client should have zero calls
        sync_manager._client.assert_not_called()
        assert plan["estimated_api_calls"] > 0

    def test_dry_run_force_flag(self, sync_manager):
        """Force mode sets force=True in the plan."""
        plan = sync_manager.dry_run_plan(days=3, force=True)
        assert plan["force"] is True
