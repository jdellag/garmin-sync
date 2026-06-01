"""Tests for Tier 2 analytics — RPE, stress-recovery, sleep-performance,
monthly reports, personal records."""

import os
import time
from datetime import date, timedelta

import pytest

from garmin_sync.db.database import Database
from garmin_sync.db.models import Activity, SleepDaily, StressDaily, BodyBatteryDaily
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


def _seed_hevy_workout(db, workout_id, start_time, title="Workout"):
    """Insert a HEVY workout with exercises and sets."""
    cursor = db.connection.cursor()
    cursor.execute(
        "INSERT INTO hevy_workouts (id, title, start_time) VALUES (?, ?, ?)",
        (workout_id, title, start_time),
    )
    db.connection.commit()
    return workout_id


def _seed_hevy_exercise(db, workout_id, name, muscle_group="chest"):
    """Insert a HEVY exercise."""
    cursor = db.connection.cursor()
    cursor.execute(
        "INSERT INTO hevy_exercises (workout_id, exercise_name, muscle_group) "
        "VALUES (?, ?, ?)",
        (workout_id, name, muscle_group),
    )
    db.connection.commit()
    return cursor.lastrowid


def _seed_hevy_set(
    db, exercise_id, weight_kg, reps, rpe=None, is_pr=0, set_type="normal"
):
    """Insert a HEVY set."""
    cursor = db.connection.cursor()
    cursor.execute(
        "INSERT INTO hevy_sets (exercise_id, set_type, weight_kg, reps, rpe, is_pr) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (exercise_id, set_type, weight_kg, reps, rpe, is_pr),
    )
    db.connection.commit()


# ==================================================================
# Feature 1: RPE Analytics
# ==================================================================


class TestRPEAnalysis:
    @pytest.fixture(autouse=True)
    def _seed(self, db):
        today = date.today()

        # Workout 1 (3 days ago): moderate RPE
        w1 = _seed_hevy_workout(
            db, "w1", f"{(today - timedelta(days=3)).isoformat()}T08:00:00"
        )
        e1 = _seed_hevy_exercise(db, w1, "Bench Press")
        _seed_hevy_set(db, e1, 60, 10, rpe=7.0)
        _seed_hevy_set(db, e1, 65, 8, rpe=7.5)
        _seed_hevy_set(db, e1, 70, 6, rpe=8.0)

        # Workout 2 (1 day ago): higher RPE, similar volume
        w2 = _seed_hevy_workout(
            db, "w2", f"{(today - timedelta(days=1)).isoformat()}T08:00:00"
        )
        e2 = _seed_hevy_exercise(db, w2, "Bench Press")
        _seed_hevy_set(db, e2, 60, 10, rpe=8.5)
        _seed_hevy_set(db, e2, 65, 8, rpe=9.0)
        _seed_hevy_set(db, e2, 70, 5, rpe=9.5)

    def test_rpe_basic(self, agg):
        result = agg.get_rpe_analysis(days=7)
        assert result["overall_avg_rpe"] is not None
        assert result["rpe_coverage_pct"] == 100.0
        assert len(result["sessions"]) == 2

    def test_rpe_sessions_have_volume(self, agg):
        result = agg.get_rpe_analysis(days=7)
        for s in result["sessions"]:
            assert s["raw_volume_kg"] > 0
            assert s["rpe_adjusted_volume_kg"] > 0
            # RPE-adjusted should be less than raw (RPE < 10)
            assert s["rpe_adjusted_volume_kg"] < s["raw_volume_kg"]

    def test_rpe_no_data_returns_empty(self, db, agg):
        """No workouts in range returns zero coverage."""
        result = agg.get_rpe_analysis(days=0)
        # days=0 means today only, no workouts today
        assert result["rpe_coverage_pct"] == 0.0
        assert result["overreaching_flag"] is False


class TestRPENullHandling:
    @pytest.fixture(autouse=True)
    def _seed(self, db):
        today = date.today()
        w = _seed_hevy_workout(
            db, "w_null", f"{today.isoformat()}T08:00:00"
        )
        e = _seed_hevy_exercise(db, w, "Squat")
        # Sets without RPE
        _seed_hevy_set(db, e, 80, 5, rpe=None)
        _seed_hevy_set(db, e, 80, 5, rpe=None)
        # One set with RPE
        _seed_hevy_set(db, e, 80, 5, rpe=8.0)

    def test_partial_rpe_coverage(self, agg):
        result = agg.get_rpe_analysis(days=1)
        # 1 out of 3 sets has RPE = 33.3%
        assert result["rpe_coverage_pct"] == pytest.approx(33.3, abs=0.1)


class TestExerciseRPETrend:
    @pytest.fixture(autouse=True)
    def _seed(self, db):
        today = date.today()
        # 4 workouts over 8 weeks: RPE rising from 6 to 9
        for i, (days_ago, rpe_val) in enumerate(
            [(56, 6.0), (42, 6.5), (28, 7.5), (14, 9.0)]
        ):
            w = _seed_hevy_workout(
                db, f"w_trend_{i}",
                f"{(today - timedelta(days=days_ago)).isoformat()}T08:00:00",
            )
            e = _seed_hevy_exercise(db, w, "Deadlift")
            _seed_hevy_set(db, e, 100, 5, rpe=rpe_val)

    def test_rising_rpe_trend(self, agg):
        result = agg.get_exercise_rpe_trend("Deadlift", days=90)
        assert len(result["sessions"]) == 4
        assert result["rpe_trend"] == "rising"


class TestOverreachingDetection:
    @pytest.fixture(autouse=True)
    def _seed(self, db):
        today = date.today()
        # First half: low RPE, high volume
        for i in range(3):
            w = _seed_hevy_workout(
                db, f"w_early_{i}",
                f"{(today - timedelta(days=6 - i)).isoformat()}T08:00:00",
            )
            e = _seed_hevy_exercise(db, w, "Squat")
            _seed_hevy_set(db, e, 100, 10, rpe=6.0)
            _seed_hevy_set(db, e, 100, 10, rpe=6.5)

        # Second half: high RPE, low volume
        for i in range(3):
            w = _seed_hevy_workout(
                db, f"w_late_{i}",
                f"{(today - timedelta(days=3 - i)).isoformat()}T08:00:00",
            )
            e = _seed_hevy_exercise(db, w, "Squat")
            _seed_hevy_set(db, e, 100, 5, rpe=8.0)
            _seed_hevy_set(db, e, 100, 5, rpe=8.5)

    def test_overreaching_flag(self, agg):
        result = agg.get_rpe_analysis(days=7)
        # RPE increased > 0.5 while volume dropped
        assert result["overreaching_flag"] is True


# ==================================================================
# Feature 2: Stress-Recovery Correlation
# ==================================================================


class TestStressRecoveryCorrelation:
    @pytest.fixture(autouse=True)
    def _seed(self, repo, db):
        today = date.today()
        cursor = db.connection.cursor()

        # Seed stress: high on days 0, 2, 4 (even); low on 1, 3, 5
        # Seed BB: the DAY AFTER a high-stress day gets poor BB start
        for i in range(7):
            d = (today - timedelta(days=6 - i)).isoformat()
            stress = 60 if i % 2 == 0 else 30
            cursor.execute(
                "INSERT INTO stress_daily (date, avg_stress_level, high_stress_duration) "
                "VALUES (?, ?, ?)",
                (d, stress, 3600 if stress > 50 else 1200),
            )

        # BB: day after high-stress days (odd indices) get low BB start
        for i in range(7):
            d = (today - timedelta(days=6 - i)).isoformat()
            # Days 1, 3, 5 follow high-stress days 0, 2, 4
            bb_start = 20 if i % 2 == 1 else 60
            cursor.execute(
                "INSERT INTO body_battery_daily (date, start_level, end_level, charged, drained) "
                "VALUES (?, ?, ?, ?, ?)",
                (d, bb_start, 40, 30, 20),
            )
        db.connection.commit()

        # Add training activity on day 2 and day 4
        for i, days_ago in enumerate([4, 2]):
            d = today - timedelta(days=days_ago)
            repo.upsert_activity(Activity(
                activity_id=f"act_stress_{i}",
                activity_type="running",
                start_time=f"{d.isoformat()}T07:00:00Z",
                start_time_local=f"{d.isoformat()}T07:00:00",
                duration_seconds=3600,
                training_load=50.0,
            ))

    def test_basic_correlation(self, agg):
        today = date.today()
        result = agg.get_stress_recovery_correlation(
            today - timedelta(days=6), today
        )
        assert result["days_analyzed"] == 7
        assert result["avg_stress_training_days"] is not None
        assert result["avg_stress_rest_days"] is not None

    def test_high_stress_poor_recovery_detection(self, agg):
        today = date.today()
        result = agg.get_stress_recovery_correlation(
            today - timedelta(days=6), today
        )
        # High stress days (60) should have poor BB start (<30) on next day
        assert result["high_stress_poor_recovery_days"] > 0
        assert len(result["patterns"]) > 0
        assert result["patterns"][0]["pattern"] == "high_stress_poor_recovery"

    def test_no_data_returns_empty(self, db):
        """Empty tables return sensible defaults."""
        agg = DataAggregator(db)
        # Clear the seeded data
        cursor = db.connection.cursor()
        cursor.execute("DELETE FROM stress_daily")
        db.connection.commit()

        result = agg.get_stress_recovery_correlation(
            date.today() - timedelta(days=7), date.today()
        )
        assert result["days_analyzed"] == 0
        assert result["patterns"] == []


# ==================================================================
# Feature 3: Sleep-Performance Correlation
# ==================================================================


class TestSleepPerformanceCorrelation:
    @pytest.fixture(autouse=True)
    def _seed(self, repo, db):
        cursor = db.connection.cursor()
        today = date.today()

        # 10 days of sleep + next-day activities
        # Scores distributed around mean ~75, std ~10
        scores = [90, 85, 80, 75, 75, 73, 70, 65, 60, 55]
        for i, score in enumerate(scores):
            sleep_date = (today - timedelta(days=10 - i)).isoformat()
            activity_date = (today - timedelta(days=9 - i))

            cursor.execute(
                "INSERT INTO sleep_daily (date, sleep_score, avg_hrv, total_sleep_seconds) "
                "VALUES (?, ?, ?, ?)",
                (sleep_date, score, 50 + (score - 70), 28800),
            )

            repo.upsert_activity(Activity(
                activity_id=f"act_sleep_{i}",
                activity_type="running",
                start_time=f"{activity_date.isoformat()}T07:00:00Z",
                start_time_local=f"{activity_date.isoformat()}T07:00:00",
                duration_seconds=3600,
                training_load=40 + score * 0.5,
                hr_drift=0.02 + (100 - score) * 0.001,
                training_effect_aerobic=2.0 + score * 0.02,
            ))
        db.connection.commit()

    def test_grade_distribution(self, agg):
        today = date.today()
        result = agg.get_sleep_performance_correlation(
            today - timedelta(days=11), today
        )
        assert result["data_points"] == 10
        assert result["sleep_score_stats"] is not None
        assert "mean" in result["sleep_score_stats"]
        assert "std" in result["sleep_score_stats"]
        # Should have at least 2 grade buckets populated
        assert len(result["by_sleep_grade"]) >= 2

    def test_a_grade_has_higher_load(self, agg):
        today = date.today()
        result = agg.get_sleep_performance_correlation(
            today - timedelta(days=11), today
        )
        grades = result["by_sleep_grade"]
        # A-grade sleep (scores 85-90) should yield higher training load than lower grades
        if "A" in grades and "F" in grades:
            a_load = grades["A"]["avg_training_load"]
            f_load = grades["F"]["avg_training_load"]
            if a_load and f_load:
                assert a_load > f_load

    def test_hrv_performance_link(self, agg):
        today = date.today()
        result = agg.get_sleep_performance_correlation(
            today - timedelta(days=11), today
        )
        # With 10 data points (> 4), HRV link should be computed
        assert result["hrv_performance_link"] is not None
        assert "high_hrv_avg_load" in result["hrv_performance_link"]
        assert "low_hrv_avg_load" in result["hrv_performance_link"]

    def test_no_data_returns_empty(self):
        """Fresh DB with no sleep/activity data returns empty."""
        fresh_db = Database(":memory:")
        fresh_db.initialize()
        fresh_db.migrate()
        fresh_agg = DataAggregator(fresh_db)
        result = fresh_agg.get_sleep_performance_correlation(
            date.today() - timedelta(days=7), date.today()
        )
        assert result["data_points"] == 0
        assert result["by_sleep_grade"] == {}

    def test_insight_generated(self, agg):
        today = date.today()
        result = agg.get_sleep_performance_correlation(
            today - timedelta(days=11), today
        )
        # Insight should be generated if A and F grades exist with >10% difference
        if "A" in result["by_sleep_grade"] and "F" in result["by_sleep_grade"]:
            assert result["insight"] is not None
            assert "training load" in result["insight"]


# ==================================================================
# Feature 4: Monthly Reports
# ==================================================================


class TestMonthlyComparison:
    @pytest.fixture(autouse=True)
    def _seed(self, repo):
        # Current month activities (May 2026)
        for i in range(4):
            repo.upsert_activity(Activity(
                activity_id=f"may_{i}",
                activity_type="running",
                start_time=f"2026-05-{10 + i:02d}T07:00:00Z",
                start_time_local=f"2026-05-{10 + i:02d}T07:00:00",
                duration_seconds=3600,
                distance_meters=10000,
                calories=500,
            ))

        # Previous month activities (April 2026)
        for i in range(3):
            repo.upsert_activity(Activity(
                activity_id=f"apr_{i}",
                activity_type="running",
                start_time=f"2026-04-{10 + i:02d}T07:00:00Z",
                start_time_local=f"2026-04-{10 + i:02d}T07:00:00",
                duration_seconds=3600,
                distance_meters=8000,
                calories=400,
            ))

    def test_monthly_comparison(self, agg):
        result = agg.get_monthly_comparison(2026, 5)
        assert result.current["activities"] == 4
        assert result.previous["activities"] == 3
        # Changes should show increase
        assert result.changes["activities"] is not None
        assert result.changes["activities"] > 0

    def test_january_wraps_to_december(self, agg):
        """January comparison looks back to December of prior year."""
        result = agg.get_monthly_comparison(2026, 1)
        # No December data, so previous should be 0
        assert result.previous["activities"] == 0


class TestMonthlyBestActivities:
    @pytest.fixture(autouse=True)
    def _seed(self, repo):
        repo.upsert_activity(Activity(
            activity_id="best_dist",
            activity_name="Long Run",
            activity_type="running",
            start_time="2026-05-10T07:00:00Z",
            start_time_local="2026-05-10T07:00:00",
            duration_seconds=7200,
            distance_meters=21000,
            training_load=120,
            hr_drift=0.05,
        ))
        repo.upsert_activity(Activity(
            activity_id="best_load",
            activity_name="Interval Session",
            activity_type="running",
            start_time="2026-05-12T07:00:00Z",
            start_time_local="2026-05-12T07:00:00",
            duration_seconds=3600,
            distance_meters=8000,
            training_load=150,
            hr_drift=0.08,
        ))
        repo.upsert_activity(Activity(
            activity_id="best_drift",
            activity_name="Easy Run",
            activity_type="running",
            start_time="2026-05-14T07:00:00Z",
            start_time_local="2026-05-14T07:00:00",
            duration_seconds=3600,
            distance_meters=9000,
            training_load=40,
            hr_drift=0.01,
        ))

    def test_best_activities(self, agg):
        result = agg.get_monthly_best_activities(
            date(2026, 5, 1), date(2026, 5, 31)
        )
        assert result["longest_distance"]["name"] == "Long Run"
        assert result["longest_distance"]["distance_km"] == 21.0
        assert result["highest_training_load"]["name"] == "Interval Session"
        assert result["highest_training_load"]["training_load"] == 150.0
        assert result["best_aerobic_efficiency"]["name"] == "Easy Run"
        assert result["best_aerobic_efficiency"]["hr_drift"] == 0.01

    def test_empty_range_returns_empty_dicts(self, agg):
        result = agg.get_monthly_best_activities(
            date(2025, 1, 1), date(2025, 1, 31)
        )
        assert result["longest_distance"] == {}
        assert result["highest_training_load"] == {}
        assert result["best_aerobic_efficiency"] == {}


# ==================================================================
# Feature 5: Personal Records
# ==================================================================


class TestPersonalRecordsRepository:
    def test_upsert_new_pr(self, repo):
        pr = repo.upsert_personal_record(
            category="cardio",
            metric_name="fastest_5k",
            value=1200.0,
            date_set="2026-05-15",
            activity_id="act_5k",
        )
        assert pr is not None
        assert pr["category"] == "cardio"
        assert pr["metric_name"] == "fastest_5k"
        assert pr["value"] == 1200.0
        assert pr["previous_value"] is None

    def test_upsert_beats_existing(self, repo):
        # First PR
        repo.upsert_personal_record(
            category="cardio",
            metric_name="fastest_5k",
            value=1200.0,
            date_set="2026-05-10",
        )
        # New PR (faster = lower time)
        pr = repo.upsert_personal_record(
            category="cardio",
            metric_name="fastest_5k",
            value=1150.0,
            date_set="2026-05-15",
        )
        assert pr is not None
        assert pr["value"] == 1150.0
        assert pr["previous_value"] == 1200.0

    def test_upsert_does_not_beat(self, repo):
        # First PR
        repo.upsert_personal_record(
            category="cardio",
            metric_name="fastest_5k",
            value=1200.0,
            date_set="2026-05-10",
        )
        # Slower time — not a PR
        pr = repo.upsert_personal_record(
            category="cardio",
            metric_name="fastest_5k",
            value=1300.0,
            date_set="2026-05-15",
        )
        assert pr is None

    def test_higher_is_better_for_non_time_metrics(self, repo):
        repo.upsert_personal_record(
            category="cardio",
            metric_name="longest_run",
            value=10000.0,
            date_set="2026-05-10",
        )
        # Longer run beats existing
        pr = repo.upsert_personal_record(
            category="cardio",
            metric_name="longest_run",
            value=12000.0,
            date_set="2026-05-15",
        )
        assert pr is not None
        assert pr["value"] == 12000.0

    def test_get_personal_records(self, repo):
        repo.upsert_personal_record(
            category="cardio", metric_name="fastest_5k",
            value=1200.0, date_set="2026-05-15",
        )
        repo.upsert_personal_record(
            category="strength", metric_name="heaviest",
            value=100.0, date_set="2026-05-14",
            exercise_name="Bench Press",
        )

        all_prs = repo.get_personal_records()
        assert len(all_prs) == 2

        cardio_only = repo.get_personal_records(category="cardio")
        assert len(cardio_only) == 1
        assert cardio_only[0]["category"] == "cardio"

    def test_get_recent_prs(self, repo):
        repo.upsert_personal_record(
            category="cardio", metric_name="fastest_5k",
            value=1200.0, date_set=date.today().isoformat(),
        )
        repo.upsert_personal_record(
            category="cardio", metric_name="fastest_10k",
            value=2500.0, date_set=(date.today() - timedelta(days=30)).isoformat(),
        )

        recent = repo.get_recent_prs(days=7)
        assert len(recent) == 1
        assert recent[0]["metric_name"] == "fastest_5k"


class TestCardioActivityPRDetection:
    @pytest.fixture(autouse=True)
    def _seed(self, repo):
        # A 5K run
        repo.upsert_activity(Activity(
            activity_id="run_5k",
            activity_name="Morning 5K",
            activity_type="running",
            start_time="2026-05-15T07:00:00Z",
            start_time_local="2026-05-15T07:00:00",
            duration_seconds=1200,
            distance_meters=5000,
            training_load=60,
        ))
        # A long run
        repo.upsert_activity(Activity(
            activity_id="run_long",
            activity_name="Long Run",
            activity_type="running",
            start_time="2026-05-16T07:00:00Z",
            start_time_local="2026-05-16T07:00:00",
            duration_seconds=7200,
            distance_meters=20000,
            training_load=120,
        ))

    def test_detect_5k_pr(self, agg, repo):
        prs = agg.detect_activity_prs("run_5k")
        metric_names = [p["metric_name"] for p in prs]
        assert "fastest_5k" in metric_names
        # run_5k (5000m) should NOT get longest_run — run_long (20000m) is longer
        assert "longest_run" not in metric_names

    def test_detect_longest_run(self, agg, repo):
        """The longest run in the DB should get the PR, not a shorter one."""
        prs = agg.detect_activity_prs("run_long")
        metric_names = [p["metric_name"] for p in prs]
        assert "longest_run" in metric_names

    def test_detect_highest_training_load(self, agg, repo):
        """Only the activity with the actual highest load gets the PR."""
        # run_5k has training_load=60, run_long has 120.
        # run_5k should NOT get it — run_long is higher.
        prs_5k = agg.detect_activity_prs("run_5k")
        assert "highest_training_load" not in [p["metric_name"] for p in prs_5k]

        # run_long has the actual highest load
        prs = agg.detect_activity_prs("run_long")
        metric_names = [p["metric_name"] for p in prs]
        assert "highest_training_load" in metric_names

    def test_no_pr_when_slower(self, agg, repo):
        # Set initial 5K PR
        agg.detect_activity_prs("run_5k")

        # Add a slower 5K
        repo.upsert_activity(Activity(
            activity_id="run_5k_slow",
            activity_name="Slow 5K",
            activity_type="running",
            start_time="2026-05-17T07:00:00Z",
            start_time_local="2026-05-17T07:00:00",
            duration_seconds=1500,  # Slower
            distance_meters=5000,
        ))
        prs = agg.detect_activity_prs("run_5k_slow")
        time_prs = [p for p in prs if p["metric_name"] == "fastest_5k"]
        assert len(time_prs) == 0


class TestStrengthPRSurfacing:
    @pytest.fixture(autouse=True)
    def _seed(self, db):
        today = date.today()
        w = _seed_hevy_workout(db, "w_pr", f"{today.isoformat()}T08:00:00", "Push Day")
        e = _seed_hevy_exercise(db, w, "Bench Press", "chest")
        _seed_hevy_set(db, e, 100, 5, rpe=8.0, is_pr=1)
        _seed_hevy_set(db, e, 90, 8, rpe=7.0, is_pr=0)

    def test_surfaces_hevy_flagged_prs(self, agg):
        prs = agg.get_strength_prs(days=7)
        assert len(prs) == 1
        assert prs[0]["exercise_name"] == "Bench Press"
        assert prs[0]["category"] == "strength"
        assert prs[0]["weight_lbs"] > 0

    def test_no_prs_when_none_flagged(self, db):
        cursor = db.connection.cursor()
        cursor.execute("UPDATE hevy_sets SET is_pr = 0")
        db.connection.commit()

        agg = DataAggregator(db)
        prs = agg.get_strength_prs(days=7)
        assert len(prs) == 0


class TestSchemaMigrationV4toV5:
    def test_personal_records_table_created(self, db):
        """Migration v4→v5 creates personal_records table."""
        cursor = db.connection.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='personal_records'"
        )
        assert cursor.fetchone() is not None

    def test_personal_records_unique_constraint(self, db):
        """UNIQUE(category, metric_name, exercise_name) works for strength PRs."""
        cursor = db.connection.cursor()
        cursor.execute(
            "INSERT INTO personal_records (category, metric_name, value, date_set, exercise_name) "
            "VALUES ('strength', 'heaviest', 100, '2026-05-15', 'Bench Press')"
        )
        # Second insert with same key should conflict and update
        cursor.execute(
            "INSERT INTO personal_records (category, metric_name, value, date_set, exercise_name) "
            "VALUES ('strength', 'heaviest', 120, '2026-05-16', 'Bench Press') "
            "ON CONFLICT(category, metric_name, exercise_name) "
            "DO UPDATE SET value = excluded.value"
        )
        db.connection.commit()

        cursor.execute(
            "SELECT value FROM personal_records "
            "WHERE metric_name = 'heaviest' AND exercise_name = 'Bench Press'"
        )
        assert cursor.fetchone()["value"] == 120


# ==================================================================
# Tool enrichment integration tests
# ==================================================================


class TestToolEnrichments:
    """Test that executor tools include Tier 2 data."""

    @pytest.fixture
    def executor(self, repo, agg):
        from garmin_sync.tools.executor import ToolExecutor
        return ToolExecutor(repo, agg)

    def test_recovery_status_has_stress_recovery(self, executor):
        result = executor.get_recovery_status()
        assert "stress_recovery" in result
        assert "stress_on_training_days" in result["stress_recovery"]
        assert "patterns" in result["stress_recovery"]

    def test_recovery_status_has_sleep_performance(self, executor):
        result = executor.get_recovery_status()
        assert "sleep_performance" in result
        assert "data_points" in result["sleep_performance"]
        assert "by_sleep_grade" in result["sleep_performance"]

    def test_weekly_comparison_has_month_to_date(self, executor):
        result = executor.get_weekly_comparison()
        assert "month_to_date" in result
        assert "previous_month" in result
        assert "prs_this_week" in result

    def test_strength_summary_no_crash_on_empty(self, executor):
        # Real repo with no HEVY data — should return 0 sessions
        result = executor.get_strength_training_summary(days=7)
        assert result["total_sessions"] == 0


class TestWeeklyLoadBucketing:
    """Regression: get_weekly_load_history must bucket by distinct ISO weeks.

    A prior bug used strftime('%%Y-%%W', ...). The doubled percent is a
    literal in SQLite's strftime (not a printf-style escape), so every row
    collapsed into a single bucket literally named '%Y-%W' — which made
    _compute_weekly_trend always return 'insufficient_data' and
    _count_overload_weeks always return 0 (deload could never fire).
    """

    def _seed_activity(self, db, activity_id, start_local, load):
        cur = db.connection.cursor()
        cur.execute(
            "INSERT INTO activities (activity_id, start_time, start_time_local, "
            "training_load, average_hr) VALUES (?, ?, ?, ?, ?)",
            (activity_id, start_local, start_local, load, 140),
        )
        db.connection.commit()

    def test_distinct_weeks_not_collapsed(self, agg, db):
        today = date.today()
        # Three activities, each exactly one ISO week apart.
        for i, offset in enumerate((0, 7, 14)):
            d = (today - timedelta(days=offset)).isoformat()
            self._seed_activity(db, f"a{i}", f"{d}T08:00:00", 100.0 + i)

        weeks = agg.get_weekly_load_history(today, weeks=6).get("weeks", [])

        assert len(weeks) == 3, f"expected 3 distinct week buckets, got {len(weeks)}"
        assert len({w["week_start"] for w in weeks}) == 3  # not fused into one


class TestStrengthSummarySTLMatching:
    """Regression: get_strength_training_summary must attach the stored STL
    to every recent workout — including same-day workouts — matched by
    workout id.

    Prior bugs: (1) the end_date bound was a date-only string, which sorts
    lexicographically before any same-day 'YYYY-MM-DDTHH:...' timestamp and
    dropped today's workouts; (2) matching by title cross-assigned STL when
    two workouts shared a title (e.g. 'Push Day').
    """

    @pytest.fixture
    def executor(self, repo, agg):
        from garmin_sync.tools.executor import ToolExecutor
        return ToolExecutor(repo, agg)

    def _seed_workout(self, db, wid, title, start_time, load, method):
        cur = db.connection.cursor()
        cur.execute(
            "INSERT INTO hevy_workouts (id, title, start_time, duration_seconds, "
            "volume_kg, training_load, stl_method) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (wid, title, start_time, 3600, 5000.0, load, method),
        )
        ex = _seed_hevy_exercise(db, wid, "Bench Press", "chest")
        _seed_hevy_set(db, ex, 60.0, 10)
        db.connection.commit()

    def test_stl_attached_by_id_today_and_colliding_titles(self, executor, db):
        today = date.today()
        yesterday = today - timedelta(days=1)
        # Two workouts share the title "Push Day"; one is TODAY.
        self._seed_workout(
            db, "wA", "Push Day", f"{today.isoformat()}T10:00:00+00:00", 275.0, "srpe"
        )
        self._seed_workout(
            db, "wB", "Push Day",
            f"{yesterday.isoformat()}T10:00:00+00:00", 90.0, "estimated",
        )

        summary = executor.get_strength_training_summary(days=7)
        by_id = {w["id"]: w for w in summary["recent_workouts"]}

        # Today's workout is present and carries its OWN stored STL.
        assert "wA" in by_id, "same-day workout was dropped from the summary"
        assert by_id["wA"]["training_load"] == 275.0
        assert by_id["wA"]["stl_method"] == "srpe"
        # Colliding title did not cross-assign the other workout's STL.
        assert by_id["wB"]["training_load"] == 90.0
        assert by_id["wB"]["stl_method"] == "estimated"


class TestACOverloadBaselineGuard:
    """Regression: overload anomalies must NOT fire on a single session with
    no chronic baseline (all load inside the last 7 days), where the A:C ratio
    is structurally ~4 and meaningless. They MUST still fire on a genuine spike
    that sits on top of an established baseline. Applies to cardio and strength.
    """

    def _seed_hevy(self, db, wid, dstr, load):
        cur = db.connection.cursor()
        cur.execute(
            "INSERT INTO hevy_workouts (id, title, start_time, training_load, "
            "stl_method) VALUES (?, ?, ?, ?, ?)",
            (wid, "W", f"{dstr}T12:00:00+00:00", load, "srpe"),
        )
        db.connection.commit()

    def _seed_activity(self, db, aid, dstr, load):
        cur = db.connection.cursor()
        cur.execute(
            "INSERT INTO activities (activity_id, start_time, start_time_local, "
            "training_load) VALUES (?, ?, ?, ?)",
            (aid, f"{dstr}T12:00:00", f"{dstr}T12:00:00", load),
        )
        db.connection.commit()

    def test_strength_single_session_suppressed(self, db):
        from garmin_sync.reports.anomaly_detector import AnomalyDetector
        today = date(2026, 5, 31)
        self._seed_hevy(db, "s1", today.isoformat(), 120.0)  # only the last week
        assert AnomalyDetector(db)._check_strength_overload(today) == []

    def test_strength_spike_with_baseline_fires(self, db):
        from garmin_sync.reports.anomaly_detector import AnomalyDetector
        today = date(2026, 5, 31)
        self._seed_hevy(db, "s1", (today - timedelta(days=20)).isoformat(), 60.0)
        self._seed_hevy(db, "s2", (today - timedelta(days=13)).isoformat(), 60.0)
        self._seed_hevy(db, "s3", today.isoformat(), 320.0)  # spike on a baseline
        fired = [a for a in AnomalyDetector(db)._check_strength_overload(today)
                 if a["check"] == "strength_overload"]
        assert len(fired) == 1

    def test_cardio_single_session_suppressed(self, db):
        from garmin_sync.reports.anomaly_detector import AnomalyDetector
        today = date(2026, 5, 31)
        self._seed_activity(db, "c1", today.isoformat(), 300.0)
        fired = [a for a in AnomalyDetector(db)._check_training_overload(today)
                 if a["check"] == "training_overload"]
        assert fired == []

    def test_cardio_spike_with_baseline_fires(self, db):
        from garmin_sync.reports.anomaly_detector import AnomalyDetector
        today = date(2026, 5, 31)
        self._seed_activity(db, "c1", (today - timedelta(days=20)).isoformat(), 80.0)
        self._seed_activity(db, "c2", (today - timedelta(days=13)).isoformat(), 80.0)
        self._seed_activity(db, "c3", today.isoformat(), 420.0)
        fired = [a for a in AnomalyDetector(db)._check_training_overload(today)
                 if a["check"] == "training_overload"]
        assert len(fired) == 1


class TestHevyWeeklyLocalBucketing:
    """Regression: get_weekly_load_history must bucket HEVY workouts (stored in
    UTC) by LOCAL time, matching how activities bucket by start_time_local — so
    a late-evening lift and a same-evening cardio session land in one ISO week.
    """

    @pytest.mark.skipif(not hasattr(time, "tzset"), reason="tzset() unavailable")
    def test_late_evening_lift_buckets_with_local_cardio(self, agg, db):
        old_tz = os.environ.get("TZ")
        os.environ["TZ"] = "America/New_York"
        time.tzset()
        try:
            cur = db.connection.cursor()
            # Sunday 2026-05-31, 22:00 ET. Cardio stores local wall-clock.
            cur.execute(
                "INSERT INTO activities (activity_id, start_time, start_time_local, "
                "training_load, average_hr) VALUES (?, ?, ?, ?, ?)",
                ("c1", "2026-06-01T02:00:00", "2026-05-31T22:00:00", 100.0, 140),
            )
            # Same instant lift; HEVY stores UTC (02:00 Mon UTC == 22:00 Sun ET).
            cur.execute(
                "INSERT INTO hevy_workouts (id, title, start_time, training_load, "
                "stl_method) VALUES (?, ?, ?, ?, ?)",
                ("h1", "Leg Day", "2026-06-01T02:00:00+00:00", 300.0, "srpe"),
            )
            db.connection.commit()

            weeks = agg.get_weekly_load_history(date(2026, 6, 6), weeks=6)["weeks"]

            assert len(weeks) == 1, "lift and cardio split into different ISO weeks"
            assert weeks[0]["cardio_load"] == 100.0
            assert weeks[0]["strength_load"] == 300.0
        finally:
            if old_tz is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = old_tz
            time.tzset()
