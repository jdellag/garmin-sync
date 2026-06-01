"""Tests for MCP server tools."""

import sqlite3

import pytest
from datetime import date, timedelta
from unittest.mock import MagicMock, patch, call

from garmin_sync.db.database import Database
from garmin_sync.db.models import Activity
from garmin_sync.db.repository import Repository
from garmin_sync.tools.executor import ToolExecutor


class TestMCPServer:
    """Test MCP server tools."""

    @pytest.fixture
    def mock_repo(self):
        """Create mock repository."""
        repo = MagicMock()
        repo.get_latest_sync_timestamp.return_value = "2026-03-16T10:00:00Z"
        repo.get_hevy_workout_count.return_value = 0
        repo.get_recent_prs.return_value = []
        repo.db = MagicMock()
        return repo

    @pytest.fixture
    def mock_aggregator(self):
        """Create mock aggregator."""
        agg = MagicMock()
        agg.get_hrv_context.return_value = {
            "baseline_7d": 65,
            "last_night": 62,
            "delta_from_baseline": -4.6,
            "status": "BALANCED",
            "days_below_baseline": 1,
        }
        agg.get_sleep_consistency.return_value = {
            "avg_sleep_seconds": 28800,
            "sleep_time_variance_mins": 30,
            "avg_deep_pct": 18.5,
            "avg_rem_pct": 22.0,
        }
        agg.get_body_battery_recovery.return_value = {
            "avg_overnight_recovery": 60,
            "avg_morning_high": 85,
        }
        agg.get_resting_hr_trend.return_value = {
            "current": 48,
            "baseline_28d": 50,
            "delta": -2,
            "trend": "falling",
        }
        agg.get_training_readiness_latest.return_value = {
            "score": 75,
            "level": "MODERATE",
        }
        agg.get_training_load_trend.return_value = {
            "acute_load_7d": 200,
            "chronic_load_28d": 220,
            "acute_chronic_ratio": 0.91,
            "week_change_pct": 5.0,
            "by_type": {
                "running": {"load": 150, "count": 3},
                "cycling": {"load": 50, "count": 1},
            },
        }
        agg.get_strength_volume_summary.return_value = {
            "total_sessions": 3,
            "total_volume_kg": 5000,
            "total_sets": 45,
            "by_muscle_group": {
                "chest": {"volume_kg": 1500, "sets": 12},
                "back": {"volume_kg": 2000, "sets": 15},
            },
            "recent_workouts": [
                {
                    "date": "2026-03-15",
                    "title": "Push Day",
                    "volume_kg": 2500,
                    "exercises": [
                        {"name": "Bench Press", "muscle_group": "chest", "sets": "135×10, 145×8"}
                    ],
                }
            ],
        }
        agg.get_rpe_analysis.return_value = {
            "sessions": [],
            "overall_avg_rpe": None,
            "rpe_coverage_pct": 0.0,
            "overreaching_flag": False,
        }
        agg.get_exercise_rpe_trend.return_value = {
            "sessions": [],
            "rpe_trend": None,
        }
        agg.get_stress_recovery_correlation.return_value = {
            "days_analyzed": 0,
            "avg_stress_training_days": None,
            "avg_stress_rest_days": None,
            "high_stress_poor_recovery_days": 0,
            "patterns": [],
        }
        agg.get_sleep_performance_correlation.return_value = {
            "data_points": 0,
            "sleep_score_stats": None,
            "by_sleep_grade": {},
            "hrv_performance_link": None,
            "insight": None,
        }
        agg.get_strength_prs.return_value = []
        agg.get_strength_exercise_progression.return_value = {
            "exercise": "Bench Press",
            "sessions": [{"date": "2026-03-15", "max_weight": 80, "est_1rm": 90}],
            "current_1rm": 90,
            "progression_pct": 5.0,
        }
        return agg

    @pytest.fixture
    def executor(self, mock_repo, mock_aggregator):
        """Create ToolExecutor with mocks."""
        return ToolExecutor(mock_repo, mock_aggregator)

    def test_get_recent_activities(self, mock_repo, mock_aggregator, executor):
        """Test get_recent_activities returns serialized activities."""
        from garmin_sync.mcp import server

        mock_activity = Activity(
            activity_id="123",
            activity_name="Morning Run",
            activity_type="running",
            start_time="2026-03-16T07:00:00Z",
            duration_seconds=3600,
            distance_meters=10000,
            average_hr=145,
            max_hr=165,
            training_load=75.5,
        )
        mock_repo.get_activities.return_value = [mock_activity]

        with patch.object(server, "_get_executor", return_value=executor):
            result = server.get_recent_activities(days=7)

        assert len(result) == 1
        assert result[0]["activity_id"] == "123"
        assert result[0]["name"] == "Morning Run"
        assert result[0]["type"] == "running"
        assert result[0]["duration_seconds"] == 3600
        assert "raw_json" not in result[0]

    def test_get_recent_activities_with_filter(self, mock_repo, mock_aggregator, executor):
        """Test get_recent_activities with activity_type filter."""
        from garmin_sync.mcp import server

        mock_repo.get_activities.return_value = []

        with patch.object(server, "_get_executor", return_value=executor):
            result = server.get_recent_activities(days=14, activity_type="running", limit=10)

        mock_repo.get_activities.assert_called_once()
        call_kwargs = mock_repo.get_activities.call_args[1]
        assert call_kwargs["activity_type"] == "running"
        assert call_kwargs["limit"] == 10

    def test_get_recovery_status(self, mock_repo, mock_aggregator, executor):
        """Test get_recovery_status aggregates metrics."""
        from garmin_sync.mcp import server

        with patch.object(server, "_get_executor", return_value=executor):
            result = server.get_recovery_status()

        assert "hrv" in result
        assert "sleep" in result
        assert "body_battery" in result
        assert "resting_hr" in result
        assert "training_readiness" in result
        assert "last_sync" in result

        assert result["hrv"]["baseline_7d"] == 65
        assert result["hrv"]["last_night"] == 62
        assert result["hrv"]["status"] == "BALANCED"
        assert result["sleep"]["avg_hours"] == 8.0
        assert result["body_battery"]["overnight_recovery"] == 60
        assert result["resting_hr"]["current"] == 48
        assert result["resting_hr"]["trend"] == "falling"

    def test_get_training_load_optimal(self, mock_repo, mock_aggregator, executor):
        """Test training load with optimal A:C ratio."""
        from garmin_sync.mcp import server

        with patch.object(server, "_get_executor", return_value=executor):
            result = server.get_training_load_analysis()

        assert result["acute_load_7d"] == 200
        assert result["chronic_load_28d"] == 220
        assert result["acute_chronic_ratio"] == 0.91
        assert result["risk_assessment"] == "optimal"
        assert "by_activity_type" in result
        assert "running" in result["by_activity_type"]

    def test_get_training_load_high_risk(self, mock_repo, mock_aggregator):
        """Test training load flags high risk."""
        from garmin_sync.mcp import server

        mock_aggregator.get_training_load_trend.return_value = {
            "acute_load_7d": 400,
            "chronic_load_28d": 200,
            "acute_chronic_ratio": 2.0,
            "by_type": {},
        }

        executor = ToolExecutor(mock_repo, mock_aggregator)
        with patch.object(server, "_get_executor", return_value=executor):
            result = server.get_training_load_analysis()

        assert result["risk_assessment"] == "high_risk"

    def test_get_training_load_detraining(self, mock_repo, mock_aggregator):
        """Test training load detects detraining."""
        from garmin_sync.mcp import server

        mock_aggregator.get_training_load_trend.return_value = {
            "acute_load_7d": 50,
            "chronic_load_28d": 200,
            "acute_chronic_ratio": 0.25,
            "by_type": {},
        }

        executor = ToolExecutor(mock_repo, mock_aggregator)
        with patch.object(server, "_get_executor", return_value=executor):
            result = server.get_training_load_analysis()

        assert result["risk_assessment"] == "detraining"

    def test_get_training_load_building(self, mock_repo, mock_aggregator):
        """Test training load building phase."""
        from garmin_sync.mcp import server

        mock_aggregator.get_training_load_trend.return_value = {
            "acute_load_7d": 280,
            "chronic_load_28d": 200,
            "acute_chronic_ratio": 1.4,
            "by_type": {},
        }

        executor = ToolExecutor(mock_repo, mock_aggregator)
        with patch.object(server, "_get_executor", return_value=executor):
            result = server.get_training_load_analysis()

        assert result["risk_assessment"] == "building"

    def test_get_training_load_insufficient_data(self, mock_repo, mock_aggregator):
        """Test training load with no data."""
        from garmin_sync.mcp import server

        mock_aggregator.get_training_load_trend.return_value = {
            "acute_load_7d": None,
            "chronic_load_28d": None,
            "acute_chronic_ratio": None,
            "by_type": {},
        }

        executor = ToolExecutor(mock_repo, mock_aggregator)
        with patch.object(server, "_get_executor", return_value=executor):
            result = server.get_training_load_analysis()

        assert result["risk_assessment"] == "insufficient_data"

    def test_get_strength_training_summary_no_workouts(self, mock_repo, mock_aggregator, executor):
        """Test strength summary with no workouts."""
        from garmin_sync.mcp import server

        mock_repo.get_hevy_workout_count.return_value = 0

        with patch.object(server, "_get_executor", return_value=executor):
            result = server.get_strength_training_summary(days=7)

        assert result["configured"] is True
        assert result["total_sessions"] == 0
        assert "message" in result

    def test_get_strength_training_summary_with_data(self, mock_repo, mock_aggregator, executor):
        """Test strength summary with workout data."""
        from garmin_sync.mcp import server

        mock_repo.get_hevy_workout_count.return_value = 3

        with patch.object(server, "_get_executor", return_value=executor):
            result = server.get_strength_training_summary(days=7)

        assert result["configured"] is True
        assert result["total_sessions"] == 3
        assert result["total_volume_lbs"] == round(5000 * 2.20462)
        assert "by_muscle_group" in result
        assert "chest" in result["by_muscle_group"]
        assert "recent_workouts" in result



class TestMCPServerEdgeCases:
    """Test MCP server edge cases and error handling."""

    @pytest.fixture
    def mock_repo(self):
        """Create mock repository."""
        repo = MagicMock()
        repo.get_latest_sync_timestamp.return_value = None
        repo.get_hevy_workout_count.return_value = 0
        repo.db = MagicMock()
        return repo

    @pytest.fixture
    def mock_aggregator_empty(self):
        """Create mock aggregator returning empty/None data."""
        agg = MagicMock()
        agg.get_hrv_context.return_value = {
            "baseline_7d": None,
            "last_night": None,
            "delta_from_baseline": None,
            "status": None,
            "days_below_baseline": 0,
        }
        agg.get_sleep_consistency.return_value = {
            "avg_sleep_seconds": None,
            "sleep_time_variance_mins": None,
            "avg_deep_pct": None,
            "avg_rem_pct": None,
        }
        agg.get_body_battery_recovery.return_value = {
            "avg_overnight_recovery": None,
            "avg_morning_high": None,
        }
        agg.get_resting_hr_trend.return_value = {
            "current": None,
            "baseline_28d": None,
            "delta": None,
            "trend": None,
        }
        agg.get_training_readiness_latest.return_value = {
            "score": None,
            "level": None,
        }
        agg.get_training_load_trend.return_value = {
            "acute_load_7d": None,
            "chronic_load_28d": None,
            "acute_chronic_ratio": None,
            "week_change_pct": None,
            "by_type": {},
        }
        return agg

    def test_get_recent_activities_empty_result(self, mock_repo, mock_aggregator_empty):
        """Test get_recent_activities with no activities."""
        from garmin_sync.mcp import server

        mock_repo.get_activities.return_value = []

        executor = ToolExecutor(mock_repo, mock_aggregator_empty)
        with patch.object(server, "_get_executor", return_value=executor):
            result = server.get_recent_activities(days=7)

        assert result == []

    def test_get_recovery_status_no_sync(self, mock_repo, mock_aggregator_empty):
        """Test get_recovery_status when no sync has occurred."""
        from garmin_sync.mcp import server

        executor = ToolExecutor(mock_repo, mock_aggregator_empty)
        with patch.object(server, "_get_executor", return_value=executor):
            result = server.get_recovery_status()

        assert result["last_sync"] is None
        assert result["hrv"]["baseline_7d"] is None
        assert result["sleep"]["avg_hours"] is None

    def test_get_recovery_status_handles_zero_sleep(self, mock_repo, mock_aggregator_empty):
        """Test get_recovery_status handles zero sleep seconds."""
        from garmin_sync.mcp import server

        mock_aggregator_empty.get_sleep_consistency.return_value = {
            "avg_sleep_seconds": 0,
        }

        executor = ToolExecutor(mock_repo, mock_aggregator_empty)
        with patch.object(server, "_get_executor", return_value=executor):
            result = server.get_recovery_status()

        # Should not crash, should return None (0 seconds = falsy)
        assert result["sleep"]["avg_hours"] is None

    def test_get_strength_summary_custom_days(self, mock_repo, mock_aggregator_empty):
        """Test get_strength_training_summary with custom days parameter."""
        from garmin_sync.mcp import server

        mock_repo.get_hevy_workout_count.return_value = 0

        executor = ToolExecutor(mock_repo, mock_aggregator_empty)
        with patch.object(server, "_get_executor", return_value=executor):
            result = server.get_strength_training_summary(days=30)

        mock_repo.get_hevy_workout_count.assert_called_once_with(days=30)
        assert "No workouts in last 30 days" in result["message"]

    def test_get_training_load_boundary_ratios(self):
        """Test training load at exact boundary values."""
        from garmin_sync.mcp import server

        mock_repo = MagicMock()
        mock_repo.db = MagicMock()
        mock_agg = MagicMock()

        # Test exactly 0.8 (should be optimal, not detraining)
        mock_agg.get_training_load_trend.return_value = {
            "acute_chronic_ratio": 0.8,
            "by_type": {},
        }
        executor = ToolExecutor(mock_repo, mock_agg)
        with patch.object(server, "_get_executor", return_value=executor):
            result = server.get_training_load_analysis()
        assert result["risk_assessment"] == "optimal"

        # Test exactly 1.3 (should be optimal)
        mock_agg.get_training_load_trend.return_value = {
            "acute_chronic_ratio": 1.3,
            "by_type": {},
        }
        executor = ToolExecutor(mock_repo, mock_agg)
        with patch.object(server, "_get_executor", return_value=executor):
            result = server.get_training_load_analysis()
        assert result["risk_assessment"] == "optimal"

        # Test exactly 1.5 (should be building)
        mock_agg.get_training_load_trend.return_value = {
            "acute_chronic_ratio": 1.5,
            "by_type": {},
        }
        executor = ToolExecutor(mock_repo, mock_agg)
        with patch.object(server, "_get_executor", return_value=executor):
            result = server.get_training_load_analysis()
        assert result["risk_assessment"] == "building"


class TestMCPServerIntegration:
    """Integration tests using real in-memory database."""

    @pytest.fixture
    def db(self):
        """Create in-memory database."""
        db = Database(":memory:")
        db.initialize()
        db.migrate()
        return db

    @pytest.fixture
    def repo(self, db):
        """Create repository with database."""
        return Repository(db)

    def test_get_recent_activities_integration(self, db, repo):
        """Test get_recent_activities with real database."""
        from garmin_sync.mcp import server
        from garmin_sync.reports.aggregators import DataAggregator

        # Insert test activities
        today = date.today()
        activities = [
            Activity(
                activity_id="1",
                activity_name="Morning Run",
                activity_type="running",
                start_time=f"{today.isoformat()}T07:00:00Z",
                duration_seconds=3600,
                distance_meters=10000,
                average_hr=145,
                training_load=75.0,
            ),
            Activity(
                activity_id="2",
                activity_name="Evening Bike",
                activity_type="cycling",
                start_time=f"{today.isoformat()}T18:00:00Z",
                duration_seconds=5400,
                distance_meters=30000,
                average_hr=130,
                training_load=60.0,
            ),
            Activity(
                activity_id="3",
                activity_name="Old Run",
                activity_type="running",
                start_time=f"{(today - timedelta(days=30)).isoformat()}T07:00:00Z",
                duration_seconds=2400,
                distance_meters=5000,
            ),
        ]
        for a in activities:
            repo.upsert_activity(a)

        aggregator = DataAggregator(db)
        executor = ToolExecutor(repo, aggregator)
        with patch.object(server, "_get_executor", return_value=executor):
            # Get last 7 days
            result = server.get_recent_activities(days=7)
            assert len(result) == 2

            # Filter by type
            result = server.get_recent_activities(days=7, activity_type="running")
            assert len(result) == 1
            assert result[0]["name"] == "Morning Run"

            # Get all with longer range
            result = server.get_recent_activities(days=60, limit=10)
            assert len(result) == 3

    def test_get_recent_activities_respects_limit(self, db, repo):
        """Test that limit parameter is respected."""
        from garmin_sync.mcp import server
        from garmin_sync.reports.aggregators import DataAggregator

        today = date.today()
        for i in range(25):
            repo.upsert_activity(Activity(
                activity_id=str(i),
                activity_name=f"Run {i}",
                activity_type="running",
                start_time=f"{today.isoformat()}T{i:02d}:00:00Z",
            ))

        aggregator = DataAggregator(db)
        executor = ToolExecutor(repo, aggregator)
        with patch.object(server, "_get_executor", return_value=executor):
            result = server.get_recent_activities(days=7, limit=10)
            assert len(result) == 10

            result = server.get_recent_activities(days=7, limit=5)
            assert len(result) == 5


class TestMCPLazyInitialization:
    """Test lazy initialization of repository and aggregator."""

    def test_repo_initialized_once(self):
        """Test that repository is only initialized once."""
        from garmin_sync.mcp import server

        # Reset global state
        server._db = None
        server._repo = None
        server._aggregator = None
        server._executor = None

        mock_db = MagicMock()
        mock_repo = MagicMock()
        mock_settings = MagicMock()
        mock_settings.database_path = "/fake/path"

        with patch("garmin_sync.config.get_settings", return_value=mock_settings):
            with patch("garmin_sync.db.database.Database", return_value=mock_db):
                with patch("garmin_sync.db.repository.Repository", return_value=mock_repo):
                    # First call should initialize
                    repo1 = server._get_repo()
                    # Second call should return cached
                    repo2 = server._get_repo()

                    assert repo1 is repo2
                    # Database should only be created once
                    assert mock_db.initialize.call_count == 1

        # Clean up
        server._db = None
        server._repo = None
        server._aggregator = None
        server._executor = None

    def test_aggregator_uses_repo_db(self):
        """Test that aggregator uses the repository's database."""
        from garmin_sync.mcp import server

        # Reset global state
        server._db = None
        server._repo = None
        server._aggregator = None
        server._executor = None

        mock_db = MagicMock()
        mock_repo = MagicMock()
        mock_repo.db = mock_db

        with patch.object(server, "_get_repo", return_value=mock_repo):
            with patch("garmin_sync.reports.aggregators.DataAggregator") as mock_agg_class:
                server._get_aggregator()
                mock_agg_class.assert_called_once_with(mock_db)

        # Clean up
        server._db = None
        server._repo = None
        server._aggregator = None
        server._executor = None


class TestMCPCLI:
    """Test MCP CLI commands."""

    def test_mcp_info_command(self):
        """Test mcp info command outputs correct information."""
        from typer.testing import CliRunner
        from garmin_sync.cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["mcp", "info"])

        assert result.exit_code == 0
        assert "garmin-sync MCP Server" in result.stdout
        assert "get_recent_activities" in result.stdout
        assert "get_recovery_status" in result.stdout
        assert "get_training_load_analysis" in result.stdout
        assert "get_strength_training_summary" in result.stdout
        assert "claude mcp add" in result.stdout

    def test_mcp_serve_imports_correctly(self):
        """Test that mcp serve command can import the server module."""
        # Just verify the import works
        from garmin_sync.mcp.server import main
        assert callable(main)


class TestMCPStrengthSummaryDetails:
    """Test strength training summary details."""

    @pytest.fixture
    def mock_repo(self):
        repo = MagicMock()
        repo.get_hevy_workout_count.return_value = 2
        repo.db = MagicMock()
        return repo

    @pytest.fixture
    def mock_aggregator_strength(self):
        """Mock aggregator with detailed strength data."""
        agg = MagicMock()
        agg.get_strength_volume_summary.return_value = {
            "total_sessions": 2,
            "total_volume_kg": 3000,
            "total_sets": 30,
            "total_reps": 240,
            "by_muscle_group": {
                "chest": {"volume_kg": 1000, "sets": 10},
                "back": {"volume_kg": 1200, "sets": 12},
                "shoulders": {"volume_kg": 800, "sets": 8},
            },
            "recent_workouts": [
                {
                    "date": "2026-03-15",
                    "title": "Push Day",
                    "volume_kg": 1500,
                    "duration_minutes": 60,
                    "exercises": [
                        {"name": "Bench Press", "muscle_group": "chest", "sets": "135×10, 145×8, 155×6"},
                        {"name": "Shoulder Press", "muscle_group": "shoulders", "sets": "80×12, 90×10"},
                    ],
                },
                {
                    "date": "2026-03-13",
                    "title": "Pull Day",
                    "volume_kg": 1500,
                    "duration_minutes": 55,
                    "exercises": [
                        {"name": "Lat Pulldown", "muscle_group": "back", "sets": "100×12, 110×10, 120×8"},
                    ],
                },
            ],
        }
        agg.get_rpe_analysis.return_value = {
            "sessions": [],
            "overall_avg_rpe": None,
            "rpe_coverage_pct": 0.0,
            "overreaching_flag": False,
        }
        return agg

    def test_strength_summary_converts_kg_to_lbs(self, mock_repo, mock_aggregator_strength):
        """Test that volume is correctly converted from kg to lbs."""
        from garmin_sync.mcp import server

        KG_TO_LBS = 2.20462

        executor = ToolExecutor(mock_repo, mock_aggregator_strength)
        with patch.object(server, "_get_executor", return_value=executor):
            result = server.get_strength_training_summary(days=7)

        # Total volume should be converted
        assert result["total_volume_lbs"] == round(3000 * KG_TO_LBS)

        # Muscle group volumes should be converted
        assert result["by_muscle_group"]["chest"]["volume_lbs"] == round(1000 * KG_TO_LBS)
        assert result["by_muscle_group"]["back"]["volume_lbs"] == round(1200 * KG_TO_LBS)

    def test_strength_summary_includes_recent_workouts(self, mock_repo, mock_aggregator_strength):
        """Test that recent workouts are included with details."""
        from garmin_sync.mcp import server

        executor = ToolExecutor(mock_repo, mock_aggregator_strength)
        with patch.object(server, "_get_executor", return_value=executor):
            result = server.get_strength_training_summary(days=7)

        assert len(result["recent_workouts"]) == 2
        assert result["recent_workouts"][0]["title"] == "Push Day"
        assert len(result["recent_workouts"][0]["exercises"]) == 2

    def test_strength_summary_handles_zero_volume(self, mock_repo):
        """Test handling of zero volume (bodyweight exercises)."""
        from garmin_sync.mcp import server

        mock_agg = MagicMock()
        mock_agg.get_strength_volume_summary.return_value = {
            "total_sessions": 1,
            "total_volume_kg": 0,
            "total_sets": 15,
            "by_muscle_group": {
                "core": {"volume_kg": 0, "sets": 15},
            },
            "recent_workouts": [],
        }
        mock_agg.get_rpe_analysis.return_value = {
            "sessions": [],
            "overall_avg_rpe": None,
            "rpe_coverage_pct": 0.0,
            "overreaching_flag": False,
        }

        executor = ToolExecutor(mock_repo, mock_agg)
        with patch.object(server, "_get_executor", return_value=executor):
            result = server.get_strength_training_summary(days=7)

        assert result["total_volume_lbs"] == 0
        assert result["by_muscle_group"]["core"]["volume_lbs"] == 0
        assert result["by_muscle_group"]["core"]["sets"] == 15


class TestMCPDateCalculations:
    """Test date calculations in MCP tools."""

    def test_get_recent_activities_date_calculation(self):
        """Test that date calculation for activities is correct."""
        from garmin_sync.mcp import server

        mock_repo = MagicMock()
        mock_repo.get_activities.return_value = []
        mock_repo.db = MagicMock()
        mock_agg = MagicMock()

        today = date.today()

        executor = ToolExecutor(mock_repo, mock_agg)
        with patch.object(server, "_get_executor", return_value=executor):
            server.get_recent_activities(days=7)

        # Check the start_date passed to get_activities
        call_kwargs = mock_repo.get_activities.call_args[1]
        expected_start = (today - timedelta(days=7)).isoformat()
        assert call_kwargs["start_date"] == expected_start

    def test_get_recent_activities_one_day(self):
        """Test get_recent_activities with days=1."""
        from garmin_sync.mcp import server

        mock_repo = MagicMock()
        mock_repo.get_activities.return_value = []
        mock_repo.db = MagicMock()
        mock_agg = MagicMock()

        today = date.today()

        executor = ToolExecutor(mock_repo, mock_agg)
        with patch.object(server, "_get_executor", return_value=executor):
            server.get_recent_activities(days=1)

        call_kwargs = mock_repo.get_activities.call_args[1]
        expected_start = (today - timedelta(days=1)).isoformat()
        assert call_kwargs["start_date"] == expected_start


class TestMCPPhase2Tools:
    """Test Phase 2 MCP tools."""

    @pytest.fixture
    def mock_repo(self):
        """Create mock repository."""
        repo = MagicMock()
        repo.db = MagicMock()
        repo.get_hevy_workout_details.return_value = [
            {
                "date": "2026-03-15",
                "title": "Push Day",
                "duration_minutes": 60,
                "total_volume_lbs": 12500,
                "exercises": [
                    {"name": "Bench Press", "muscle_group": "chest", "sets": "135×10, 155×8, 175×6"},
                    {"name": "Shoulder Press", "muscle_group": "shoulders", "sets": "80×12, 90×10"},
                ],
            }
        ]
        return repo

    @pytest.fixture
    def mock_aggregator(self):
        """Create mock aggregator for Phase 2 tools."""
        agg = MagicMock()
        # Mock for get_exercise_progression
        agg.get_strength_exercise_progression.return_value = {
            "exercise": "Bench Press",
            "sessions": [
                {"date": "2026-03-15", "max_weight": 80, "est_1rm": 90},
                {"date": "2026-03-10", "max_weight": 77.5, "est_1rm": 87},
            ],
            "current_1rm": 90,
            "progression_pct": 5.0,
        }
        # Mock for get_weekly_comparison
        mock_comparison = MagicMock()
        mock_comparison.current = {
            "activities": 5,
            "duration_hours": 6.5,
            "distance_km": 42.0,
            "calories": 2800,
            "avg_steps": 10000,
            "avg_sleep_hours": 7.2,
            "avg_resting_hr": 48,
        }
        mock_comparison.previous = {
            "activities": 4,
            "duration_hours": 5.5,
            "distance_km": 35.0,
            "calories": 2400,
            "avg_steps": 9000,
            "avg_sleep_hours": 7.0,
            "avg_resting_hr": 50,
        }
        mock_comparison.changes = {
            "activities": 25.0,
            "duration_hours": 18.2,
            "distance_km": 20.0,
            "calories": 16.7,
            "avg_steps": 11.1,
            "avg_sleep_hours": 2.9,
            "avg_resting_hr": -4.0,
        }
        agg.get_weekly_comparison.return_value = mock_comparison
        return agg

    def test_get_exercise_progression_found(self, mock_repo, mock_aggregator):
        """Test exercise progression with data."""
        from garmin_sync.mcp import server

        executor = ToolExecutor(mock_repo, mock_aggregator)
        with patch.object(server, "_get_executor", return_value=executor):
            result = server.get_exercise_progression("Bench Press", days=90)

        assert result["exercise"] == "Bench Press"
        assert result["found"] is True
        assert len(result["sessions"]) == 2
        # 80 kg * 2.20462 = 176.37 -> 176
        assert result["sessions"][0]["max_weight_lbs"] == 176
        # 90 kg * 2.20462 = 198.42 -> 198
        assert result["current_1rm_lbs"] == 198
        assert result["progression_pct"] == 5.0

    def test_get_exercise_progression_not_found(self, mock_repo, mock_aggregator):
        """Test exercise progression with no data."""
        from garmin_sync.mcp import server

        mock_aggregator.get_strength_exercise_progression.return_value = {
            "exercise": "Unknown Exercise",
            "sessions": [],
            "current_1rm": None,
            "progression_pct": None,
        }

        executor = ToolExecutor(mock_repo, mock_aggregator)
        with patch.object(server, "_get_executor", return_value=executor):
            result = server.get_exercise_progression("Unknown Exercise", days=90)

        assert result["exercise"] == "Unknown Exercise"
        assert result["found"] is False
        assert "No data found" in result["message"]

    def test_get_workout_details(self, mock_repo, mock_aggregator):
        """Test workout details returns repository data."""
        from garmin_sync.mcp import server

        executor = ToolExecutor(mock_repo, mock_aggregator)
        with patch.object(server, "_get_executor", return_value=executor):
            result = server.get_workout_details(days=7)

        mock_repo.get_hevy_workout_details.assert_called_once_with(days=7)
        assert len(result) == 1
        assert result[0]["title"] == "Push Day"
        assert len(result[0]["exercises"]) == 2

    def test_get_workout_details_custom_days(self, mock_repo, mock_aggregator):
        """Test workout details with custom days parameter."""
        from garmin_sync.mcp import server

        executor = ToolExecutor(mock_repo, mock_aggregator)
        with patch.object(server, "_get_executor", return_value=executor):
            server.get_workout_details(days=30)

        mock_repo.get_hevy_workout_details.assert_called_once_with(days=30)

    def test_get_weekly_comparison(self, mock_repo, mock_aggregator):
        """Test weekly comparison format."""
        from garmin_sync.mcp import server

        executor = ToolExecutor(mock_repo, mock_aggregator)
        with patch.object(server, "_get_executor", return_value=executor):
            result = server.get_weekly_comparison()

        assert "current_week" in result
        assert "previous_week" in result
        assert "changes_pct" in result

        assert result["current_week"]["activities"] == 5
        assert result["current_week"]["duration_hours"] == 6.5
        assert result["previous_week"]["activities"] == 4
        assert result["changes_pct"]["activities"] == 25.0
        assert result["changes_pct"]["avg_resting_hr"] == -4.0

    def test_sync_garmin_data_success(self, mock_repo, mock_aggregator):
        """Test sync returns success format."""
        from garmin_sync.mcp import server

        mock_sync_result = MagicMock()
        mock_sync_result.records_synced = 5
        mock_sync_result.errors = []

        mock_sync_manager = MagicMock()
        mock_sync_manager.sync_all.return_value = {
            "activities": mock_sync_result,
            "sleep": mock_sync_result,
        }

        executor = ToolExecutor(mock_repo, mock_aggregator)
        with patch.object(server, "_get_executor", return_value=executor):
            with patch("garmin_sync.sync.sync_manager.SyncManager", return_value=mock_sync_manager):
                result = server.sync_garmin_data(days=1)

        assert result["success"] is True
        assert result["synced"]["activities"] == 5
        assert result["synced"]["sleep"] == 5
        assert result["errors"] == []

    def test_sync_garmin_data_with_errors(self, mock_repo, mock_aggregator):
        """Test sync handles partial errors."""
        from garmin_sync.mcp import server

        mock_sync_result_ok = MagicMock()
        mock_sync_result_ok.records_synced = 3
        mock_sync_result_ok.errors = []

        mock_sync_result_err = MagicMock()
        mock_sync_result_err.records_synced = 0
        mock_sync_result_err.errors = ["API rate limit exceeded"]

        mock_sync_manager = MagicMock()
        mock_sync_manager.sync_all.return_value = {
            "activities": mock_sync_result_ok,
            "hrv": mock_sync_result_err,
        }

        executor = ToolExecutor(mock_repo, mock_aggregator)
        with patch.object(server, "_get_executor", return_value=executor):
            with patch("garmin_sync.sync.sync_manager.SyncManager", return_value=mock_sync_manager):
                result = server.sync_garmin_data(days=1)

        assert result["success"] is False
        assert result["synced"]["activities"] == 3
        assert result["synced"]["hrv"] == 0
        assert "API rate limit exceeded" in result["errors"]

    def test_sync_garmin_data_exception(self, mock_repo, mock_aggregator):
        """Test sync handles exceptions gracefully."""
        from garmin_sync.mcp import server

        mock_sync_manager = MagicMock()
        mock_sync_manager.sync_all.side_effect = Exception("Authentication failed")

        executor = ToolExecutor(mock_repo, mock_aggregator)
        with patch.object(server, "_get_executor", return_value=executor):
            with patch("garmin_sync.sync.sync_manager.SyncManager", return_value=mock_sync_manager):
                result = server.sync_garmin_data(days=1)

        assert result["success"] is False
        assert result["synced"] == {}
        assert "Authentication failed" in result["errors"]

    def test_sync_garmin_data_custom_days(self, mock_repo, mock_aggregator):
        """Test sync with custom days parameter."""
        from garmin_sync.mcp import server

        mock_sync_result = MagicMock()
        mock_sync_result.records_synced = 10
        mock_sync_result.errors = []

        mock_sync_manager = MagicMock()
        mock_sync_manager.sync_all.return_value = {"activities": mock_sync_result}

        executor = ToolExecutor(mock_repo, mock_aggregator)
        with patch.object(server, "_get_executor", return_value=executor):
            with patch("garmin_sync.sync.sync_manager.SyncManager", return_value=mock_sync_manager):
                server.sync_garmin_data(days=7)

        mock_sync_manager.sync_all.assert_called_once_with(days=7, force=False, detailed=False)

    def test_get_longitudinal_summary_registered(self, mock_repo, mock_aggregator):
        """Smoke: MCP wrapper delegates to executor.get_longitudinal_summary."""
        from garmin_sync.mcp import server

        mock_aggregator.get_aerobic_efficiency_by_period.return_value = {
            "granularity": "year", "periods": [],
        }
        mock_aggregator.get_yearly_health_baselines.return_value = {"years": []}
        mock_aggregator.get_volume_by_period.return_value = {
            "granularity": "year", "periods": [],
        }
        mock_aggregator.get_hr_drift_by_period.return_value = {"periods": []}

        cursor = MagicMock()
        cursor.fetchone.return_value = {"d": "2022-01-01"}
        mock_repo.db.connection.cursor.return_value = cursor

        executor = ToolExecutor(mock_repo, mock_aggregator)
        with patch.object(server, "_get_executor", return_value=executor):
            result = server.get_longitudinal_summary()

        assert "aerobic_efficiency" in result
        assert "health_baselines" in result
        assert "volume" in result
        assert "hr_drift" in result
        assert result["range"]["start_year"] == 2022


class TestMCPPhase2EdgeCases:
    """Test edge cases for Phase 2 MCP tools."""

    @pytest.fixture
    def mock_repo(self):
        """Create mock repository."""
        repo = MagicMock()
        repo.db = MagicMock()
        repo.get_hevy_workout_details.return_value = []
        return repo

    def test_get_exercise_progression_handles_none_est_1rm(self, mock_repo):
        """Test exercise progression handles None est_1rm."""
        from garmin_sync.mcp import server

        mock_agg = MagicMock()
        mock_agg.get_strength_exercise_progression.return_value = {
            "exercise": "Deadlift",
            "sessions": [
                {"date": "2026-03-15", "max_weight": 100, "est_1rm": None},
            ],
            "current_1rm": None,
            "progression_pct": None,
        }

        executor = ToolExecutor(mock_repo, mock_agg)
        with patch.object(server, "_get_executor", return_value=executor):
            result = server.get_exercise_progression("Deadlift")

        assert result["found"] is True
        assert result["sessions"][0]["est_1rm_lbs"] is None
        assert result["current_1rm_lbs"] is None
        assert result["progression_pct"] is None

    def test_get_workout_details_empty(self, mock_repo):
        """Test workout details with no workouts."""
        from garmin_sync.mcp import server

        mock_agg = MagicMock()

        executor = ToolExecutor(mock_repo, mock_agg)
        with patch.object(server, "_get_executor", return_value=executor):
            result = server.get_workout_details(days=7)

        assert result == []

    def test_get_weekly_comparison_with_none_values(self, mock_repo):
        """Test weekly comparison handles None values."""
        from garmin_sync.mcp import server

        mock_agg = MagicMock()
        mock_comparison = MagicMock()
        mock_comparison.current = {
            "activities": 0,
            "duration_hours": 0,
            "distance_km": None,
            "calories": None,
            "avg_steps": None,
            "avg_sleep_hours": None,
            "avg_resting_hr": None,
        }
        mock_comparison.previous = {
            "activities": 0,
            "duration_hours": 0,
            "distance_km": None,
            "calories": None,
            "avg_steps": None,
            "avg_sleep_hours": None,
            "avg_resting_hr": None,
        }
        mock_comparison.changes = {
            "activities": None,
            "duration_hours": None,
            "distance_km": None,
            "calories": None,
            "avg_steps": None,
            "avg_sleep_hours": None,
            "avg_resting_hr": None,
        }
        mock_agg.get_weekly_comparison.return_value = mock_comparison

        executor = ToolExecutor(mock_repo, mock_agg)
        with patch.object(server, "_get_executor", return_value=executor):
            result = server.get_weekly_comparison()

        assert result["current_week"]["activities"] == 0
        assert result["changes_pct"]["activities"] is None

    def test_sync_errors_limited_to_five(self, mock_repo):
        """Test that sync limits errors to 5."""
        from garmin_sync.mcp import server

        mock_agg = MagicMock()
        mock_sync_result = MagicMock()
        mock_sync_result.records_synced = 0
        mock_sync_result.errors = [f"Error {i}" for i in range(10)]

        mock_sync_manager = MagicMock()
        mock_sync_manager.sync_all.return_value = {"activities": mock_sync_result}

        executor = ToolExecutor(mock_repo, mock_agg)
        with patch.object(server, "_get_executor", return_value=executor):
            with patch("garmin_sync.sync.sync_manager.SyncManager", return_value=mock_sync_manager):
                result = server.sync_garmin_data(days=1)

        assert len(result["errors"]) == 5


class TestAnomalyAndPeriodizationTools:
    """Test get_anomaly_report and get_periodization_status executor methods."""

    @pytest.fixture
    def mock_repo(self):
        repo = MagicMock()
        repo.db = MagicMock()
        return repo

    @pytest.fixture
    def mock_aggregator(self):
        return MagicMock()

    @pytest.fixture
    def executor(self, mock_repo, mock_aggregator):
        return ToolExecutor(mock_repo, mock_aggregator)

    @patch("garmin_sync.reports.anomaly_detector.AnomalyDetector")
    def test_get_anomaly_report_no_anomalies(self, mock_detector_cls, executor):
        """Test anomaly report with no anomalies."""
        mock_detector_cls.return_value.detect_anomalies.return_value = []
        result = executor.get_anomaly_report()
        assert result["total"] == 0
        assert result["anomalies"] == []
        assert result["summary"]["critical"] == 0

    @patch("garmin_sync.reports.anomaly_detector.AnomalyDetector")
    def test_get_anomaly_report_with_anomalies(self, mock_detector_cls, executor):
        """Test anomaly report with mixed severity anomalies."""
        mock_detector_cls.return_value.detect_anomalies.return_value = [
            {"check": "training_overload", "severity": "critical", "message": "A:C > 1.5", "data": {}},
            {"check": "hrv_crash", "severity": "warning", "message": "HRV dropped", "data": {}},
            {"check": "detraining", "severity": "info", "message": "A:C < 0.8", "data": {}},
        ]
        result = executor.get_anomaly_report()
        assert result["total"] == 3
        assert result["summary"]["critical"] == 1
        assert result["summary"]["warning"] == 1
        assert result["summary"]["info"] == 1

    @patch("garmin_sync.reports.periodization.PeriodizationAnalyzer")
    def test_get_periodization_status(self, mock_analyzer_cls, executor):
        """Test periodization status returns summary."""
        mock_analyzer_cls.return_value.get_periodization_summary.return_value = {
            "phase": {"phase": "build", "description": "Progressive overload"},
            "readiness": {"score": 75, "signal": "green", "components": {}},
            "deload": {"recommended": False, "reason": None},
        }
        result = executor.get_periodization_status()
        assert result["phase"]["phase"] == "build"
        assert result["readiness"]["score"] == 75
        assert result["deload"]["recommended"] is False

    @patch("garmin_sync.reports.anomaly_detector.AnomalyDetector")
    def test_recovery_status_includes_anomalies(self, mock_detector_cls, mock_repo, mock_aggregator):
        """Test that get_recovery_status enriches with anomalies."""
        mock_aggregator.get_hrv_context.return_value = {"baseline_7d": 65, "last_night": 62, "delta_from_baseline": -4.6, "status": "BALANCED", "days_below_baseline": 1}
        mock_aggregator.get_sleep_consistency.return_value = {"avg_sleep_seconds": 28800, "sleep_time_variance_mins": 30, "avg_deep_pct": 18.5, "avg_rem_pct": 22.0}
        mock_aggregator.get_body_battery_recovery.return_value = {"avg_overnight_recovery": 60, "avg_morning_high": 85}
        mock_aggregator.get_resting_hr_trend.return_value = {"current": 48, "baseline_28d": 50, "delta": -2, "trend": "falling"}
        mock_aggregator.get_training_readiness_latest.return_value = {"score": 70, "level": "Good"}
        mock_aggregator.get_sleep_respiration_trends.return_value = {}
        mock_aggregator.get_allday_respiration_spo2.return_value = {}
        mock_aggregator.get_stress_recovery_correlation.return_value = {}
        mock_aggregator.get_sleep_performance_correlation.return_value = {}
        mock_repo.get_latest_sync_timestamp.return_value = "2026-05-23T10:00:00Z"

        mock_detector_cls.return_value.detect_anomalies.return_value = [
            {"check": "hrv_crash", "severity": "warning", "message": "HRV dropped", "data": {}},
        ]

        executor = ToolExecutor(mock_repo, mock_aggregator)
        result = executor.get_recovery_status()
        assert "anomalies" in result
        assert len(result["anomalies"]) == 1

    @patch("garmin_sync.reports.anomaly_detector.AnomalyDetector")
    def test_recovery_status_no_anomalies_key_when_empty(self, mock_detector_cls, mock_repo, mock_aggregator):
        """Test that get_recovery_status omits anomalies key when no anomalies."""
        mock_aggregator.get_hrv_context.return_value = {"baseline_7d": 65, "last_night": 62, "delta_from_baseline": -4.6, "status": "BALANCED", "days_below_baseline": 1}
        mock_aggregator.get_sleep_consistency.return_value = {"avg_sleep_seconds": 28800}
        mock_aggregator.get_body_battery_recovery.return_value = {"avg_overnight_recovery": 60, "avg_morning_high": 85}
        mock_aggregator.get_resting_hr_trend.return_value = {"current": 48, "baseline_28d": 50, "delta": -2, "trend": "falling"}
        mock_aggregator.get_training_readiness_latest.return_value = {"score": 70}
        mock_aggregator.get_sleep_respiration_trends.return_value = {}
        mock_aggregator.get_allday_respiration_spo2.return_value = {}
        mock_aggregator.get_stress_recovery_correlation.return_value = {}
        mock_aggregator.get_sleep_performance_correlation.return_value = {}
        mock_repo.get_latest_sync_timestamp.return_value = "2026-05-23T10:00:00Z"

        mock_detector_cls.return_value.detect_anomalies.return_value = []

        executor = ToolExecutor(mock_repo, mock_aggregator)
        result = executor.get_recovery_status()
        assert "anomalies" not in result

    def test_execute_dispatches_anomaly_report(self, executor):
        """Test that execute() dispatches to get_anomaly_report."""
        with patch.object(executor, "get_anomaly_report", return_value={"total": 0}) as mock:
            result = executor.execute("get_anomaly_report", {})
            mock.assert_called_once()
            assert result["total"] == 0

    def test_execute_dispatches_periodization_status(self, executor):
        """Test that execute() dispatches to get_periodization_status."""
        with patch.object(executor, "get_periodization_status", return_value={"phase": {}}) as mock:
            result = executor.execute("get_periodization_status", {})
            mock.assert_called_once()


class TestMCPCLIPhase2:
    """Test MCP CLI commands for Phase 2."""

    def test_mcp_info_shows_all_tools(self):
        """Test mcp info command outputs all 8 tools."""
        from typer.testing import CliRunner
        from garmin_sync.cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["mcp", "info"])

        assert result.exit_code == 0
        # Phase 1 tools
        assert "get_recent_activities" in result.stdout
        assert "get_recovery_status" in result.stdout
        assert "get_training_load_analysis" in result.stdout
        assert "get_strength_training_summary" in result.stdout
        # Phase 2 tools
        assert "get_exercise_progression" in result.stdout
        assert "get_workout_details" in result.stdout
        assert "get_weekly_comparison" in result.stdout
        assert "sync_garmin_data" in result.stdout


class TestMCPErrorHandling:
    """Test structured error responses from MCP tools."""

    def test_mcp_tool_returns_structured_error_on_value_error(self):
        """Test that ValueError produces DATA_MISSING error type."""
        from garmin_sync.mcp import server

        mock_executor = MagicMock()
        mock_executor.get_recovery_status.side_effect = ValueError(
            "No HRV data found"
        )

        with patch.object(server, "_get_executor", return_value=mock_executor):
            result = server.get_recovery_status()

        assert result["error"] is True
        assert result["error_type"] == "DATA_MISSING"
        assert "No HRV data" in result["message"]

    def test_mcp_tool_returns_structured_error_on_runtime_error(self):
        """Test that RuntimeError produces INTERNAL error type."""
        from garmin_sync.mcp import server

        mock_executor = MagicMock()
        mock_executor.get_recovery_status.side_effect = RuntimeError("unexpected")

        with patch.object(server, "_get_executor", return_value=mock_executor):
            result = server.get_recovery_status()

        assert result["error"] is True
        assert result["error_type"] == "INTERNAL"

    def test_mcp_error_classification_sync_needed(self):
        """Test that sqlite3.OperationalError classifies as SYNC_NEEDED."""
        from garmin_sync.mcp.server import _classify_mcp_error

        error_type, message = _classify_mcp_error(
            sqlite3.OperationalError("no such table: sleep_daily")
        )
        assert error_type == "SYNC_NEEDED"
        assert "sleep_daily" in message

    def test_mcp_error_classification_file_vs_network(self):
        """File/permission errors (OSError subclasses) must NOT be reported as
        NETWORK_ERROR — that would tell the model to retry the connection for a
        filesystem/setup problem. Real connection errors still map to network."""
        from garmin_sync.mcp.server import _classify_mcp_error

        assert _classify_mcp_error(FileNotFoundError("missing"))[0] == "INTERNAL"
        assert _classify_mcp_error(PermissionError("denied"))[0] == "INTERNAL"
        assert _classify_mcp_error(ConnectionError("reset"))[0] == "NETWORK_ERROR"
        assert _classify_mcp_error(TimeoutError("slow"))[0] == "NETWORK_ERROR"
