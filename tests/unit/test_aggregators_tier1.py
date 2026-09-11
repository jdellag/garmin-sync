"""Tests for Tier 1 analytics — cadence, VO2 max, elevation, sleep
respiration, body battery patterns, training effect balance."""

from datetime import date, timedelta

import pytest

from garmin_sync.db.database import Database
from garmin_sync.db.models import (
    Activity,
    BodyBatteryDaily,
    SleepDaily,
    TrainingReadiness,
)
from garmin_sync.db.repository import Repository
from garmin_sync.reports.aggregators import DataAggregator


# ------------------------------------------------------------------
# Shared fixtures
# ------------------------------------------------------------------


@pytest.fixture
def db():
    """In-memory database with schema."""
    db = Database(":memory:")
    db.initialize()
    db.migrate()
    return db


@pytest.fixture
def repo(db):
    return Repository(db)


@pytest.fixture
def agg(db):
    return DataAggregator(db)


# ------------------------------------------------------------------
# Cadence analysis
# ------------------------------------------------------------------


class TestCadenceAnalysis:
    @pytest.fixture(autouse=True)
    def _seed(self, repo):
        activities = [
            Activity(
                activity_id="r1",
                activity_type="running",
                start_time="2026-05-12T07:00:00Z",
                duration_seconds=3600,
                distance_meters=10000,
                avg_cadence=172.0,
                max_cadence=184.0,
            ),
            Activity(
                activity_id="r2",
                activity_type="running",
                start_time="2026-05-14T07:00:00Z",
                duration_seconds=1800,
                distance_meters=5000,
                avg_cadence=176.0,
                max_cadence=190.0,
            ),
            Activity(
                activity_id="c1",
                activity_type="cycling",
                start_time="2026-05-15T08:00:00Z",
                duration_seconds=5400,
                distance_meters=30000,
                avg_cadence=85.0,
                max_cadence=95.0,
            ),
            # Activity with no cadence data
            Activity(
                activity_id="r3",
                activity_type="running",
                start_time="2026-05-16T07:00:00Z",
                duration_seconds=2400,
                distance_meters=7000,
            ),
        ]
        for a in activities:
            repo.upsert_activity(a)

    def test_basic_averages(self, agg):
        result = agg.get_cadence_analysis(date(2026, 5, 10), date(2026, 5, 20))
        # Three activities have cadence data
        assert result["total_activities_with_cadence"] == 3
        # Overall average: (172 + 176 + 85) / 3
        assert result["avg_cadence"] == pytest.approx(144.3, abs=0.1)
        # Overall max
        assert result["max_cadence"] == 190.0

    def test_by_activity_type(self, agg):
        result = agg.get_cadence_analysis(date(2026, 5, 10), date(2026, 5, 20))
        assert "running" in result["by_activity_type"]
        assert "cycling" in result["by_activity_type"]
        running = result["by_activity_type"]["running"]
        assert running["count"] == 2
        assert running["avg"] == pytest.approx(174.0, abs=0.1)
        assert running["max"] == 190.0

    def test_weekly_trend(self, agg):
        result = agg.get_cadence_analysis(date(2026, 5, 10), date(2026, 5, 20))
        assert len(result["weekly_trend"]) >= 1
        for entry in result["weekly_trend"]:
            assert "week" in entry
            assert "avg_cadence" in entry
            assert "count" in entry

    def test_empty_data(self, agg):
        result = agg.get_cadence_analysis(date(2020, 1, 1), date(2020, 1, 7))
        assert result["avg_cadence"] is None
        assert result["max_cadence"] is None
        assert result["total_activities_with_cadence"] == 0


# ------------------------------------------------------------------
# VO2 max trend
# ------------------------------------------------------------------


class TestVo2MaxTrend:
    @pytest.fixture(autouse=True)
    def _seed(self, repo):
        activities = [
            Activity(
                activity_id="v1",
                activity_type="running",
                start_time="2026-04-20T07:00:00Z",
                duration_seconds=3600,
                distance_meters=10000,
                vo2_max=46.0,
            ),
            Activity(
                activity_id="v2",
                activity_type="running",
                start_time="2026-05-05T07:00:00Z",
                duration_seconds=3600,
                distance_meters=10500,
                vo2_max=47.0,
            ),
            Activity(
                activity_id="v3",
                activity_type="running",
                start_time="2026-05-18T07:00:00Z",
                duration_seconds=3600,
                distance_meters=11000,
                vo2_max=48.5,
            ),
        ]
        for a in activities:
            repo.upsert_activity(a)

    def test_improving_trend(self, agg):
        result = agg.get_vo2_max_trend(date(2026, 4, 1), date(2026, 5, 20))
        assert result["current"] == 48.5
        assert result["period_start"] == 46.0
        assert result["delta"] == pytest.approx(2.5, abs=0.1)
        assert result["trend"] == "improving"
        assert result["data_points"] == 3

    def test_stable_trend(self, agg):
        # Narrow range with only one data point
        result = agg.get_vo2_max_trend(date(2026, 5, 18), date(2026, 5, 20))
        assert result["current"] == 48.5
        assert result["delta"] == pytest.approx(0.0, abs=0.1)
        assert result["trend"] == "stable"

    def test_values_list(self, agg):
        result = agg.get_vo2_max_trend(date(2026, 4, 1), date(2026, 5, 20))
        assert len(result["values"]) == 3
        assert result["values"][0]["vo2_max"] == 46.0
        assert result["values"][-1]["vo2_max"] == 48.5

    def test_empty_data(self, agg):
        result = agg.get_vo2_max_trend(date(2020, 1, 1), date(2020, 1, 7))
        assert result["current"] is None
        assert result["trend"] is None
        assert result["data_points"] == 0


# ------------------------------------------------------------------
# Elevation summary
# ------------------------------------------------------------------


class TestElevationSummary:
    @pytest.fixture(autouse=True)
    def _seed(self, repo):
        activities = [
            Activity(
                activity_id="e1",
                activity_type="running",
                start_time="2026-05-12T07:00:00Z",
                duration_seconds=3600,
                distance_meters=10000,
                elevation_gain_meters=200.0,
                elevation_loss_meters=180.0,
            ),
            Activity(
                activity_id="e2",
                activity_type="trail_running",
                start_time="2026-05-14T07:00:00Z",
                duration_seconds=7200,
                distance_meters=15000,
                elevation_gain_meters=600.0,
                elevation_loss_meters=590.0,
            ),
            Activity(
                activity_id="e3",
                activity_type="cycling",
                start_time="2026-05-15T08:00:00Z",
                duration_seconds=5400,
                distance_meters=30000,
                elevation_gain_meters=400.0,
                elevation_loss_meters=380.0,
            ),
        ]
        for a in activities:
            repo.upsert_activity(a)

    def test_totals(self, agg):
        result = agg.get_elevation_summary(date(2026, 5, 10), date(2026, 5, 20))
        assert result["total_gain_meters"] == pytest.approx(1200.0, abs=0.1)
        assert result["total_loss_meters"] == pytest.approx(1150.0, abs=0.1)
        assert result["total_activities"] == 3

    def test_avg_gain_per_activity(self, agg):
        result = agg.get_elevation_summary(date(2026, 5, 10), date(2026, 5, 20))
        assert result["avg_gain_per_activity"] == pytest.approx(400.0, abs=0.1)

    def test_vert_per_hour(self, agg):
        result = agg.get_elevation_summary(date(2026, 5, 10), date(2026, 5, 20))
        # 1200m gain / (16200s / 3600) = 1200 / 4.5 = 266.7 m/h
        total_hours = (3600 + 7200 + 5400) / 3600
        expected = 1200.0 / total_hours
        assert result["vert_per_hour"] == pytest.approx(expected, abs=0.5)

    def test_by_activity_type(self, agg):
        result = agg.get_elevation_summary(date(2026, 5, 10), date(2026, 5, 20))
        assert "running" in result["by_activity_type"]
        assert "cycling" in result["by_activity_type"]
        assert result["by_activity_type"]["running"]["gain"] == pytest.approx(200.0)
        assert result["by_activity_type"]["cycling"]["count"] == 1

    def test_empty_data(self, agg):
        result = agg.get_elevation_summary(date(2020, 1, 1), date(2020, 1, 7))
        assert result["total_gain_meters"] is None
        assert result["total_activities"] == 0


# ------------------------------------------------------------------
# Sleep respiration trends
# ------------------------------------------------------------------


class TestSleepRespirationTrends:
    @pytest.fixture(autouse=True)
    def _seed(self, repo):
        # 7 days of sleep data with rising respiration
        for i in range(7):
            repo.upsert_sleep(SleepDaily(
                date=f"2026-05-{12 + i:02d}",
                total_sleep_seconds=28800,
                avg_respiration=14.0 + i * 0.2,   # 14.0 → 15.2
                avg_spo2=95.0 - i * 0.1,           # 95.0 → 94.4
            ))

    def test_averages(self, agg):
        result = agg.get_sleep_respiration_trends(date(2026, 5, 12), date(2026, 5, 18))
        assert result["avg_respiration"] is not None
        assert result["avg_spo2"] is not None
        assert result["data_points"] == 7

    def test_min_spo2(self, agg):
        result = agg.get_sleep_respiration_trends(date(2026, 5, 12), date(2026, 5, 18))
        assert result["min_spo2"] == pytest.approx(94.4, abs=0.1)

    def test_rising_trend(self, agg):
        result = agg.get_sleep_respiration_trends(date(2026, 5, 12), date(2026, 5, 18))
        assert result["respiration_trend"] == "rising"

    def test_daily_values(self, agg):
        result = agg.get_sleep_respiration_trends(date(2026, 5, 12), date(2026, 5, 18))
        assert len(result["daily_values"]) == 7
        assert result["daily_values"][0]["date"] == "2026-05-12"

    def test_empty_data(self, agg):
        result = agg.get_sleep_respiration_trends(date(2020, 1, 1), date(2020, 1, 7))
        assert result["avg_respiration"] is None
        assert result["avg_spo2"] is None
        assert result["data_points"] == 0


# ------------------------------------------------------------------
# Body battery enrichment (weekday/weekend split)
# ------------------------------------------------------------------


class TestBodyBatteryEnriched:
    @pytest.fixture(autouse=True)
    def _seed(self, repo):
        # Mon 2026-05-11 through Sun 2026-05-17
        days = [
            # Mon-Fri (weekdays)
            ("2026-05-11", 30, 80, 40, 35, 50, 45),  # Mon
            ("2026-05-12", 35, 85, 45, 38, 55, 47),  # Tue
            ("2026-05-13", 32, 82, 42, 36, 52, 46),  # Wed
            ("2026-05-14", 28, 78, 38, 32, 48, 42),  # Thu
            ("2026-05-15", 33, 83, 43, 37, 53, 46),  # Fri
            # Sat-Sun (weekends)
            ("2026-05-16", 40, 90, 50, 42, 60, 52),  # Sat
            ("2026-05-17", 42, 92, 52, 44, 62, 54),  # Sun
        ]
        for dt, start, mx, mn, end, charged, drained in days:
            repo.upsert_body_battery(BodyBatteryDaily(
                date=dt,
                start_level=start,
                max_level=mx,
                min_level=mn,
                end_level=end,
                charged=charged,
                drained=drained,
            ))

    def test_weekday_avg_recovery(self, agg):
        result = agg.get_body_battery_recovery(date(2026, 5, 11), date(2026, 5, 17))
        assert result["weekday_avg_recovery"] is not None
        # Weekday recoveries: (80-30), (85-35), (82-32), (78-28), (83-33)
        # = 50, 50, 50, 50, 50 → avg = 50
        assert result["weekday_avg_recovery"] == 50

    def test_weekend_avg_recovery(self, agg):
        result = agg.get_body_battery_recovery(date(2026, 5, 11), date(2026, 5, 17))
        assert result["weekend_avg_recovery"] is not None
        # Weekend recoveries: (90-40), (92-42) = 50, 50 → avg = 50
        assert result["weekend_avg_recovery"] == 50

    def test_charged_drained_fields(self, agg):
        result = agg.get_body_battery_recovery(date(2026, 5, 11), date(2026, 5, 17))
        assert result["avg_charged"] is not None
        assert result["avg_drained"] is not None
        assert result["avg_start_level"] is not None
        assert result["avg_end_level"] is not None

    def test_existing_fields_unchanged(self, agg):
        result = agg.get_body_battery_recovery(date(2026, 5, 11), date(2026, 5, 17))
        assert result["avg_overnight_recovery"] is not None
        assert result["avg_morning_high"] is not None
        assert result["avg_evening_low"] is not None
        assert len(result["daily_values"]) == 7


# ------------------------------------------------------------------
# Training load — training effect enrichment
# ------------------------------------------------------------------


class TestTrainingEffectEnrichment:
    @pytest.fixture(autouse=True)
    def _seed(self, repo):
        today = date(2026, 5, 20)
        activities = [
            Activity(
                activity_id="te1",
                activity_type="running",
                start_time="2026-05-18T07:00:00Z",
                duration_seconds=3600,
                distance_meters=10000,
                training_load=75.0,
                training_effect_aerobic=3.5,
                training_effect_anaerobic=1.2,
            ),
            Activity(
                activity_id="te2",
                activity_type="running",
                start_time="2026-05-19T07:00:00Z",
                duration_seconds=2700,
                distance_meters=8000,
                training_load=55.0,
                training_effect_aerobic=2.8,
                training_effect_anaerobic=1.5,
            ),
            Activity(
                activity_id="te3",
                activity_type="cycling",
                start_time="2026-05-20T08:00:00Z",
                duration_seconds=5400,
                distance_meters=30000,
                training_load=60.0,
                training_effect_aerobic=3.0,
                training_effect_anaerobic=0.8,
            ),
        ]
        for a in activities:
            repo.upsert_activity(a)

    def test_overall_effect_averages(self, agg):
        result = agg.get_training_load_trend(date(2026, 5, 20))
        # avg aerobic: (3.5 + 2.8 + 3.0) / 3 = 3.1
        assert result["avg_training_effect_aerobic"] == pytest.approx(3.1, abs=0.1)
        # avg anaerobic: (1.2 + 1.5 + 0.8) / 3 = 1.17
        assert result["avg_training_effect_anaerobic"] == pytest.approx(1.2, abs=0.1)

    def test_balance_classification_aerobic_dominant(self, agg):
        result = agg.get_training_load_trend(date(2026, 5, 20))
        # 3.1 - 1.17 = 1.93 > 0.5 → aerobic_dominant
        assert result["training_effect_balance"] == "aerobic_dominant"

    def test_existing_fields_unchanged(self, agg):
        result = agg.get_training_load_trend(date(2026, 5, 20))
        assert result["acute_load_7d"] is not None
        assert result["by_type"] is not None


# ------------------------------------------------------------------
# Training readiness — weakest component (via executor)
# ------------------------------------------------------------------


class TestTrainingReadinessWeakest:
    @pytest.fixture(autouse=True)
    def _seed(self, repo):
        repo.upsert_training_readiness(TrainingReadiness(
            date="2026-05-20",
            score=65,
            level="MODERATE",
            sleep_score=70,
            recovery_score=80,
            hrv_score=55,
            stress_history_score=60,
            training_load_balance_score=75,
            feedback_phrase="Take it easy",
        ))

    def test_weakest_component_identified(self, repo, agg):
        from garmin_sync.tools.executor import ToolExecutor

        executor = ToolExecutor(repo, agg)
        result = executor.get_recovery_status()
        readiness = result["training_readiness"]
        assert readiness["weakest_component"] == "hrv_score"

    def test_recovery_includes_respiration_fields(self, repo, agg):
        from garmin_sync.tools.executor import ToolExecutor

        executor = ToolExecutor(repo, agg)
        result = executor.get_recovery_status()
        # Fields present even if None (no sleep data seeded here)
        assert "avg_respiration" in result["sleep"]
        assert "avg_spo2" in result["sleep"]

    def test_recovery_includes_battery_patterns(self, repo, agg):
        from garmin_sync.tools.executor import ToolExecutor

        executor = ToolExecutor(repo, agg)
        result = executor.get_recovery_status()
        assert "weekday_avg_recovery" in result["body_battery"]
        assert "weekend_avg_recovery" in result["body_battery"]


# ------------------------------------------------------------------
# Training load analysis — enriched tool output
# ------------------------------------------------------------------


class TestTrainingLoadAnalysisEnriched:
    @pytest.fixture(autouse=True)
    def _seed(self, repo):
        activities = [
            Activity(
                activity_id="tla1",
                activity_type="running",
                start_time="2026-05-18T07:00:00Z",
                duration_seconds=3600,
                distance_meters=10000,
                training_load=70.0,
                training_effect_aerobic=3.2,
                training_effect_anaerobic=1.0,
            ),
        ]
        for a in activities:
            repo.upsert_activity(a)

    def test_includes_effect_fields(self, repo, agg):
        from garmin_sync.tools.executor import ToolExecutor

        executor = ToolExecutor(repo, agg)
        result = executor.get_training_load_analysis()
        assert "avg_training_effect_aerobic" in result
        assert "avg_training_effect_anaerobic" in result
        assert "training_effect_balance" in result


# ------------------------------------------------------------------
# Cardio performance tool (new)
# ------------------------------------------------------------------


class TestCardioPerformanceTool:
    @pytest.fixture(autouse=True)
    def _seed(self, repo):
        # get_cardio_performance uses a rolling window ending today, so the
        # seeded activity must be date-relative or the test rots over time.
        recent = (date.today() - timedelta(days=3)).isoformat()
        activities = [
            Activity(
                activity_id="cp1",
                activity_type="running",
                start_time=f"{recent}T07:00:00Z",
                duration_seconds=3600,
                distance_meters=10000,
                avg_cadence=174.0,
                max_cadence=186.0,
                vo2_max=48.0,
                elevation_gain_meters=150.0,
                elevation_loss_meters=140.0,
                training_load=70.0,
                training_effect_aerobic=3.0,
                training_effect_anaerobic=1.2,
            ),
        ]
        for a in activities:
            repo.upsert_activity(a)

    def test_returns_all_sections(self, repo, agg):
        from garmin_sync.tools.executor import ToolExecutor

        executor = ToolExecutor(repo, agg)
        result = executor.get_cardio_performance(days=28)
        assert "cadence" in result
        assert "vo2_max" in result
        assert "elevation" in result
        assert "training_effect" in result

    def test_cadence_section(self, repo, agg):
        from garmin_sync.tools.executor import ToolExecutor

        executor = ToolExecutor(repo, agg)
        result = executor.get_cardio_performance(days=28)
        assert result["cadence"]["avg"] == pytest.approx(174.0, abs=0.1)
        assert result["cadence"]["total_activities"] == 1

    def test_vo2_section(self, repo, agg):
        from garmin_sync.tools.executor import ToolExecutor

        executor = ToolExecutor(repo, agg)
        result = executor.get_cardio_performance(days=28)
        assert result["vo2_max"]["current"] == 48.0

    def test_elevation_section(self, repo, agg):
        from garmin_sync.tools.executor import ToolExecutor

        executor = ToolExecutor(repo, agg)
        result = executor.get_cardio_performance(days=28)
        assert result["elevation"]["total_gain_meters"] == pytest.approx(150.0)

    def test_execute_dispatch(self, repo, agg):
        from garmin_sync.tools.executor import ToolExecutor

        executor = ToolExecutor(repo, agg)
        result = executor.execute("get_cardio_performance", {"days": 28})
        assert "cadence" in result
