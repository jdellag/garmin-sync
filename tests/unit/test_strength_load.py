"""Tests for the Strength Training Load (STL) calculator."""

import pytest

from garmin_sync.reports.strength_load import (
    DEFAULT_RPE,
    MIN_RPE_COVERAGE,
    RPE_CLAMP,
    STL_SCALE_FACTOR,
    compute_stl,
    estimate_session_rpe,
)


# ---------------------------------------------------------------------------
# estimate_session_rpe tests
# ---------------------------------------------------------------------------


class TestEstimateSessionRPE:
    """Tests for RPE estimation heuristics."""

    def test_default_rpe_with_moderate_workout(self):
        """Moderate workout (12 sets, no special signals) -> base RPE."""
        sets = [{"set_type": "normal", "is_pr": False}] * 12
        result = estimate_session_rpe(sets, exercise_count=4)
        assert result == DEFAULT_RPE

    def test_pr_adds_one(self):
        """A PR set adds +1.0 to estimated RPE."""
        sets = [
            {"set_type": "normal", "is_pr": True},
            *[{"set_type": "normal", "is_pr": False}] * 11,
        ]
        result = estimate_session_rpe(sets, exercise_count=4)
        assert result == DEFAULT_RPE + 1.0

    def test_failure_set_adds_half(self):
        """Failure/dropset adds +0.5."""
        sets = [
            {"set_type": "failure", "is_pr": False},
            *[{"set_type": "normal", "is_pr": False}] * 11,
        ]
        result = estimate_session_rpe(sets, exercise_count=4)
        assert result == DEFAULT_RPE + 0.5

    def test_dropset_adds_half(self):
        """Dropset type also adds +0.5."""
        sets = [
            {"set_type": "dropset", "is_pr": False},
            *[{"set_type": "normal", "is_pr": False}] * 11,
        ]
        result = estimate_session_rpe(sets, exercise_count=4)
        assert result == DEFAULT_RPE + 0.5

    def test_high_volume_adds_half(self):
        """20+ working sets adds +0.5."""
        sets = [{"set_type": "normal", "is_pr": False}] * 22
        result = estimate_session_rpe(sets, exercise_count=4)
        assert result == DEFAULT_RPE + 0.5

    def test_low_volume_subtracts_half(self):
        """< 10 working sets subtracts -0.5."""
        sets = [{"set_type": "normal", "is_pr": False}] * 8
        result = estimate_session_rpe(sets, exercise_count=3)
        assert result == DEFAULT_RPE - 0.5

    def test_many_exercises_adds_half(self):
        """6+ exercises adds +0.5."""
        sets = [{"set_type": "normal", "is_pr": False}] * 12
        result = estimate_session_rpe(sets, exercise_count=7)
        assert result == DEFAULT_RPE + 0.5

    def test_stacking_adjustments(self):
        """PR + failure + high volume + many exercises stack."""
        sets = [
            {"set_type": "failure", "is_pr": True},
            *[{"set_type": "normal", "is_pr": False}] * 21,
        ]
        # +1.0 (PR) + 0.5 (failure) + 0.5 (>=20 sets) + 0.5 (>=6 exercises) = +2.5
        result = estimate_session_rpe(sets, exercise_count=8)
        assert result == DEFAULT_RPE + 2.5

    def test_clamp_upper(self):
        """Result never exceeds RPE_CLAMP upper bound."""
        # Stack everything to push past 9.0
        sets = [
            {"set_type": "failure", "is_pr": True},
            *[{"set_type": "normal", "is_pr": False}] * 25,
        ]
        result = estimate_session_rpe(sets, exercise_count=10)
        assert result <= RPE_CLAMP[1]

    def test_clamp_lower(self):
        """Result never goes below RPE_CLAMP lower bound."""
        # Very light session
        sets = [{"set_type": "normal", "is_pr": False}] * 5
        result = estimate_session_rpe(sets, exercise_count=2)
        assert result >= RPE_CLAMP[0]

    def test_warmup_excluded(self):
        """Warmup sets are filtered before estimation (in compute_stl)."""
        # This test verifies the caller filters warmups, not estimate_session_rpe
        # itself, which receives pre-filtered working_sets.
        working = [{"set_type": "normal", "is_pr": False}] * 8
        result = estimate_session_rpe(working, exercise_count=3)
        assert result == DEFAULT_RPE - 0.5  # < 10 sets


# ---------------------------------------------------------------------------
# compute_stl tests
# ---------------------------------------------------------------------------


class TestComputeSTL:
    """Tests for the main STL computation."""

    def test_no_duration_returns_none(self):
        """Missing duration -> (None, 'no_data')."""
        sets = [{"set_type": "normal", "weight_kg": 100, "reps": 10, "rpe": None, "is_pr": False}]
        stl, method = compute_stl(sets, duration_seconds=None, exercise_count=1)
        assert stl is None
        assert method == "no_data"

    def test_zero_duration_returns_none(self):
        """Zero duration -> (None, 'no_data')."""
        sets = [{"set_type": "normal", "weight_kg": 100, "reps": 10, "rpe": None, "is_pr": False}]
        stl, method = compute_stl(sets, duration_seconds=0, exercise_count=1)
        assert stl is None
        assert method == "no_data"

    def test_no_working_sets_returns_none(self):
        """Only warmup sets -> (None, 'no_data')."""
        sets = [
            {"set_type": "warmup", "weight_kg": 60, "reps": 10, "rpe": None, "is_pr": False},
            {"set_type": "warmup", "weight_kg": 80, "reps": 5, "rpe": None, "is_pr": False},
        ]
        stl, method = compute_stl(sets, duration_seconds=3600, exercise_count=1)
        assert stl is None
        assert method == "no_data"

    def test_estimated_method_when_no_rpe(self):
        """No RPE logged -> uses estimation, method='estimated'."""
        sets = [
            {"set_type": "normal", "weight_kg": 100, "reps": 10, "rpe": None, "is_pr": False},
        ] * 12
        stl, method = compute_stl(sets, duration_seconds=3600, exercise_count=4)
        assert method == "estimated"
        assert stl is not None
        # 60 min * RPE 5.0 * 1.0 scale = 300
        assert stl == 300.0

    def test_srpe_method_when_rpe_above_threshold(self):
        """>=50% RPE coverage -> sRPE method."""
        # 8 sets with RPE, 4 without -> 66.7% coverage -> sRPE
        sets_with_rpe = [
            {"set_type": "normal", "weight_kg": 100, "reps": 10, "rpe": 7.0, "is_pr": False},
        ] * 8
        sets_without = [
            {"set_type": "normal", "weight_kg": 100, "reps": 10, "rpe": None, "is_pr": False},
        ] * 4
        stl, method = compute_stl(sets_with_rpe + sets_without, duration_seconds=3600, exercise_count=4)
        assert method == "srpe"
        # Volume-weighted RPE = 7.0 (all RPE sets have same weight/reps)
        # STL = 7.0 * 60 = 420.0
        assert stl == 420.0

    def test_estimated_method_below_rpe_threshold(self):
        """<50% RPE coverage -> estimation method."""
        # 3 sets with RPE, 9 without -> 25% coverage -> estimated
        sets_with_rpe = [
            {"set_type": "normal", "weight_kg": 100, "reps": 10, "rpe": 8.0, "is_pr": False},
        ] * 3
        sets_without = [
            {"set_type": "normal", "weight_kg": 100, "reps": 10, "rpe": None, "is_pr": False},
        ] * 9
        stl, method = compute_stl(sets_with_rpe + sets_without, duration_seconds=3600, exercise_count=4)
        assert method == "estimated"

    def test_volume_weighted_rpe(self):
        """Heavy set RPE weighs more than light set RPE."""
        sets = [
            # Heavy set: 150kg x 3 @ RPE 9 -> volume 450
            {"set_type": "normal", "weight_kg": 150, "reps": 3, "rpe": 9.0, "is_pr": False},
            # Light set: 50kg x 15 @ RPE 5 -> volume 750
            {"set_type": "normal", "weight_kg": 50, "reps": 15, "rpe": 5.0, "is_pr": False},
        ]
        stl, method = compute_stl(sets, duration_seconds=3600, exercise_count=2)
        assert method == "srpe"
        # Volume-weighted RPE: (9*450 + 5*750) / (450+750) = (4050+3750)/1200 = 6.5
        expected_rpe = (9.0 * 450 + 5.0 * 750) / (450 + 750)
        expected_stl = round(expected_rpe * 60.0 * STL_SCALE_FACTOR, 1)
        assert stl == expected_stl

    def test_bodyweight_sets_use_unit_weight(self):
        """Sets with no weight still count RPE via unit weighting."""
        sets = [
            {"set_type": "normal", "weight_kg": None, "reps": 15, "rpe": 6.0, "is_pr": False},
            {"set_type": "normal", "weight_kg": None, "reps": 15, "rpe": 8.0, "is_pr": False},
        ]
        stl, method = compute_stl(sets, duration_seconds=2700, exercise_count=2)
        assert method == "srpe"
        # Unit weighting: (6+8) / 2 = 7.0; STL = 7.0 * 45 = 315
        assert stl == 315.0

    def test_warmup_sets_filtered(self):
        """Warmup sets don't count toward working set volume or RPE."""
        sets = [
            {"set_type": "warmup", "weight_kg": 60, "reps": 10, "rpe": 3.0, "is_pr": False},
            {"set_type": "warmup", "weight_kg": 80, "reps": 5, "rpe": 4.0, "is_pr": False},
            {"set_type": "normal", "weight_kg": 100, "reps": 10, "rpe": 7.0, "is_pr": False},
            {"set_type": "normal", "weight_kg": 100, "reps": 10, "rpe": 7.0, "is_pr": False},
        ]
        stl, method = compute_stl(sets, duration_seconds=3600, exercise_count=1)
        assert method == "srpe"
        # Only 2 working sets, both RPE 7 -> session RPE 7
        assert stl == 420.0

    def test_short_session(self):
        """30-minute session produces reasonable load."""
        sets = [{"set_type": "normal", "weight_kg": 80, "reps": 10, "rpe": None, "is_pr": False}] * 12
        stl, method = compute_stl(sets, duration_seconds=1800, exercise_count=4)
        # 30 min * RPE 5.0 = 150
        assert stl == 150.0

    def test_long_session(self):
        """75-minute session produces higher load."""
        sets = [{"set_type": "normal", "weight_kg": 80, "reps": 10, "rpe": None, "is_pr": False}] * 12
        stl, method = compute_stl(sets, duration_seconds=4500, exercise_count=4)
        # 75 min * RPE 5.0 = 375
        assert stl == 375.0

    def test_pr_day_higher_load(self):
        """PR day produces higher estimated load than normal day."""
        normal_sets = [{"set_type": "normal", "weight_kg": 100, "reps": 5, "rpe": None, "is_pr": False}] * 15
        pr_sets = [
            {"set_type": "normal", "weight_kg": 120, "reps": 3, "rpe": None, "is_pr": True},
            *[{"set_type": "normal", "weight_kg": 100, "reps": 5, "rpe": None, "is_pr": False}] * 14,
        ]
        normal_stl, _ = compute_stl(normal_sets, 3600, exercise_count=4)
        pr_stl, _ = compute_stl(pr_sets, 3600, exercise_count=4)
        assert pr_stl > normal_stl


# ---------------------------------------------------------------------------
# compute_stl_from_workout tests
# ---------------------------------------------------------------------------


class TestComputeSTLFromWorkout:
    """Tests for the HevyWorkout model wrapper."""

    def test_from_workout_model(self):
        """compute_stl_from_workout extracts data from HevyWorkout correctly."""
        from garmin_sync.hevy.models import HevyExercise, HevySet, HevyWorkout

        workout = HevyWorkout(
            id="test-1",
            title="Upper Body",
            start_time="2026-05-30T10:00:00+00:00",
            end_time="2026-05-30T11:00:00+00:00",
            exercises=[
                HevyExercise(
                    exercise_template_id="bench",
                    exercise_name="Bench Press",
                    sets=[
                        HevySet(set_index=0, set_type="normal", weight_kg=80, reps=10),
                        HevySet(set_index=1, set_type="normal", weight_kg=80, reps=8),
                    ],
                ),
            ],
        )

        from garmin_sync.reports.strength_load import compute_stl_from_workout

        stl, method = compute_stl_from_workout(workout)
        assert stl is not None
        assert method == "estimated"  # No RPE logged
        # 2 working sets < 10 -> RPE 4.5; 60 min -> 270
        assert stl == 270.0

    def test_no_end_time_returns_none(self):
        """Workout without end_time -> no duration -> None."""
        from garmin_sync.hevy.models import HevyExercise, HevySet, HevyWorkout
        from garmin_sync.reports.strength_load import compute_stl_from_workout

        workout = HevyWorkout(
            id="test-2",
            title="Quick Workout",
            start_time="2026-05-30T10:00:00+00:00",
            end_time=None,
            exercises=[
                HevyExercise(
                    exercise_template_id="curl",
                    exercise_name="Bicep Curl",
                    sets=[HevySet(set_index=0, set_type="normal", weight_kg=15, reps=12)],
                ),
            ],
        )

        stl, method = compute_stl_from_workout(workout)
        assert stl is None
        assert method == "no_data"


# ---------------------------------------------------------------------------
# Migration test
# ---------------------------------------------------------------------------


class TestSTLMigration:
    """Test schema migration v6->v7."""

    def test_migrate_adds_stl_columns(self):
        """Migration adds training_load and stl_method to hevy_workouts."""
        import sqlite3

        from garmin_sync.db.database import Database

        db = Database(":memory:")
        db.initialize()

        cursor = db.connection.cursor()
        cursor.execute("PRAGMA table_info(hevy_workouts)")
        columns = {row[1] for row in cursor.fetchall()}

        assert "training_load" in columns
        assert "stl_method" in columns

        db.close()
