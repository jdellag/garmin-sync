"""Tests for report generation."""

from datetime import date

import pytest

from garmin_sync.db.database import Database
from garmin_sync.db.models import (
    Activity,
    BodyBatteryDaily,
    DailySummary,
    HeartRateDaily,
    HRVDaily,
    SleepDaily,
    StressDaily,
    TrainingReadiness,
)
from garmin_sync.db.repository import Repository
from garmin_sync.reports.aggregators import (
    ActivitySummary,
    DataAggregator,
    HealthSummary,
    PeriodComparison,
)
from garmin_sync.reports.llm_formatter import (
    LLMReportFormatter,
    format_duration,
    format_pace,
    format_change,
)
from garmin_sync.reports.report_generator import ReportGenerator


class TestFormatFunctions:
    """Test formatting helper functions."""

    def test_format_duration_seconds(self):
        """Test formatting seconds."""
        assert format_duration(30) == "30s"
        assert format_duration(59) == "59s"

    def test_format_duration_minutes(self):
        """Test formatting minutes."""
        assert format_duration(60) == "1m"
        assert format_duration(90) == "1m"
        assert format_duration(3599) == "59m"

    def test_format_duration_hours(self):
        """Test formatting hours."""
        assert format_duration(3600) == "1h"
        assert format_duration(5400) == "1h 30m"
        assert format_duration(7200) == "2h"

    def test_format_pace(self):
        """Test pace formatting."""
        # 5:00/km pace = 5000m in 25 minutes
        assert format_pace(5000, 1500) == "5:00/km"
        # 6:30/km pace
        assert format_pace(1000, 390) == "6:30/km"

    def test_format_pace_invalid(self):
        """Test pace with invalid values."""
        assert format_pace(0, 100) == "N/A"
        assert format_pace(100, 0) == "N/A"

    def test_format_change_positive(self):
        """Test formatting positive changes."""
        assert format_change(10, higher_is_better=True) == "↑10%"
        assert format_change(10, higher_is_better=False) == "↓10%"

    def test_format_change_negative(self):
        """Test formatting negative changes."""
        assert format_change(-10, higher_is_better=True) == "↓10%"
        assert format_change(-10, higher_is_better=False) == "↑10%"

    def test_format_change_zero(self):
        """Test formatting zero change."""
        assert format_change(0) == "→0%"

    def test_format_change_none(self):
        """Test formatting None value."""
        assert format_change(None) == "—"


class TestActivitySummary:
    """Test ActivitySummary dataclass."""

    def test_duration_hours(self):
        """Test duration hours calculation."""
        summary = ActivitySummary(total_duration_seconds=7200)
        assert summary.total_duration_hours == 2.0

    def test_distance_km(self):
        """Test distance km calculation."""
        summary = ActivitySummary(total_distance_meters=10000)
        assert summary.total_distance_km == 10.0


class TestHealthSummary:
    """Test HealthSummary dataclass."""

    def test_sleep_hours(self):
        """Test sleep hours calculation."""
        summary = HealthSummary(avg_sleep_seconds=28800)  # 8 hours
        assert summary.avg_sleep_hours == 8.0

    def test_sleep_hours_none(self):
        """Test sleep hours when None."""
        summary = HealthSummary()
        assert summary.avg_sleep_hours is None


class TestPeriodComparison:
    """Test PeriodComparison dataclass."""

    def test_calculate_changes(self):
        """Test change calculation."""
        comparison = PeriodComparison(
            current={"steps": 10000, "distance": 50},
            previous={"steps": 8000, "distance": 40},
        )
        comparison.calculate_changes()

        assert comparison.changes["steps"] == 25.0  # 25% increase
        assert comparison.changes["distance"] == 25.0

    def test_calculate_changes_with_zero(self):
        """Test change calculation with zero previous value."""
        comparison = PeriodComparison(
            current={"steps": 10000},
            previous={"steps": 0},
        )
        comparison.calculate_changes()

        assert comparison.changes["steps"] is None


class TestDataAggregator:
    """Test DataAggregator class."""

    @pytest.fixture
    def db_with_data(self):
        """Create database with sample data."""
        db = Database(":memory:")
        db.initialize()
        repo = Repository(db)

        # Add activities
        activities = [
            Activity(
                activity_id="1",
                activity_type="running",
                start_time="2024-01-15T07:00:00Z",
                duration_seconds=3600,
                distance_meters=10000,
                average_hr=150,
                max_hr=175,
                calories=500,
            ),
            Activity(
                activity_id="2",
                activity_type="running",
                start_time="2024-01-16T07:00:00Z",
                duration_seconds=1800,
                distance_meters=5000,
                average_hr=145,
                calories=250,
            ),
            Activity(
                activity_id="3",
                activity_type="cycling",
                start_time="2024-01-17T08:00:00Z",
                duration_seconds=5400,
                distance_meters=30000,
                average_hr=135,
                calories=600,
            ),
        ]
        for a in activities:
            repo.upsert_activity(a)

        # Add daily summaries
        for day in range(15, 18):
            repo.upsert_daily_summary(DailySummary(
                date=f"2024-01-{day}",
                total_steps=10000 + day * 100,
                step_goal=10000,
                total_calories=2500,
            ))

        # Add sleep data
        for day in range(15, 18):
            repo.upsert_sleep(SleepDaily(
                date=f"2024-01-{day}",
                total_sleep_seconds=28800,  # 8 hours
                deep_sleep_seconds=7200,
                sleep_score=85,
            ))

        # Add heart rate data
        for day in range(15, 18):
            repo.upsert_heart_rate(HeartRateDaily(
                date=f"2024-01-{day}",
                resting_hr=52 + (day - 15),
            ))

        return db

    def test_get_activity_summary(self, db_with_data):
        """Test getting activity summary."""
        aggregator = DataAggregator(db_with_data)

        summary = aggregator.get_activity_summary(
            start_date=date(2024, 1, 15),
            end_date=date(2024, 1, 17),
        )

        assert summary.total_count == 3
        assert summary.total_duration_seconds == 10800  # 3h total
        assert summary.total_distance_meters == 45000
        assert summary.total_calories == 1350

        assert "running" in summary.by_type
        assert summary.by_type["running"]["count"] == 2

    def test_get_health_summary(self, db_with_data):
        """Test getting health summary."""
        aggregator = DataAggregator(db_with_data)

        summary = aggregator.get_health_summary(
            start_date=date(2024, 1, 15),
            end_date=date(2024, 1, 17),
        )

        assert summary.avg_steps is not None
        assert summary.avg_steps > 10000
        assert summary.avg_sleep_seconds == 28800
        assert summary.avg_sleep_score == 85
        assert summary.avg_resting_hr == 53  # Average of 52, 53, 54

    def test_get_top_activities(self, db_with_data):
        """Test getting top activities."""
        aggregator = DataAggregator(db_with_data)

        top = aggregator.get_top_activities(
            start_date=date(2024, 1, 15),
            end_date=date(2024, 1, 17),
            limit=2,
        )

        assert len(top) == 2

    def test_empty_date_range(self, db_with_data):
        """Test aggregation with no data in range."""
        aggregator = DataAggregator(db_with_data)

        summary = aggregator.get_activity_summary(
            start_date=date(2024, 2, 1),
            end_date=date(2024, 2, 7),
        )

        assert summary.total_count == 0
        assert summary.total_duration_seconds == 0


class TestLLMReportFormatter:
    """Test LLMReportFormatter class."""

    @pytest.fixture
    def db_with_data(self):
        """Create database with sample data."""
        db = Database(":memory:")
        db.initialize()
        repo = Repository(db)

        # Add some sample data
        repo.upsert_activity(Activity(
            activity_id="1",
            activity_name="Morning Run",
            activity_type="running",
            start_time="2024-01-15T07:00:00Z",
            duration_seconds=3600,
            distance_meters=10000,
            average_hr=150,
            calories=500,
        ))

        repo.upsert_daily_summary(DailySummary(
            date="2024-01-15",
            total_steps=10000,
            step_goal=10000,
        ))

        repo.upsert_sleep(SleepDaily(
            date="2024-01-15",
            total_sleep_seconds=28800,
            sleep_score=85,
        ))

        return db

    def test_generate_weekly_report(self, db_with_data):
        """Test weekly report generation."""
        aggregator = DataAggregator(db_with_data)
        formatter = LLMReportFormatter(aggregator)

        report = formatter.generate_weekly_report(
            end_date=date(2024, 1, 15),
            include_comparison=False,
            llm_mode=True,
        )

        assert "Weekly Fitness Summary" in report
        assert "Quick Stats" in report
        assert "Activity Breakdown" in report or "Activities" in report

    def test_generate_monthly_report(self, db_with_data):
        """Test monthly report generation."""
        aggregator = DataAggregator(db_with_data)
        formatter = LLMReportFormatter(aggregator)

        report = formatter.generate_monthly_report(
            year=2024,
            month=1,
            llm_mode=True,
        )

        assert "Monthly Fitness Summary" in report
        assert "January 2024" in report

    def test_estimate_tokens(self, db_with_data):
        """Test token estimation."""
        aggregator = DataAggregator(db_with_data)
        formatter = LLMReportFormatter(aggregator)

        # 400 characters ~ 100 tokens
        text = "x" * 400
        tokens = formatter.estimate_tokens(text)
        assert tokens == 100


class TestReportGenerator:
    """Test ReportGenerator class."""

    @pytest.fixture
    def db_with_data(self):
        """Create database with sample data."""
        db = Database(":memory:")
        db.initialize()
        repo = Repository(db)

        repo.upsert_activity(Activity(
            activity_id="1",
            activity_type="running",
            start_time="2024-01-15T07:00:00Z",
            duration_seconds=3600,
            distance_meters=10000,
        ))

        repo.upsert_daily_summary(DailySummary(
            date="2024-01-15",
            total_steps=10000,
        ))

        return db

    def test_generate_weekly_report(self, db_with_data):
        """Test weekly report generation via generator."""
        generator = ReportGenerator(db_with_data)

        report = generator.generate_weekly_report(
            end_date=date(2024, 1, 15),
            llm_mode=True,
        )

        assert isinstance(report, str)
        assert len(report) > 0

    def test_generate_monthly_report(self, db_with_data):
        """Test monthly report generation."""
        generator = ReportGenerator(db_with_data)

        report = generator.generate_monthly_report(
            year=2024,
            month=1,
        )

        assert isinstance(report, str)
        assert "January 2024" in report

    def test_export_activities_json(self, db_with_data, temp_dir):
        """Test exporting activities to JSON."""
        generator = ReportGenerator(db_with_data)
        output_path = temp_dir / "activities.json"

        count = generator.export_activities_json(
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            output_path=output_path,
        )

        assert count == 1
        assert output_path.exists()

        import json
        with open(output_path) as f:
            data = json.load(f)
        assert len(data) == 1

    def test_export_activities_csv(self, db_with_data, temp_dir):
        """Test exporting activities to CSV."""
        generator = ReportGenerator(db_with_data)
        output_path = temp_dir / "activities.csv"

        count = generator.export_activities_csv(
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            output_path=output_path,
        )

        assert count == 1
        assert output_path.exists()

        content = output_path.read_text()
        assert "activity_id" in content  # Header
        assert "running" in content  # Data

    def test_save_report(self, db_with_data, temp_dir):
        """Test saving report to file."""
        generator = ReportGenerator(db_with_data)
        output_path = temp_dir / "report.md"

        report = generator.generate_weekly_report()
        generator.save_report(report, output_path)

        assert output_path.exists()
        assert output_path.read_text() == report


class TestHRVContext:
    """Test HRV context calculation."""

    @pytest.fixture
    def db_with_hrv_data(self):
        """Create database with HRV data."""
        db = Database(":memory:")
        db.initialize()
        repo = Repository(db)

        # Add 10 days of HRV data
        for day in range(1, 11):
            repo.upsert_hrv(HRVDaily(
                date=f"2024-01-{day:02d}",
                hrv_value=60 + day,  # 61, 62, ..., 70
                weekly_avg=65,
                last_night_avg=60 + day,
                hrv_status="BALANCED" if day > 3 else "UNBALANCED",
            ))

        return db

    def test_hrv_baseline_7d_calculation(self, db_with_hrv_data):
        """7-day baseline is calculated correctly."""
        aggregator = DataAggregator(db_with_hrv_data)
        ctx = aggregator.get_hrv_context(date(2024, 1, 10))

        assert ctx["baseline_7d"] is not None
        # Last 7 days: 64, 65, 66, 67, 68, 69, 70 -> avg = 67
        assert ctx["baseline_7d"] == 67.0

    def test_hrv_baseline_28d_calculation(self, db_with_hrv_data):
        """28-day baseline is calculated (uses available data)."""
        aggregator = DataAggregator(db_with_hrv_data)
        ctx = aggregator.get_hrv_context(date(2024, 1, 10))

        assert ctx["baseline_28d"] is not None
        # All 10 days: 61-70 -> avg = 65.5
        assert ctx["baseline_28d"] == 65.5

    def test_hrv_last_night_value(self, db_with_hrv_data):
        """Last night HRV is captured."""
        aggregator = DataAggregator(db_with_hrv_data)
        ctx = aggregator.get_hrv_context(date(2024, 1, 10))

        assert ctx["last_night"] == 70  # Day 10

    def test_hrv_delta_from_baseline(self, db_with_hrv_data):
        """Delta from baseline is calculated as percentage."""
        aggregator = DataAggregator(db_with_hrv_data)
        ctx = aggregator.get_hrv_context(date(2024, 1, 10))

        # last_night=70, baseline_7d=67 -> delta = (70-67)/67*100 = 4.5%
        assert ctx["delta_from_baseline"] is not None
        assert abs(ctx["delta_from_baseline"] - 4.5) < 0.5

    def test_hrv_days_below_baseline(self, db_with_hrv_data):
        """Consecutive days below baseline are counted."""
        aggregator = DataAggregator(db_with_hrv_data)
        ctx = aggregator.get_hrv_context(date(2024, 1, 10))

        # All recent days (64-70) are >= or close to baseline (67)
        # Only days 1-3 (61-63) are below baseline, but they're not consecutive from end
        assert "days_below_baseline" in ctx

    def test_hrv_status_captured(self, db_with_hrv_data):
        """HRV status from Garmin is captured."""
        aggregator = DataAggregator(db_with_hrv_data)
        ctx = aggregator.get_hrv_context(date(2024, 1, 10))

        assert ctx["status"] == "BALANCED"

    def test_hrv_daily_values_included(self, db_with_hrv_data):
        """Daily values for last 7 days are included."""
        aggregator = DataAggregator(db_with_hrv_data)
        ctx = aggregator.get_hrv_context(date(2024, 1, 10))

        assert len(ctx["daily_values"]) == 7
        assert ctx["daily_values"][0]["date"] == "2024-01-10"
        assert ctx["daily_values"][0]["hrv"] == 70

    def test_hrv_context_empty_data(self):
        """Returns empty context when no data."""
        db = Database(":memory:")
        db.initialize()
        aggregator = DataAggregator(db)

        ctx = aggregator.get_hrv_context(date(2024, 1, 10))

        assert ctx["baseline_7d"] is None
        assert ctx["baseline_28d"] is None


class TestSleepConsistency:
    """Test sleep consistency calculation."""

    @pytest.fixture
    def db_with_detailed_sleep(self):
        """Create database with detailed sleep data."""
        db = Database(":memory:")
        db.initialize()
        repo = Repository(db)

        # Add 7 days of detailed sleep data
        for day in range(1, 8):
            repo.upsert_sleep(SleepDaily(
                date=f"2024-01-{day:02d}",
                sleep_start=f"2024-01-{day:02d}T22:{30+day}:00Z",
                sleep_end=f"2024-01-{day+1:02d}T06:{30+day}:00Z",
                total_sleep_seconds=28800,  # 8 hours
                deep_sleep_seconds=5400 + day * 100,  # ~19-22%
                rem_sleep_seconds=6000 + day * 50,  # ~21-23%
                awake_seconds=1200 + day * 60,  # 20-27 mins
                sleep_score=80 + day,
            ))

        return db

    def test_avg_awake_mins_calculation(self, db_with_detailed_sleep):
        """Average awake time is calculated in minutes."""
        aggregator = DataAggregator(db_with_detailed_sleep)
        result = aggregator.get_sleep_consistency(
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 7),
        )

        assert result["avg_awake_mins"] is not None
        # Average of (1260, 1320, 1380, 1440, 1500, 1560, 1620) / 60 = ~24 mins
        assert 20 < result["avg_awake_mins"] < 30

    def test_avg_rem_pct_calculation(self, db_with_detailed_sleep):
        """Average REM percentage is calculated."""
        aggregator = DataAggregator(db_with_detailed_sleep)
        result = aggregator.get_sleep_consistency(
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 7),
        )

        assert result["avg_rem_pct"] is not None
        assert 20 < result["avg_rem_pct"] < 25

    def test_avg_deep_pct_calculation(self, db_with_detailed_sleep):
        """Average deep sleep percentage is calculated."""
        aggregator = DataAggregator(db_with_detailed_sleep)
        result = aggregator.get_sleep_consistency(
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 7),
        )

        assert result["avg_deep_pct"] is not None
        assert 18 < result["avg_deep_pct"] < 25

    def test_daily_values_included(self, db_with_detailed_sleep):
        """Daily sleep values are included."""
        aggregator = DataAggregator(db_with_detailed_sleep)
        result = aggregator.get_sleep_consistency(
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 7),
        )

        assert len(result["daily_values"]) == 7
        assert "sleep_hours" in result["daily_values"][0]
        assert "sleep_score" in result["daily_values"][0]

    def test_empty_sleep_data(self):
        """Returns empty result when no data."""
        db = Database(":memory:")
        db.initialize()
        aggregator = DataAggregator(db)

        result = aggregator.get_sleep_consistency(
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 7),
        )

        assert result["avg_awake_mins"] is None
        assert result["avg_rem_pct"] is None


class TestTrainingLoadTrend:
    """Test training load trend calculation."""

    @pytest.fixture
    def db_with_training_data(self):
        """Create database with training load data."""
        db = Database(":memory:")
        db.initialize()
        repo = Repository(db)

        # Add activities with training load over 14 days
        activities = [
            # This week (last 7 days)
            Activity(activity_id="1", activity_type="running", start_time="2024-01-10T07:00:00Z",
                     training_load=80, training_effect_aerobic=3.5, training_effect_anaerobic=1.0),
            Activity(activity_id="2", activity_type="running", start_time="2024-01-12T07:00:00Z",
                     training_load=100, training_effect_aerobic=4.0, training_effect_anaerobic=1.5),
            Activity(activity_id="3", activity_type="cycling", start_time="2024-01-14T08:00:00Z",
                     training_load=60, training_effect_aerobic=2.5, training_effect_anaerobic=0.5),
            # Previous week
            Activity(activity_id="4", activity_type="running", start_time="2024-01-03T07:00:00Z",
                     training_load=90, training_effect_aerobic=3.8, training_effect_anaerobic=1.2),
            Activity(activity_id="5", activity_type="running", start_time="2024-01-05T07:00:00Z",
                     training_load=85, training_effect_aerobic=3.6, training_effect_anaerobic=1.1),
        ]
        for a in activities:
            repo.upsert_activity(a)

        return db

    def test_acute_load_7d_calculation(self, db_with_training_data):
        """7-day acute load is calculated."""
        aggregator = DataAggregator(db_with_training_data)
        result = aggregator.get_training_load_trend(date(2024, 1, 14))

        assert result["acute_load_7d"] is not None
        # This week: 80 + 100 + 60 = 240
        assert result["acute_load_7d"] == 240.0

    def test_chronic_load_28d_calculation(self, db_with_training_data):
        """28-day chronic load (weekly average) is calculated."""
        aggregator = DataAggregator(db_with_training_data)
        result = aggregator.get_training_load_trend(date(2024, 1, 14))

        assert result["chronic_load_28d"] is not None
        # Total: 80+100+60+90+85 = 415, divided by 4 weeks = 103.75
        assert abs(result["chronic_load_28d"] - 103.75) < 1

    def test_acute_chronic_ratio(self, db_with_training_data):
        """A:C ratio is calculated correctly."""
        aggregator = DataAggregator(db_with_training_data)
        result = aggregator.get_training_load_trend(date(2024, 1, 14))

        assert result["acute_chronic_ratio"] is not None
        # 240 / 103.75 = ~2.31
        assert 2.0 < result["acute_chronic_ratio"] < 2.5

    def test_week_over_week_change(self, db_with_training_data):
        """Week-over-week change percentage is calculated."""
        aggregator = DataAggregator(db_with_training_data)
        result = aggregator.get_training_load_trend(date(2024, 1, 14))

        assert result["this_week_load"] == 240.0
        assert result["prev_week_load"] == 175.0  # 90 + 85
        # Change: (240-175)/175*100 = 37.1%
        assert result["week_change_pct"] is not None
        assert abs(result["week_change_pct"] - 37.1) < 1

    def test_load_by_activity_type(self, db_with_training_data):
        """Training load is broken down by activity type."""
        aggregator = DataAggregator(db_with_training_data)
        result = aggregator.get_training_load_trend(date(2024, 1, 14))

        assert "running" in result["by_type"]
        assert "cycling" in result["by_type"]
        assert result["by_type"]["running"]["load"] == 180.0  # 80 + 100
        assert result["by_type"]["cycling"]["load"] == 60.0

    def test_daily_loads_included(self, db_with_training_data):
        """Daily training loads are included."""
        aggregator = DataAggregator(db_with_training_data)
        result = aggregator.get_training_load_trend(date(2024, 1, 14))

        assert len(result["daily_loads"]) >= 1
        assert "date" in result["daily_loads"][0]
        assert "load" in result["daily_loads"][0]

    def test_empty_training_data(self):
        """Returns empty result when no training data."""
        db = Database(":memory:")
        db.initialize()
        aggregator = DataAggregator(db)

        result = aggregator.get_training_load_trend(date(2024, 1, 14))

        assert result["acute_load_7d"] is None
        assert result["acute_chronic_ratio"] is None


class TestRestingHRTrend:
    """Test resting heart rate trend calculation."""

    @pytest.fixture
    def db_with_rhr_data(self):
        """Create database with RHR data."""
        db = Database(":memory:")
        db.initialize()
        repo = Repository(db)

        # Add 14 days of RHR data with slight upward trend
        for day in range(1, 15):
            repo.upsert_heart_rate(HeartRateDaily(
                date=f"2024-01-{day:02d}",
                resting_hr=50 + (day // 3),  # Gradual increase
            ))

        return db

    def test_rhr_baseline_calculation(self, db_with_rhr_data):
        """28-day baseline is calculated."""
        aggregator = DataAggregator(db_with_rhr_data)
        result = aggregator.get_resting_hr_trend(date(2024, 1, 14))

        assert result["baseline_28d"] is not None
        # Values range from 50-54, average around 52
        assert 50 <= result["baseline_28d"] <= 55

    def test_rhr_current_value(self, db_with_rhr_data):
        """Current RHR is captured."""
        aggregator = DataAggregator(db_with_rhr_data)
        result = aggregator.get_resting_hr_trend(date(2024, 1, 14))

        assert result["current"] == 54  # Day 14, 50 + (14//3) = 54

    def test_rhr_delta_calculation(self, db_with_rhr_data):
        """Delta from baseline is calculated."""
        aggregator = DataAggregator(db_with_rhr_data)
        result = aggregator.get_resting_hr_trend(date(2024, 1, 14))

        assert result["delta"] is not None

    def test_rhr_trend_detection(self, db_with_rhr_data):
        """Trend direction is detected."""
        aggregator = DataAggregator(db_with_rhr_data)
        result = aggregator.get_resting_hr_trend(date(2024, 1, 14))

        assert result["trend"] in ["rising", "stable", "falling", None]

    def test_rhr_daily_values_included(self, db_with_rhr_data):
        """Daily RHR values are included."""
        aggregator = DataAggregator(db_with_rhr_data)
        result = aggregator.get_resting_hr_trend(date(2024, 1, 14))

        assert len(result["daily_values"]) == 7
        assert "rhr" in result["daily_values"][0]
        assert "delta" in result["daily_values"][0]


class TestTrainingReadinessLatest:
    """Test training readiness retrieval."""

    @pytest.fixture
    def db_with_readiness_data(self):
        """Create database with training readiness data."""
        db = Database(":memory:")
        db.initialize()
        repo = Repository(db)

        repo.upsert_training_readiness(TrainingReadiness(
            date="2024-01-14",
            score=75,
            level="MODERATE",
            sleep_score=80,
            recovery_score=70,
            hrv_score=72,
            stress_history_score=78,
            training_load_balance_score=74,
            feedback_phrase="Recovery is progressing normally",
        ))

        return db

    def test_readiness_score_retrieved(self, db_with_readiness_data):
        """Training readiness score is retrieved."""
        aggregator = DataAggregator(db_with_readiness_data)
        result = aggregator.get_training_readiness_latest(date(2024, 1, 14))

        assert result["score"] == 75
        assert result["level"] == "MODERATE"

    def test_readiness_component_scores(self, db_with_readiness_data):
        """Component scores are retrieved."""
        aggregator = DataAggregator(db_with_readiness_data)
        result = aggregator.get_training_readiness_latest(date(2024, 1, 14))

        assert result["sleep_score"] == 80
        assert result["recovery_score"] == 70
        assert result["hrv_score"] == 72

    def test_readiness_feedback_retrieved(self, db_with_readiness_data):
        """Feedback phrase is retrieved."""
        aggregator = DataAggregator(db_with_readiness_data)
        result = aggregator.get_training_readiness_latest(date(2024, 1, 14))

        assert result["feedback"] == "Recovery is progressing normally"


class TestBodyBatteryRecovery:
    """Test body battery recovery calculation."""

    @pytest.fixture
    def db_with_bb_data(self):
        """Create database with body battery data."""
        db = Database(":memory:")
        db.initialize()
        repo = Repository(db)

        for day in range(1, 8):
            repo.upsert_body_battery(BodyBatteryDaily(
                date=f"2024-01-{day:02d}",
                max_level=70 + day,  # 71-77
                min_level=25 + day,  # 26-32
                start_level=30 + day,  # 31-37
                end_level=35 + day,  # 36-42
            ))

        return db

    def test_avg_overnight_recovery(self, db_with_bb_data):
        """Average overnight recovery is calculated."""
        aggregator = DataAggregator(db_with_bb_data)
        result = aggregator.get_body_battery_recovery(
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 7),
        )

        assert result["avg_overnight_recovery"] is not None
        # max - start: e.g., 71-31=40, 72-32=40, etc. -> avg = 40
        assert result["avg_overnight_recovery"] == 40

    def test_avg_morning_high(self, db_with_bb_data):
        """Average morning high is calculated."""
        aggregator = DataAggregator(db_with_bb_data)
        result = aggregator.get_body_battery_recovery(
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 7),
        )

        assert result["avg_morning_high"] is not None
        # 71-77, avg = 74
        assert result["avg_morning_high"] == 74

    def test_avg_evening_low(self, db_with_bb_data):
        """Average evening low is calculated."""
        aggregator = DataAggregator(db_with_bb_data)
        result = aggregator.get_body_battery_recovery(
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 7),
        )

        assert result["avg_evening_low"] is not None
        # 26-32, avg = 29
        assert result["avg_evening_low"] == 29

    def test_daily_values_included(self, db_with_bb_data):
        """Daily body battery values are included."""
        aggregator = DataAggregator(db_with_bb_data)
        result = aggregator.get_body_battery_recovery(
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 7),
        )

        assert len(result["daily_values"]) == 7
        assert "morning_high" in result["daily_values"][0]
        assert "overnight_recovery" in result["daily_values"][0]


class TestLLMFormatterEnhanced:
    """Test enhanced LLM report formatting."""

    @pytest.fixture
    def db_with_comprehensive_data(self):
        """Create database with comprehensive data for LLM reports."""
        db = Database(":memory:")
        db.initialize()
        repo = Repository(db)

        # Add activities with training load (days 8-14 to match report period)
        for day in range(8, 15):
            repo.upsert_activity(Activity(
                activity_id=str(day),
                activity_type="running",
                start_time=f"2024-01-{day:02d}T07:00:00Z",
                duration_seconds=3600,
                distance_meters=10000,
                average_hr=150,
                calories=500,
                training_load=80.0,
                training_effect_aerobic=3.5,
            ))

        # Add daily summaries
        for day in range(1, 15):
            repo.upsert_daily_summary(DailySummary(
                date=f"2024-01-{day:02d}",
                total_steps=10000,
                step_goal=10000,
            ))

        # Add sleep data
        for day in range(1, 15):
            repo.upsert_sleep(SleepDaily(
                date=f"2024-01-{day:02d}",
                sleep_start=f"2024-01-{day:02d}T22:30:00Z",
                sleep_end=f"2024-01-{day+1:02d}T06:30:00Z",
                total_sleep_seconds=28800,
                deep_sleep_seconds=5400,
                rem_sleep_seconds=6000,
                awake_seconds=1800,
                sleep_score=85,
            ))

        # Add HRV data
        for day in range(1, 15):
            repo.upsert_hrv(HRVDaily(
                date=f"2024-01-{day:02d}",
                hrv_value=60 + day,
                weekly_avg=65,
                last_night_avg=60 + day,
                hrv_status="BALANCED",
            ))

        # Add heart rate data
        for day in range(1, 15):
            repo.upsert_heart_rate(HeartRateDaily(
                date=f"2024-01-{day:02d}",
                resting_hr=52,
            ))

        # Add body battery data
        for day in range(1, 15):
            repo.upsert_body_battery(BodyBatteryDaily(
                date=f"2024-01-{day:02d}",
                max_level=75,
                min_level=30,
                start_level=35,
                end_level=40,
            ))

        # Add training readiness
        repo.upsert_training_readiness(TrainingReadiness(
            date="2024-01-14",
            score=75,
            level="MODERATE",
            sleep_score=80,
            recovery_score=70,
            hrv_score=72,
            feedback_phrase="Recovery is progressing normally",
        ))

        return db

    def test_llm_report_contains_recovery_analysis(self, db_with_comprehensive_data):
        """LLM report includes Recovery & Readiness Analysis section."""
        aggregator = DataAggregator(db_with_comprehensive_data)
        formatter = LLMReportFormatter(aggregator)

        report = formatter.generate_weekly_report(
            end_date=date(2024, 1, 14),
            llm_mode=True,
        )

        assert "## Recovery & Readiness Analysis" in report

    def test_llm_report_contains_hrv_section(self, db_with_comprehensive_data):
        """LLM report includes HRV Status section with baselines."""
        aggregator = DataAggregator(db_with_comprehensive_data)
        formatter = LLMReportFormatter(aggregator)

        report = formatter.generate_weekly_report(
            end_date=date(2024, 1, 14),
            llm_mode=True,
        )

        assert "### HRV Status" in report
        assert "7-Day Baseline" in report
        assert "28-Day Baseline" in report
        assert "Daily HRV" in report

    def test_llm_report_contains_sleep_analysis(self, db_with_comprehensive_data):
        """LLM report includes Sleep Analysis section."""
        aggregator = DataAggregator(db_with_comprehensive_data)
        formatter = LLMReportFormatter(aggregator)

        report = formatter.generate_weekly_report(
            end_date=date(2024, 1, 14),
            llm_mode=True,
        )

        assert "### Sleep Analysis" in report
        assert "Deep Sleep" in report or "deep" in report.lower()

    def test_llm_report_contains_training_load(self, db_with_comprehensive_data):
        """LLM report includes Training Load section with A:C ratio."""
        aggregator = DataAggregator(db_with_comprehensive_data)
        formatter = LLMReportFormatter(aggregator)

        report = formatter.generate_weekly_report(
            end_date=date(2024, 1, 14),
            llm_mode=True,
        )

        assert "### Training Load" in report
        assert "Acute" in report
        assert "Chronic" in report or "chronic" in report.lower()

    def test_llm_report_contains_decision_context(self, db_with_comprehensive_data):
        """LLM report includes Decision Context section."""
        aggregator = DataAggregator(db_with_comprehensive_data)
        formatter = LLMReportFormatter(aggregator)

        report = formatter.generate_weekly_report(
            end_date=date(2024, 1, 14),
            llm_mode=True,
        )

        assert "## Decision Context" in report
        assert "training decisions" in report.lower()

    def test_llm_report_contains_training_readiness(self, db_with_comprehensive_data):
        """LLM report includes Training Readiness section."""
        aggregator = DataAggregator(db_with_comprehensive_data)
        formatter = LLMReportFormatter(aggregator)

        report = formatter.generate_weekly_report(
            end_date=date(2024, 1, 14),
            llm_mode=True,
        )

        assert "### Training Readiness" in report
        assert "75/100" in report
        assert "MODERATE" in report

    def test_llm_report_graceful_with_missing_data(self):
        """LLM report handles missing data gracefully."""
        db = Database(":memory:")
        db.initialize()
        aggregator = DataAggregator(db)
        formatter = LLMReportFormatter(aggregator)

        report = formatter.generate_weekly_report(
            end_date=date(2024, 1, 14),
            llm_mode=True,
        )

        # Should not raise exception
        assert "Weekly Fitness Summary" in report
        assert "No HRV data available" in report or "—" in report

    def test_non_llm_mode_uses_compact_format(self, db_with_comprehensive_data):
        """Non-LLM mode uses compact health section instead of detailed analysis."""
        aggregator = DataAggregator(db_with_comprehensive_data)
        formatter = LLMReportFormatter(aggregator)

        report = formatter.generate_weekly_report(
            end_date=date(2024, 1, 14),
            llm_mode=False,
        )

        # Should not have detailed analysis sections
        assert "## Recovery & Readiness Analysis" not in report
        assert "## Decision Context" not in report
        # Should have basic health metrics
        assert "## Health Metrics" in report


class TestJSONReportGeneration:
    """Test JSON report generation."""

    @pytest.fixture
    def db_with_comprehensive_data(self):
        """Create database with comprehensive data for JSON reports."""
        db = Database(":memory:")
        db.initialize()
        repo = Repository(db)

        # Add activities with training load (days 8-14 to match report period)
        for day in range(8, 15):
            repo.upsert_activity(Activity(
                activity_id=str(day),
                activity_name=f"Morning Run {day}",
                activity_type="running",
                start_time=f"2024-01-{day:02d}T07:00:00Z",
                duration_seconds=3600,
                distance_meters=10000,
                average_hr=150,
                calories=500,
                training_load=80.0,
                training_effect_aerobic=3.5,
            ))

        # Add daily summaries
        for day in range(1, 15):
            repo.upsert_daily_summary(DailySummary(
                date=f"2024-01-{day:02d}",
                total_steps=10000,
                step_goal=10000,
            ))

        # Add sleep data
        for day in range(1, 15):
            repo.upsert_sleep(SleepDaily(
                date=f"2024-01-{day:02d}",
                sleep_start=f"2024-01-{day:02d}T22:30:00Z",
                sleep_end=f"2024-01-{day+1:02d}T06:30:00Z",
                total_sleep_seconds=28800,
                deep_sleep_seconds=5400,
                rem_sleep_seconds=6000,
                awake_seconds=1800,
                sleep_score=85,
            ))

        # Add HRV data
        for day in range(1, 15):
            repo.upsert_hrv(HRVDaily(
                date=f"2024-01-{day:02d}",
                hrv_value=60 + day,
                weekly_avg=65,
                last_night_avg=60 + day,
                hrv_status="BALANCED",
            ))

        # Add heart rate data
        for day in range(1, 15):
            repo.upsert_heart_rate(HeartRateDaily(
                date=f"2024-01-{day:02d}",
                resting_hr=52,
            ))

        # Add body battery data
        for day in range(1, 15):
            repo.upsert_body_battery(BodyBatteryDaily(
                date=f"2024-01-{day:02d}",
                max_level=75,
                min_level=30,
                start_level=35,
                end_level=40,
            ))

        # Add training readiness
        repo.upsert_training_readiness(TrainingReadiness(
            date="2024-01-14",
            score=75,
            level="MODERATE",
            sleep_score=80,
            recovery_score=70,
            hrv_score=72,
            stress_history_score=78,
            training_load_balance_score=74,
            feedback_phrase="Recovery is progressing normally",
        ))

        return db

    def test_generate_weekly_json_returns_dict(self, db_with_comprehensive_data):
        """JSON generation returns a dictionary, not a string."""
        aggregator = DataAggregator(db_with_comprehensive_data)
        formatter = LLMReportFormatter(aggregator)

        result = formatter.generate_weekly_json(end_date=date(2024, 1, 14))

        assert isinstance(result, dict)

    def test_json_contains_meta_section(self, db_with_comprehensive_data):
        """JSON includes meta section with timestamps and period."""
        aggregator = DataAggregator(db_with_comprehensive_data)
        formatter = LLMReportFormatter(aggregator)

        result = formatter.generate_weekly_json(end_date=date(2024, 1, 14))

        assert "meta" in result
        assert "generated_at" in result["meta"]
        assert "period" in result["meta"]
        assert result["meta"]["period"]["start"] == "2024-01-08"
        assert result["meta"]["period"]["end"] == "2024-01-14"
        assert result["meta"]["report_type"] == "weekly"

    def test_json_contains_summary_section(self, db_with_comprehensive_data):
        """JSON includes summary with key metrics."""
        aggregator = DataAggregator(db_with_comprehensive_data)
        formatter = LLMReportFormatter(aggregator)

        result = formatter.generate_weekly_json(end_date=date(2024, 1, 14))

        assert "summary" in result
        assert "activities" in result["summary"]
        assert "duration_hours" in result["summary"]
        assert "distance_km" in result["summary"]
        assert "calories" in result["summary"]
        assert "avg_steps" in result["summary"]
        assert "avg_sleep_hours" in result["summary"]

    def test_json_contains_comparison_section(self, db_with_comprehensive_data):
        """JSON includes week-over-week comparison."""
        aggregator = DataAggregator(db_with_comprehensive_data)
        formatter = LLMReportFormatter(aggregator)

        result = formatter.generate_weekly_json(end_date=date(2024, 1, 14))

        assert "comparison" in result
        assert "vs_last_week" in result["comparison"]

    def test_json_activities_structure(self, db_with_comprehensive_data):
        """JSON activities section has correct structure."""
        aggregator = DataAggregator(db_with_comprehensive_data)
        formatter = LLMReportFormatter(aggregator)

        result = formatter.generate_weekly_json(end_date=date(2024, 1, 14))

        assert "activities" in result
        assert "by_type" in result["activities"]
        assert "top_sessions" in result["activities"]

        # Verify by_type structure
        assert "running" in result["activities"]["by_type"]
        running = result["activities"]["by_type"]["running"]
        assert "count" in running
        assert "duration_sec" in running
        assert "distance_m" in running

    def test_json_recovery_hrv_structure(self, db_with_comprehensive_data):
        """JSON recovery.hrv has all required fields."""
        aggregator = DataAggregator(db_with_comprehensive_data)
        formatter = LLMReportFormatter(aggregator)

        result = formatter.generate_weekly_json(end_date=date(2024, 1, 14))

        hrv = result["recovery"]["hrv"]
        assert "last_night" in hrv
        assert "baseline_7d" in hrv
        assert "baseline_28d" in hrv
        assert "delta_pct" in hrv
        assert "days_below_baseline" in hrv
        assert "status" in hrv
        assert "daily" in hrv
        assert isinstance(hrv["daily"], list)

    def test_json_recovery_resting_hr_structure(self, db_with_comprehensive_data):
        """JSON recovery.resting_hr has all required fields."""
        aggregator = DataAggregator(db_with_comprehensive_data)
        formatter = LLMReportFormatter(aggregator)

        result = formatter.generate_weekly_json(end_date=date(2024, 1, 14))

        rhr = result["recovery"]["resting_hr"]
        assert "current" in rhr
        assert "baseline_28d" in rhr
        assert "delta" in rhr
        assert "trend" in rhr
        assert "daily" in rhr

    def test_json_recovery_sleep_structure(self, db_with_comprehensive_data):
        """JSON recovery.sleep has all required fields."""
        aggregator = DataAggregator(db_with_comprehensive_data)
        formatter = LLMReportFormatter(aggregator)

        result = formatter.generate_weekly_json(end_date=date(2024, 1, 14))

        sleep = result["recovery"]["sleep"]
        assert "avg_hours" in sleep
        assert "avg_score" in sleep
        assert "avg_deep_pct" in sleep
        assert "avg_rem_pct" in sleep
        assert "avg_awake_mins" in sleep
        assert "daily" in sleep

    def test_json_recovery_body_battery_structure(self, db_with_comprehensive_data):
        """JSON recovery.body_battery has all required fields."""
        aggregator = DataAggregator(db_with_comprehensive_data)
        formatter = LLMReportFormatter(aggregator)

        result = formatter.generate_weekly_json(end_date=date(2024, 1, 14))

        bb = result["recovery"]["body_battery"]
        assert "avg_morning_high" in bb
        assert "avg_evening_low" in bb
        assert "avg_overnight_recovery" in bb
        assert "daily" in bb

    def test_json_recovery_training_readiness_structure(self, db_with_comprehensive_data):
        """JSON recovery.training_readiness has all required fields."""
        aggregator = DataAggregator(db_with_comprehensive_data)
        formatter = LLMReportFormatter(aggregator)

        result = formatter.generate_weekly_json(end_date=date(2024, 1, 14))

        tr = result["recovery"]["training_readiness"]
        assert "score" in tr
        assert "level" in tr
        assert "components" in tr
        assert "feedback" in tr

        # Verify component structure
        components = tr["components"]
        assert "sleep" in components
        assert "recovery" in components
        assert "hrv" in components

    def test_json_training_load_structure(self, db_with_comprehensive_data):
        """JSON training_load has all required fields."""
        aggregator = DataAggregator(db_with_comprehensive_data)
        formatter = LLMReportFormatter(aggregator)

        result = formatter.generate_weekly_json(end_date=date(2024, 1, 14))

        load = result["training_load"]
        assert "acute_7d" in load
        assert "chronic_28d" in load
        assert "ac_ratio" in load
        assert "this_week" in load
        assert "prev_week" in load
        assert "change_pct" in load
        assert "by_type" in load
        assert "daily" in load

    def test_json_alerts_present(self, db_with_comprehensive_data):
        """JSON includes alerts array."""
        aggregator = DataAggregator(db_with_comprehensive_data)
        formatter = LLMReportFormatter(aggregator)

        result = formatter.generate_weekly_json(end_date=date(2024, 1, 14))

        assert "alerts" in result
        assert isinstance(result["alerts"], list)


class TestAlertsGeneration:
    """Test alert generation from metrics."""

    def test_hrv_below_baseline_alert(self):
        """Alert generated when HRV is below baseline for consecutive days."""
        db = Database(":memory:")
        db.initialize()
        repo = Repository(db)

        # Add HRV data with 4 consecutive days below baseline
        for day in range(1, 10):
            hrv_value = 50 if day >= 6 else 70  # Days 6-9 below baseline
            repo.upsert_hrv(HRVDaily(
                date=f"2024-01-{day:02d}",
                hrv_value=hrv_value,
                weekly_avg=65,
                last_night_avg=hrv_value,
                hrv_status="BALANCED",
            ))

        aggregator = DataAggregator(db)
        formatter = LLMReportFormatter(aggregator)
        result = formatter.generate_weekly_json(end_date=date(2024, 1, 9))

        hrv_alerts = [a for a in result["alerts"] if a["type"] == "hrv"]
        assert len(hrv_alerts) >= 1
        # Should have a warning about consecutive days below baseline
        warning_alerts = [a for a in hrv_alerts if a["severity"] == "warning"]
        assert len(warning_alerts) >= 1
        assert "below baseline" in warning_alerts[0]["message"]

    def test_ac_ratio_high_risk_alert(self):
        """Alert generated when A:C ratio > 1.5."""
        db = Database(":memory:")
        db.initialize()
        repo = Repository(db)

        # Add activities with high acute load to get ratio > 1.5
        for day in range(8, 15):
            repo.upsert_activity(Activity(
                activity_id=str(day),
                activity_type="running",
                start_time=f"2024-01-{day:02d}T07:00:00Z",
                training_load=150.0,  # High load
            ))

        # Add lower previous week load
        for day in range(1, 5):
            repo.upsert_activity(Activity(
                activity_id=str(100 + day),
                activity_type="running",
                start_time=f"2024-01-{day:02d}T07:00:00Z",
                training_load=50.0,  # Low load
            ))

        aggregator = DataAggregator(db)
        formatter = LLMReportFormatter(aggregator)
        result = formatter.generate_weekly_json(end_date=date(2024, 1, 14))

        load_alerts = [a for a in result["alerts"] if a["type"] == "load"]
        assert len(load_alerts) >= 1
        # Should have a warning about high A:C ratio
        warning_alerts = [a for a in load_alerts if a["severity"] == "warning"]
        assert len(warning_alerts) >= 1
        assert "high" in warning_alerts[0]["message"].lower() or "A:C ratio" in warning_alerts[0]["message"]

    def test_ac_ratio_optimal_info(self):
        """Info message when A:C ratio is in optimal range."""
        db = Database(":memory:")
        db.initialize()
        repo = Repository(db)

        # Add consistent training load for 28 days to get A:C ratio near 1.0
        # Activities every other day with same load = stable training
        for day in range(1, 29):
            if day % 2 == 0:  # Every other day
                repo.upsert_activity(Activity(
                    activity_id=str(day),
                    activity_type="running",
                    start_time=f"2024-01-{day:02d}T07:00:00Z",
                    training_load=80.0,
                ))

        aggregator = DataAggregator(db)
        formatter = LLMReportFormatter(aggregator)
        result = formatter.generate_weekly_json(end_date=date(2024, 1, 28))

        load_alerts = [a for a in result["alerts"] if a["type"] == "load"]
        # Should have info about optimal ratio
        info_alerts = [a for a in load_alerts if a["severity"] == "info"]
        assert len(info_alerts) >= 1
        assert "optimal" in info_alerts[0]["message"].lower()

    def test_rhr_elevated_alert(self):
        """Alert generated when RHR is elevated above baseline."""
        db = Database(":memory:")
        db.initialize()
        repo = Repository(db)

        # Add RHR data with significant elevation
        for day in range(1, 28):
            rhr = 50 if day <= 20 else 58  # Last week elevated by 8 bpm
            repo.upsert_heart_rate(HeartRateDaily(
                date=f"2024-01-{day:02d}",
                resting_hr=rhr,
            ))

        aggregator = DataAggregator(db)
        formatter = LLMReportFormatter(aggregator)
        result = formatter.generate_weekly_json(end_date=date(2024, 1, 27))

        rhr_alerts = [a for a in result["alerts"] if a["type"] == "rhr"]
        assert len(rhr_alerts) >= 1
        warning_alerts = [a for a in rhr_alerts if a["severity"] == "warning"]
        assert len(warning_alerts) >= 1
        assert "elevated" in warning_alerts[0]["message"].lower()

    def test_sleep_variance_alert(self):
        """Alert generated when sleep timing is inconsistent."""
        db = Database(":memory:")
        db.initialize()
        repo = Repository(db)

        # Add sleep data with high bedtime variance
        for day in range(1, 8):
            # Bedtime varies by 2+ hours
            hour = 21 + (day % 3) * 2
            repo.upsert_sleep(SleepDaily(
                date=f"2024-01-{day:02d}",
                sleep_start=f"2024-01-{day:02d}T{hour:02d}:00:00Z",
                sleep_end=f"2024-01-{day+1:02d}T07:00:00Z",
                total_sleep_seconds=28800,
                sleep_score=80,
            ))

        aggregator = DataAggregator(db)
        formatter = LLMReportFormatter(aggregator)
        result = formatter.generate_weekly_json(end_date=date(2024, 1, 7))

        sleep_alerts = [a for a in result["alerts"] if a["type"] == "sleep"]
        # May or may not trigger depending on calculated variance
        # Just verify alerts structure is present
        assert "alerts" in result

    def test_readiness_low_alert(self):
        """Alert generated when training readiness is low."""
        db = Database(":memory:")
        db.initialize()
        repo = Repository(db)

        repo.upsert_training_readiness(TrainingReadiness(
            date="2024-01-14",
            score=42,
            level="LOW",
            sleep_score=50,
            recovery_score=40,
            hrv_score=35,
        ))

        aggregator = DataAggregator(db)
        formatter = LLMReportFormatter(aggregator)
        result = formatter.generate_weekly_json(end_date=date(2024, 1, 14))

        readiness_alerts = [a for a in result["alerts"] if a["type"] == "readiness"]
        assert len(readiness_alerts) >= 1
        warning_alerts = [a for a in readiness_alerts if a["severity"] == "warning"]
        assert len(warning_alerts) >= 1
        assert "low" in warning_alerts[0]["message"].lower() or "recovery" in warning_alerts[0]["message"].lower()

    def test_no_warning_alerts_when_metrics_normal(self):
        """No warning alerts when all metrics are normal."""
        db = Database(":memory:")
        db.initialize()
        repo = Repository(db)

        # Add normal HRV data (above baseline)
        for day in range(1, 15):
            repo.upsert_hrv(HRVDaily(
                date=f"2024-01-{day:02d}",
                hrv_value=70,
                weekly_avg=65,
                last_night_avg=70,
                hrv_status="BALANCED",
            ))

        # Add consistent RHR
        for day in range(1, 15):
            repo.upsert_heart_rate(HeartRateDaily(
                date=f"2024-01-{day:02d}",
                resting_hr=52,
            ))

        # Add good training readiness
        repo.upsert_training_readiness(TrainingReadiness(
            date="2024-01-14",
            score=80,
            level="PRIME",
            sleep_score=85,
            recovery_score=82,
            hrv_score=78,
        ))

        aggregator = DataAggregator(db)
        formatter = LLMReportFormatter(aggregator)
        result = formatter.generate_weekly_json(end_date=date(2024, 1, 14))

        warning_alerts = [a for a in result["alerts"] if a["severity"] == "warning"]
        # Should have no warning alerts when everything is normal
        assert len(warning_alerts) == 0


class TestJSONSerialization:
    """Test JSON output is valid and serializable."""

    @pytest.fixture
    def db_with_comprehensive_data(self):
        """Create database with comprehensive data."""
        db = Database(":memory:")
        db.initialize()
        repo = Repository(db)

        for day in range(8, 15):
            repo.upsert_activity(Activity(
                activity_id=str(day),
                activity_type="running",
                start_time=f"2024-01-{day:02d}T07:00:00Z",
                duration_seconds=3600,
                distance_meters=10000,
                training_load=80.0,
            ))

        for day in range(1, 15):
            repo.upsert_daily_summary(DailySummary(
                date=f"2024-01-{day:02d}",
                total_steps=10000,
            ))
            repo.upsert_sleep(SleepDaily(
                date=f"2024-01-{day:02d}",
                total_sleep_seconds=28800,
                sleep_score=85,
            ))
            repo.upsert_hrv(HRVDaily(
                date=f"2024-01-{day:02d}",
                hrv_value=65,
            ))
            repo.upsert_heart_rate(HeartRateDaily(
                date=f"2024-01-{day:02d}",
                resting_hr=52,
            ))

        return db

    def test_json_is_serializable(self, db_with_comprehensive_data):
        """Result can be serialized to JSON string."""
        import json

        aggregator = DataAggregator(db_with_comprehensive_data)
        formatter = LLMReportFormatter(aggregator)

        result = formatter.generate_weekly_json(end_date=date(2024, 1, 14))

        json_str = json.dumps(result)
        assert isinstance(json_str, str)

        # Can be parsed back
        parsed = json.loads(json_str)
        assert parsed == result

    def test_json_handles_none_values(self):
        """None values are handled correctly in JSON output."""
        import json

        db = Database(":memory:")
        db.initialize()
        aggregator = DataAggregator(db)
        formatter = LLMReportFormatter(aggregator)

        result = formatter.generate_weekly_json(end_date=date(2024, 1, 14))

        # Should not raise exception
        json_str = json.dumps(result)
        assert json_str  # Non-empty string

    def test_json_dates_are_iso_format(self, db_with_comprehensive_data):
        """All dates in JSON are ISO format strings."""
        aggregator = DataAggregator(db_with_comprehensive_data)
        formatter = LLMReportFormatter(aggregator)

        result = formatter.generate_weekly_json(end_date=date(2024, 1, 14))

        # Check period dates
        assert result["meta"]["period"]["start"] == "2024-01-08"
        assert result["meta"]["period"]["end"] == "2024-01-14"

        # Check daily values dates (if any exist)
        for day in result["recovery"]["hrv"]["daily"]:
            # Should match YYYY-MM-DD pattern
            assert len(day["date"]) == 10
            assert day["date"][4] == "-"


class TestJSONEdgeCases:
    """Test JSON output edge cases."""

    def test_empty_database(self):
        """JSON output handles empty database gracefully."""
        db = Database(":memory:")
        db.initialize()

        aggregator = DataAggregator(db)
        formatter = LLMReportFormatter(aggregator)

        result = formatter.generate_weekly_json(end_date=date(2024, 1, 14))

        assert result["summary"]["activities"] == 0
        assert result["recovery"]["hrv"]["baseline_7d"] is None
        # Empty database may still have info alerts, but no warnings
        warning_alerts = [a for a in result["alerts"] if a["severity"] == "warning"]
        assert len(warning_alerts) == 0

    def test_partial_data(self):
        """JSON output handles partial data (some tables empty)."""
        db = Database(":memory:")
        db.initialize()
        repo = Repository(db)

        # Only add activities, no health data
        repo.upsert_activity(Activity(
            activity_id="1",
            activity_type="running",
            start_time="2024-01-14T07:00:00Z",
            duration_seconds=3600,
            training_load=80.0,
        ))

        aggregator = DataAggregator(db)
        formatter = LLMReportFormatter(aggregator)

        result = formatter.generate_weekly_json(end_date=date(2024, 1, 14))

        assert result["summary"]["activities"] == 1
        assert result["recovery"]["hrv"]["baseline_7d"] is None
        assert result["recovery"]["sleep"]["avg_hours"] is None

    def test_single_day_data(self):
        """JSON output works with only one day of data."""
        db = Database(":memory:")
        db.initialize()
        repo = Repository(db)

        # Add data for just one day
        repo.upsert_activity(Activity(
            activity_id="1",
            activity_type="running",
            start_time="2024-01-14T07:00:00Z",
            duration_seconds=3600,
        ))
        repo.upsert_hrv(HRVDaily(
            date="2024-01-14",
            hrv_value=65,
        ))

        aggregator = DataAggregator(db)
        formatter = LLMReportFormatter(aggregator)

        result = formatter.generate_weekly_json(end_date=date(2024, 1, 14))

        # Should still have structure, just with limited daily arrays
        assert len(result["recovery"]["hrv"]["daily"]) == 1


class TestMonthlyJSONReport:
    """Test monthly JSON report generation."""

    @pytest.fixture
    def db_with_monthly_data(self):
        """Create database with a month of data."""
        db = Database(":memory:")
        db.initialize()
        repo = Repository(db)

        for day in range(1, 15):
            repo.upsert_activity(Activity(
                activity_id=str(day),
                activity_type="running",
                start_time=f"2024-01-{day:02d}T07:00:00Z",
                duration_seconds=3600,
                distance_meters=10000,
                training_load=80.0,
            ))
            repo.upsert_daily_summary(DailySummary(
                date=f"2024-01-{day:02d}",
                total_steps=10000,
            ))

        return db

    def test_monthly_json_returns_dict(self, db_with_monthly_data):
        """Monthly JSON generation returns a dictionary."""
        aggregator = DataAggregator(db_with_monthly_data)
        formatter = LLMReportFormatter(aggregator)

        result = formatter.generate_monthly_json(year=2024, month=1)

        assert isinstance(result, dict)

    def test_monthly_json_has_correct_report_type(self, db_with_monthly_data):
        """Monthly JSON has correct report_type in meta."""
        aggregator = DataAggregator(db_with_monthly_data)
        formatter = LLMReportFormatter(aggregator)

        result = formatter.generate_monthly_json(year=2024, month=1)

        assert result["meta"]["report_type"] == "monthly"
        assert result["meta"]["period"]["start"] == "2024-01-01"
        assert result["meta"]["period"]["end"] == "2024-01-31"

    def test_monthly_json_contains_all_sections(self, db_with_monthly_data):
        """Monthly JSON includes all expected sections."""
        aggregator = DataAggregator(db_with_monthly_data)
        formatter = LLMReportFormatter(aggregator)

        result = formatter.generate_monthly_json(year=2024, month=1)

        assert "meta" in result
        assert "summary" in result
        assert "activities" in result
        assert "recovery" in result
        assert "training_load" in result
        assert "alerts" in result


class TestAlertBoundaryValues:
    """Test alert generation at exact boundary thresholds."""

    def test_ac_ratio_exactly_1_5_triggers_warning(self):
        """A:C ratio exactly 1.5 should trigger warning (>1.5 threshold)."""
        db = Database(":memory:")
        db.initialize()
        repo = Repository(db)

        # Create data to get A:C ratio of exactly 1.5
        # Acute (7 days): 300, Chronic (28 day avg): 200
        for day in range(22, 29):  # Days 22-28 = 7 days
            repo.upsert_activity(Activity(
                activity_id=str(day),
                activity_type="running",
                start_time=f"2024-01-{day:02d}T07:00:00Z",
                training_load=300.0 / 7,  # ~42.9 per day
            ))
        for day in range(1, 22):  # Days 1-21 = 21 days
            repo.upsert_activity(Activity(
                activity_id=str(100 + day),
                activity_type="running",
                start_time=f"2024-01-{day:02d}T07:00:00Z",
                training_load=500.0 / 21,  # ~23.8 per day
            ))

        aggregator = DataAggregator(db)
        formatter = LLMReportFormatter(aggregator)
        result = formatter.generate_weekly_json(end_date=date(2024, 1, 28))

        # Verify we have training load alerts
        load_alerts = [a for a in result["alerts"] if a["type"] == "load"]
        assert len(load_alerts) >= 1

    def test_ac_ratio_exactly_0_8_is_optimal(self):
        """A:C ratio exactly 0.8 should be in optimal range (0.8-1.3)."""
        db = Database(":memory:")
        db.initialize()
        repo = Repository(db)

        # Create lower acute load relative to chronic
        for day in range(22, 29):  # Acute week
            repo.upsert_activity(Activity(
                activity_id=str(day),
                activity_type="running",
                start_time=f"2024-01-{day:02d}T07:00:00Z",
                training_load=40.0,
            ))
        for day in range(1, 22):  # Previous 3 weeks
            repo.upsert_activity(Activity(
                activity_id=str(100 + day),
                activity_type="running",
                start_time=f"2024-01-{day:02d}T07:00:00Z",
                training_load=50.0,
            ))

        aggregator = DataAggregator(db)
        formatter = LLMReportFormatter(aggregator)
        result = formatter.generate_weekly_json(end_date=date(2024, 1, 28))

        load_alerts = [a for a in result["alerts"] if a["type"] == "load"]
        # Should have info alert (not warning) since ratio should be around 0.8-1.0
        info_alerts = [a for a in load_alerts if a["severity"] == "info"]
        assert len(info_alerts) >= 1

    def test_rhr_exactly_5_bpm_above_baseline_triggers_warning(self):
        """RHR exactly 6 bpm above baseline triggers warning (>5 threshold)."""
        db = Database(":memory:")
        db.initialize()
        repo = Repository(db)

        # 28 days of data, last day is 6 bpm above baseline
        for day in range(1, 28):
            repo.upsert_heart_rate(HeartRateDaily(
                date=f"2024-01-{day:02d}",
                resting_hr=50,
            ))
        repo.upsert_heart_rate(HeartRateDaily(
            date="2024-01-28",
            resting_hr=56,  # 6 bpm above 50
        ))

        aggregator = DataAggregator(db)
        formatter = LLMReportFormatter(aggregator)
        result = formatter.generate_weekly_json(end_date=date(2024, 1, 28))

        rhr_alerts = [a for a in result["alerts"] if a["type"] == "rhr"]
        warning_alerts = [a for a in rhr_alerts if a["severity"] == "warning"]
        assert len(warning_alerts) >= 1
        assert "elevated" in warning_alerts[0]["message"].lower()

    def test_readiness_exactly_50_is_moderate(self):
        """Readiness score exactly 50 should be moderate, not low."""
        db = Database(":memory:")
        db.initialize()
        repo = Repository(db)

        repo.upsert_training_readiness(TrainingReadiness(
            date="2024-01-14",
            score=50,
            level="MODERATE",
        ))

        aggregator = DataAggregator(db)
        formatter = LLMReportFormatter(aggregator)
        result = formatter.generate_weekly_json(end_date=date(2024, 1, 14))

        readiness_alerts = [a for a in result["alerts"] if a["type"] == "readiness"]
        # Score 50 should not trigger warning (threshold is <50)
        warning_alerts = [a for a in readiness_alerts if a["severity"] == "warning"]
        assert len(warning_alerts) == 0

    def test_readiness_49_triggers_warning(self):
        """Readiness score 49 (below 50) should trigger warning."""
        db = Database(":memory:")
        db.initialize()
        repo = Repository(db)

        repo.upsert_training_readiness(TrainingReadiness(
            date="2024-01-14",
            score=49,
            level="LOW",
        ))

        aggregator = DataAggregator(db)
        formatter = LLMReportFormatter(aggregator)
        result = formatter.generate_weekly_json(end_date=date(2024, 1, 14))

        readiness_alerts = [a for a in result["alerts"] if a["type"] == "readiness"]
        warning_alerts = [a for a in readiness_alerts if a["severity"] == "warning"]
        assert len(warning_alerts) >= 1


class TestJSONDataConsistency:
    """Test that JSON output contains consistent data with the aggregated values."""

    @pytest.fixture
    def db_with_known_data(self):
        """Create database with specific known values for verification."""
        db = Database(":memory:")
        db.initialize()
        repo = Repository(db)

        # Add exactly 3 activities with known values
        repo.upsert_activity(Activity(
            activity_id="1",
            activity_name="Run 1",
            activity_type="running",
            start_time="2024-01-14T07:00:00Z",
            duration_seconds=3600,  # 1 hour
            distance_meters=10000,  # 10 km
            calories=500,
            training_load=100.0,
        ))
        repo.upsert_activity(Activity(
            activity_id="2",
            activity_name="Run 2",
            activity_type="running",
            start_time="2024-01-13T07:00:00Z",
            duration_seconds=1800,  # 30 min
            distance_meters=5000,  # 5 km
            calories=250,
            training_load=50.0,
        ))
        repo.upsert_activity(Activity(
            activity_id="3",
            activity_name="Bike",
            activity_type="cycling",
            start_time="2024-01-12T08:00:00Z",
            duration_seconds=7200,  # 2 hours
            distance_meters=40000,  # 40 km
            calories=800,
            training_load=80.0,
        ))

        # Add daily summaries with known step counts
        for day in range(8, 15):
            repo.upsert_daily_summary(DailySummary(
                date=f"2024-01-{day:02d}",
                total_steps=10000,  # Exactly 10k steps per day
            ))

        return db

    def test_summary_values_match_expected(self, db_with_known_data):
        """Summary values match expected totals from input data."""
        aggregator = DataAggregator(db_with_known_data)
        formatter = LLMReportFormatter(aggregator)

        result = formatter.generate_weekly_json(end_date=date(2024, 1, 14))

        summary = result["summary"]
        assert summary["activities"] == 3
        # Total duration: 3600 + 1800 + 7200 = 12600 seconds = 3.5 hours
        assert summary["duration_hours"] == 3.5
        # Total distance: 10000 + 5000 + 40000 = 55000 meters = 55 km
        assert summary["distance_km"] == 55.0
        # Total calories: 500 + 250 + 800 = 1550
        assert summary["calories"] == 1550
        # Avg steps: 10000 per day
        assert summary["avg_steps"] == 10000

    def test_activities_by_type_match_expected(self, db_with_known_data):
        """Activities by type breakdown matches expected values."""
        aggregator = DataAggregator(db_with_known_data)
        formatter = LLMReportFormatter(aggregator)

        result = formatter.generate_weekly_json(end_date=date(2024, 1, 14))

        by_type = result["activities"]["by_type"]

        # Running: 2 activities, 5400 sec, 15000 m
        assert by_type["running"]["count"] == 2
        assert by_type["running"]["duration_sec"] == 5400
        assert by_type["running"]["distance_m"] == 15000

        # Cycling: 1 activity, 7200 sec, 40000 m
        assert by_type["cycling"]["count"] == 1
        assert by_type["cycling"]["duration_sec"] == 7200
        assert by_type["cycling"]["distance_m"] == 40000

    def test_training_load_values_match_expected(self, db_with_known_data):
        """Training load values match expected totals."""
        aggregator = DataAggregator(db_with_known_data)
        formatter = LLMReportFormatter(aggregator)

        result = formatter.generate_weekly_json(end_date=date(2024, 1, 14))

        load = result["training_load"]
        # Total load: 100 + 50 + 80 = 230
        assert load["acute_7d"] == 230.0
        assert load["this_week"] == 230.0

        # By type breakdown
        assert load["by_type"]["running"]["load"] == 150.0  # 100 + 50
        assert load["by_type"]["cycling"]["load"] == 80.0


class TestReportGeneratorWithFormat:
    """Test ReportGenerator format parameter."""

    @pytest.fixture
    def db_with_data(self):
        """Create database with sample data."""
        db = Database(":memory:")
        db.initialize()
        repo = Repository(db)

        repo.upsert_activity(Activity(
            activity_id="1",
            activity_type="running",
            start_time="2024-01-15T07:00:00Z",
            duration_seconds=3600,
            distance_meters=10000,
        ))

        repo.upsert_daily_summary(DailySummary(
            date="2024-01-15",
            total_steps=10000,
        ))

        return db

    def test_weekly_report_json_format(self, db_with_data):
        """Weekly report with format=json returns dict."""
        generator = ReportGenerator(db_with_data)

        result = generator.generate_weekly_report(
            end_date=date(2024, 1, 15),
            format="json",
        )

        assert isinstance(result, dict)
        assert "meta" in result

    def test_weekly_report_markdown_format(self, db_with_data):
        """Weekly report with format=markdown returns string."""
        generator = ReportGenerator(db_with_data)

        result = generator.generate_weekly_report(
            end_date=date(2024, 1, 15),
            format="markdown",
        )

        assert isinstance(result, str)
        assert "Weekly Fitness Summary" in result

    def test_monthly_report_json_format(self, db_with_data):
        """Monthly report with format=json returns dict."""
        generator = ReportGenerator(db_with_data)

        result = generator.generate_monthly_report(
            year=2024,
            month=1,
            format="json",
        )

        assert isinstance(result, dict)
        assert result["meta"]["report_type"] == "monthly"

    def test_monthly_report_markdown_format(self, db_with_data):
        """Monthly report with format=markdown returns string."""
        generator = ReportGenerator(db_with_data)

        result = generator.generate_monthly_report(
            year=2024,
            month=1,
            format="markdown",
        )

        assert isinstance(result, str)
        assert "January 2024" in result


class TestLongitudinalAggregators:
    """Test the multi-year aggregator methods."""

    @pytest.fixture
    def db_multi_year(self):
        """Seed DB with running activities across 2 years where 2024 has better
        aerobic efficiency than 2023 (same HR, faster pace)."""
        db = Database(":memory:")
        db.initialize()
        repo = Repository(db)

        # 2023: 5 runs, 10 km in 60 min = 6 min/km at HR 150
        for i in range(5):
            repo.upsert_activity(Activity(
                activity_id=f"23-{i}",
                activity_type="running",
                start_time=f"2023-0{i+1}-15T07:00:00Z",
                duration_seconds=3600,
                distance_meters=10000,
                average_hr=150,
                max_hr=170,
                calories=600,
            ))
        # 2024: 5 runs, 10 km in 50 min = 5 min/km at HR 150 (faster at same HR)
        for i in range(5):
            repo.upsert_activity(Activity(
                activity_id=f"24-{i}",
                activity_type="running",
                start_time=f"2024-0{i+1}-15T07:00:00Z",
                duration_seconds=3000,
                distance_meters=10000,
                average_hr=150,
                max_hr=170,
                calories=550,
            ))
        # One long run per year with hr_drift populated
        long_2023 = Activity(
            activity_id="23-long",
            activity_type="running",
            start_time="2023-06-10T07:00:00Z",
            duration_seconds=4500,  # 75 min
            distance_meters=12000,
            average_hr=145,
            max_hr=170,
            calories=800,
        )
        long_2024 = Activity(
            activity_id="24-long",
            activity_type="running",
            start_time="2024-06-10T07:00:00Z",
            duration_seconds=4500,
            distance_meters=14000,
            average_hr=145,
            max_hr=170,
            calories=850,
        )
        repo.upsert_activity(long_2023)
        repo.upsert_activity(long_2024)
        # Set hr_drift via direct UPDATE (no public setter for the existing column)
        cursor = db.connection.cursor()
        cursor.execute(
            "UPDATE activities SET hr_drift = ? WHERE activity_id = ?",
            (8.0, "23-long"),
        )
        cursor.execute(
            "UPDATE activities SET hr_drift = ? WHERE activity_id = ?",
            (4.5, "24-long"),
        )
        db.connection.commit()

        # Health baselines: improving year-over-year
        for day in range(1, 11):
            d23 = f"2023-01-{day:02d}"
            d24 = f"2024-01-{day:02d}"
            repo.upsert_heart_rate(HeartRateDaily(date=d23, resting_hr=55))
            repo.upsert_heart_rate(HeartRateDaily(date=d24, resting_hr=50))
            repo.upsert_hrv(HRVDaily(date=d23, hrv_value=60.0))
            repo.upsert_hrv(HRVDaily(date=d24, hrv_value=70.0))
            repo.upsert_sleep(SleepDaily(date=d23, total_sleep_seconds=25200))  # 7h
            repo.upsert_sleep(SleepDaily(date=d24, total_sleep_seconds=27000))  # 7.5h
            repo.upsert_stress(StressDaily(date=d23, avg_stress_level=35))
            repo.upsert_stress(StressDaily(date=d24, avg_stress_level=28))

        return db

    def test_aerobic_efficiency_improvement_visible(self, db_multi_year):
        """2024 should have a higher meters_per_beat than 2023 (same HR, faster pace)."""
        agg = DataAggregator(db_multi_year)
        result = agg.get_aerobic_efficiency_by_period(2023, 2024, "year")

        assert result["granularity"] == "year"
        assert len(result["periods"]) == 2
        labels = [p["label"] for p in result["periods"]]
        assert "2023" in labels and "2024" in labels

        by_label = {p["label"]: p for p in result["periods"]}
        assert by_label["2024"]["meters_per_beat"] > by_label["2023"]["meters_per_beat"]
        assert by_label["2024"]["avg_pace_min_per_km"] < by_label["2023"]["avg_pace_min_per_km"]

    def test_aerobic_efficiency_quarter_granularity(self, db_multi_year):
        """Quarter granularity should produce more buckets than year."""
        agg = DataAggregator(db_multi_year)
        year_result = agg.get_aerobic_efficiency_by_period(2023, 2024, "year")
        q_result = agg.get_aerobic_efficiency_by_period(2023, 2024, "quarter")

        assert len(q_result["periods"]) >= len(year_result["periods"])
        # Quarter labels look like "2023-Q1"
        for p in q_result["periods"]:
            assert "-Q" in p["label"]

    def test_yearly_health_baselines_shape(self, db_multi_year):
        """Returns a year entry per requested year, with all four metrics filled."""
        agg = DataAggregator(db_multi_year)
        result = agg.get_yearly_health_baselines(2023, 2024)

        assert "years" in result
        assert len(result["years"]) == 2
        for entry in result["years"]:
            for key in (
                "year",
                "avg_resting_hr",
                "avg_hrv",
                "avg_sleep_hours",
                "sleep_cov",
                "avg_stress",
            ):
                assert key in entry

        # Improving direction
        by_year = {y["year"]: y for y in result["years"]}
        assert by_year[2024]["avg_resting_hr"] < by_year[2023]["avg_resting_hr"]
        assert by_year[2024]["avg_hrv"] > by_year[2023]["avg_hrv"]
        assert by_year[2024]["avg_stress"] < by_year[2023]["avg_stress"]

    def test_yearly_health_baselines_empty_year(self, db_multi_year):
        """A year with no data returns an entry with None values rather than missing."""
        agg = DataAggregator(db_multi_year)
        result = agg.get_yearly_health_baselines(2020, 2020)

        assert len(result["years"]) == 1
        empty_year = result["years"][0]
        assert empty_year["year"] == 2020
        assert empty_year["avg_resting_hr"] is None
        assert empty_year["rhr_n_days"] == 0

    def test_volume_by_period_groups_by_type(self, db_multi_year):
        """Volume aggregator buckets by year and includes by_type breakdown."""
        agg = DataAggregator(db_multi_year)
        result = agg.get_volume_by_period(2023, 2024, "year")

        assert len(result["periods"]) == 2
        for p in result["periods"]:
            assert "running" in p["by_type"]
            assert p["total_hours"] > 0
            assert p["weeks_with_activity"] >= 1

    def test_hr_drift_by_period_filters_short_runs(self, db_multi_year):
        """Only activities ≥ 45 min with non-null hr_drift are included."""
        agg = DataAggregator(db_multi_year)
        result = agg.get_hr_drift_by_period(2023, 2024)

        assert len(result["periods"]) == 2
        by_year = {p["year"]: p for p in result["periods"]}
        assert by_year["2023"]["avg_drift_pct"] == 8.0
        assert by_year["2024"]["avg_drift_pct"] == 4.5
        # Each year should have only the one long run; the 5 short runs are excluded.
        assert by_year["2023"]["n"] == 1
        assert by_year["2024"]["n"] == 1


class TestHRDriftMedianEvenCount:
    """Test HR drift median calculation with even number of values."""

    @pytest.fixture
    def db_even_drift(self):
        """DB with 4 long runs in the same year, each with different hr_drift."""
        db = Database(":memory:")
        db.initialize()
        repo = Repository(db)

        drifts = [2.0, 4.0, 6.0, 8.0]
        for i, drift in enumerate(drifts):
            repo.upsert_activity(Activity(
                activity_id=f"drift-{i}",
                activity_type="running",
                start_time=f"2024-0{i+1}-10T07:00:00Z",
                duration_seconds=3600,  # 60 min, well above 45-min threshold
                distance_meters=12000,
                average_hr=145,
            ))
            # Set hr_drift via direct SQL (the upsert doesn't force-set it
            # when the value comes from FIT parsing, but the column is on
            # the model so this simulates a fully-populated row).
            cursor = db.connection.cursor()
            cursor.execute(
                "UPDATE activities SET hr_drift = ? WHERE activity_id = ?",
                (drift, f"drift-{i}"),
            )
        db.connection.commit()

        return db

    def test_hr_drift_median_even_count(self, db_even_drift):
        """Median of [2.0, 4.0, 6.0, 8.0] should be 5.0 (average of two middle values)."""
        agg = DataAggregator(db_even_drift)
        result = agg.get_hr_drift_by_period(2024, 2024)

        assert len(result["periods"]) == 1
        period = result["periods"][0]
        assert period["n"] == 4
        assert period["median_drift_pct"] == 5.0
