"""Tests for training periodization engine."""

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from garmin_sync.reports.periodization import PeriodizationAnalyzer


@pytest.fixture
def mock_agg():
    return MagicMock()


@pytest.fixture
def analyzer(mock_agg):
    with patch(
        "garmin_sync.reports.periodization.DataAggregator",
        return_value=mock_agg,
    ):
        a = PeriodizationAnalyzer(MagicMock())
    return a


# ------------------------------------------------------------------
# Static helpers
# ------------------------------------------------------------------


class TestComputeWeeklyTrend:
    """Tests for _compute_weekly_trend."""

    def test_insufficient_data(self):
        assert PeriodizationAnalyzer._compute_weekly_trend([]) == "insufficient_data"
        assert (
            PeriodizationAnalyzer._compute_weekly_trend(
                [{"total_load": 100}, {"total_load": 110}]
            )
            == "insufficient_data"
        )

    def test_rising(self):
        weeks = [
            {"total_load": 100},
            {"total_load": 100},
            {"total_load": 130},
            {"total_load": 140},
        ]
        assert PeriodizationAnalyzer._compute_weekly_trend(weeks) == "rising"

    def test_falling(self):
        weeks = [
            {"total_load": 200},
            {"total_load": 200},
            {"total_load": 150},
            {"total_load": 140},
        ]
        assert PeriodizationAnalyzer._compute_weekly_trend(weeks) == "falling"

    def test_steady(self):
        weeks = [
            {"total_load": 100},
            {"total_load": 102},
            {"total_load": 101},
            {"total_load": 103},
        ]
        assert PeriodizationAnalyzer._compute_weekly_trend(weeks) == "steady"

    def test_prior_avg_zero_recent_positive(self):
        weeks = [
            {"total_load": 0},
            {"total_load": 0},
            {"total_load": 50},
            {"total_load": 60},
        ]
        assert PeriodizationAnalyzer._compute_weekly_trend(weeks) == "rising"

    def test_prior_avg_zero_recent_zero(self):
        weeks = [
            {"total_load": 0},
            {"total_load": 0},
            {"total_load": 0},
            {"total_load": 0},
        ]
        assert PeriodizationAnalyzer._compute_weekly_trend(weeks) == "steady"


class TestCountPatternWeeks:
    """Tests for _count_pattern_weeks."""

    def test_insufficient_data(self):
        assert PeriodizationAnalyzer._count_pattern_weeks([], "rising") == 0
        assert (
            PeriodizationAnalyzer._count_pattern_weeks(
                [{"total_load": 100}], "rising"
            )
            == 0
        )

    def test_rising_pattern(self):
        weeks = [
            {"total_load": 80},
            {"total_load": 90},
            {"total_load": 100},
            {"total_load": 120},
        ]
        assert PeriodizationAnalyzer._count_pattern_weeks(weeks, "rising") == 3

    def test_falling_pattern(self):
        weeks = [
            {"total_load": 200},
            {"total_load": 180},
            {"total_load": 150},
        ]
        assert PeriodizationAnalyzer._count_pattern_weeks(weeks, "falling") == 2

    def test_insufficient_data_trend(self):
        weeks = [{"total_load": 100}, {"total_load": 110}]
        assert (
            PeriodizationAnalyzer._count_pattern_weeks(weeks, "insufficient_data") == 0
        )


class TestCountOverloadWeeks:
    """Tests for _count_overload_weeks."""

    def test_empty(self):
        assert PeriodizationAnalyzer._count_overload_weeks([]) == 0

    def test_no_overload(self):
        weeks = [{"total_load": 100}] * 6
        assert PeriodizationAnalyzer._count_overload_weeks(weeks) == 0

    def test_consecutive_overload(self):
        # Average = (100*3 + 200*3) / 6 = 150. Threshold = 180.
        # 200 > 180, so last 3 weeks are overload.
        weeks = [
            {"total_load": 100},
            {"total_load": 100},
            {"total_load": 100},
            {"total_load": 200},
            {"total_load": 200},
            {"total_load": 200},
        ]
        assert PeriodizationAnalyzer._count_overload_weeks(weeks) == 3

    def test_zero_average(self):
        weeks = [{"total_load": 0}] * 4
        assert PeriodizationAnalyzer._count_overload_weeks(weeks) == 0


# ------------------------------------------------------------------
# Phase detection
# ------------------------------------------------------------------


class TestDetectPhase:
    """Tests for detect_phase."""

    def test_overload_phase(self, analyzer, mock_agg):
        mock_agg.get_training_load_trend.return_value = {
            "acute_chronic_ratio": 1.7,
        }
        mock_agg.get_weekly_load_history.return_value = {
            "weeks": [
                {"total_load": 100},
                {"total_load": 120},
                {"total_load": 140},
                {"total_load": 160},
            ],
        }

        result = analyzer.detect_phase(date(2026, 5, 1))

        assert result["phase"] == "overload"
        assert result["ac_ratio"] == 1.7
        assert "1.5" in result["description"]

    def test_peak_phase(self, analyzer, mock_agg):
        mock_agg.get_training_load_trend.return_value = {
            "acute_chronic_ratio": 1.35,
        }
        mock_agg.get_weekly_load_history.return_value = {
            "weeks": [
                {"total_load": 100},
                {"total_load": 105},
                {"total_load": 110},
                {"total_load": 108},
            ],
        }

        result = analyzer.detect_phase(date(2026, 5, 1))

        assert result["phase"] == "peak"
        assert result["ac_ratio"] == 1.35

    def test_build_phase(self, analyzer, mock_agg):
        mock_agg.get_training_load_trend.return_value = {
            "acute_chronic_ratio": 1.1,
        }
        # Rising trend: recent avg (140) > prior avg (100) by >10%
        mock_agg.get_weekly_load_history.return_value = {
            "weeks": [
                {"total_load": 90},
                {"total_load": 110},
                {"total_load": 130},
                {"total_load": 150},
            ],
        }

        result = analyzer.detect_phase(date(2026, 5, 1))

        assert result["phase"] == "build"
        assert result["weekly_load_trend"] == "rising"

    def test_base_phase(self, analyzer, mock_agg):
        mock_agg.get_training_load_trend.return_value = {
            "acute_chronic_ratio": 0.9,
        }
        mock_agg.get_weekly_load_history.return_value = {
            "weeks": [
                {"total_load": 100},
                {"total_load": 100},
                {"total_load": 100},
                {"total_load": 100},
            ],
        }

        result = analyzer.detect_phase(date(2026, 5, 1))

        assert result["phase"] == "base"
        assert result["weekly_load_trend"] == "steady"

    def test_recovery_low_ratio(self, analyzer, mock_agg):
        mock_agg.get_training_load_trend.return_value = {
            "acute_chronic_ratio": 0.5,
        }
        mock_agg.get_weekly_load_history.return_value = {
            "weeks": [
                {"total_load": 200},
                {"total_load": 180},
                {"total_load": 80},
                {"total_load": 60},
            ],
        }

        result = analyzer.detect_phase(date(2026, 5, 1))

        assert result["phase"] == "recovery"
        assert result["ac_ratio"] == 0.5
        assert "0.8" in result["description"]

    def test_recovery_no_ratio(self, analyzer, mock_agg):
        mock_agg.get_training_load_trend.return_value = {
            "acute_chronic_ratio": None,
        }
        mock_agg.get_weekly_load_history.return_value = {"weeks": []}

        result = analyzer.detect_phase(date(2026, 5, 1))

        assert result["phase"] == "recovery"
        assert result["ac_ratio"] is None

    def test_aggregator_exception_returns_defaults(self, analyzer, mock_agg):
        mock_agg.get_training_load_trend.side_effect = RuntimeError("DB error")

        result = analyzer.detect_phase(date(2026, 5, 1))

        assert result["phase"] == "recovery"
        assert result["ac_ratio"] is None
        assert result["weekly_load_trend"] == "insufficient_data"
        assert result["weeks_in_current_pattern"] == 0


# ------------------------------------------------------------------
# Readiness score
# ------------------------------------------------------------------


class TestReadinessScore:
    """Tests for calculate_readiness_score."""

    def test_green_signal_high_scores(self, analyzer, mock_agg):
        mock_agg.get_hrv_context.return_value = {"delta_from_baseline": 5.0}
        mock_agg.get_sleep_score_history.return_value = {"mean": 85}
        mock_agg.get_body_battery_recovery.return_value = {"avg_morning_high": 80}
        mock_agg.get_resting_hr_trend.return_value = {"delta": -2}
        mock_agg.get_training_load_trend.return_value = {"acute_chronic_ratio": 1.0}

        result = analyzer.calculate_readiness_score(date(2026, 5, 1))

        assert result["signal"] == "green"
        assert result["score"] >= 70
        assert result["components"]["hrv"]["score"] == 25
        assert result["components"]["sleep"]["score"] == 17  # (85/100)*20 = 17
        assert result["components"]["body_battery"]["score"] == 16  # (80/100)*20 = 16
        assert result["components"]["resting_hr"]["score"] == 15  # delta <= 0
        assert result["components"]["ac_ratio"]["score"] == 20  # ratio == 1.0

    def test_red_signal_low_scores(self, analyzer, mock_agg):
        mock_agg.get_hrv_context.return_value = {"delta_from_baseline": -18.0}
        mock_agg.get_sleep_score_history.return_value = {"mean": 40}
        mock_agg.get_body_battery_recovery.return_value = {"avg_morning_high": 25}
        mock_agg.get_resting_hr_trend.return_value = {"delta": 5}
        mock_agg.get_training_load_trend.return_value = {"acute_chronic_ratio": 1.8}

        result = analyzer.calculate_readiness_score(date(2026, 5, 1))

        assert result["signal"] == "red"
        assert result["score"] < 50
        # HRV: delta -18 => max(0, 25 + (-18 * 25/20)) = max(0, 25-22.5) = 2
        assert result["components"]["hrv"]["score"] == 2
        # RHR: delta +5 => max(0, 15 - 15) = 0
        assert result["components"]["resting_hr"]["score"] == 0

    def test_yellow_signal(self, analyzer, mock_agg):
        mock_agg.get_hrv_context.return_value = {"delta_from_baseline": -5.0}
        mock_agg.get_sleep_score_history.return_value = {"mean": 65}
        mock_agg.get_body_battery_recovery.return_value = {"avg_morning_high": 55}
        mock_agg.get_resting_hr_trend.return_value = {"delta": 2}
        mock_agg.get_training_load_trend.return_value = {"acute_chronic_ratio": 1.2}

        result = analyzer.calculate_readiness_score(date(2026, 5, 1))

        assert result["signal"] == "yellow"
        assert 50 <= result["score"] < 70

    def test_missing_data_yields_zero_component(self, analyzer, mock_agg):
        mock_agg.get_hrv_context.return_value = {"delta_from_baseline": None}
        mock_agg.get_sleep_score_history.return_value = {"mean": None}
        mock_agg.get_body_battery_recovery.return_value = {"avg_morning_high": None}
        mock_agg.get_resting_hr_trend.return_value = {"delta": None}
        mock_agg.get_training_load_trend.return_value = {"acute_chronic_ratio": None}

        result = analyzer.calculate_readiness_score(date(2026, 5, 1))

        assert result["score"] == 0
        assert result["signal"] == "red"
        for comp in result["components"].values():
            assert comp["score"] == 0
            assert comp["detail"] == "insufficient data"


# ------------------------------------------------------------------
# Deload recommendation
# ------------------------------------------------------------------


class TestRecommendDeload:
    """Tests for recommend_deload."""

    def test_deload_recommended(self, analyzer, mock_agg):
        # 3 consecutive overload weeks + declining recovery markers
        # Avg = (100*3 + 200*3)/6 = 150, threshold = 180, last 3 > 180
        mock_agg.get_weekly_load_history.return_value = {
            "weeks": [
                {"total_load": 100},
                {"total_load": 100},
                {"total_load": 100},
                {"total_load": 200},
                {"total_load": 200},
                {"total_load": 200},
            ],
        }
        # HRV delta < -10 triggers recovery declining
        mock_agg.get_hrv_context.return_value = {"delta_from_baseline": -15.0}

        result = analyzer.recommend_deload(date(2026, 5, 1))

        assert result["recommended"] is True
        assert result["weeks_of_overload"] == 3
        assert result["recovery_declining"] is True
        assert result["suggested_volume_pct"] == 55
        assert result["reason"] is not None

    def test_deload_not_recommended_no_overload(self, analyzer, mock_agg):
        mock_agg.get_weekly_load_history.return_value = {
            "weeks": [{"total_load": 100}] * 6,
        }

        result = analyzer.recommend_deload(date(2026, 5, 1))

        assert result["recommended"] is False
        assert result["weeks_of_overload"] == 0
        assert result["suggested_volume_pct"] is None

    def test_deload_not_recommended_overload_but_recovery_ok(self, analyzer, mock_agg):
        # Overload weeks present but recovery is fine
        mock_agg.get_weekly_load_history.return_value = {
            "weeks": [
                {"total_load": 100},
                {"total_load": 100},
                {"total_load": 100},
                {"total_load": 200},
                {"total_load": 200},
                {"total_load": 200},
            ],
        }
        # HRV and RHR within normal range
        mock_agg.get_hrv_context.return_value = {"delta_from_baseline": 2.0}
        mock_agg.get_resting_hr_trend.return_value = {"delta": 1}
        mock_agg.get_body_battery_recovery.return_value = {"avg_morning_high": 70}

        result = analyzer.recommend_deload(date(2026, 5, 1))

        assert result["recommended"] is False
        assert result["weeks_of_overload"] == 3
        assert result["recovery_declining"] is False


# ------------------------------------------------------------------
# Periodization summary
# ------------------------------------------------------------------


class TestPeriodizationSummary:
    """Tests for get_periodization_summary."""

    def test_returns_all_sub_dicts(self, analyzer, mock_agg):
        mock_agg.get_training_load_trend.return_value = {
            "acute_chronic_ratio": 1.0,
        }
        mock_agg.get_weekly_load_history.return_value = {
            "weeks": [
                {"total_load": 100},
                {"total_load": 100},
                {"total_load": 100},
                {"total_load": 100},
            ],
        }
        mock_agg.get_hrv_context.return_value = {"delta_from_baseline": 0.0}
        mock_agg.get_sleep_score_history.return_value = {"mean": 75}
        mock_agg.get_body_battery_recovery.return_value = {"avg_morning_high": 60}
        mock_agg.get_resting_hr_trend.return_value = {"delta": 0}

        result = analyzer.get_periodization_summary(date(2026, 5, 1))

        assert "phase" in result
        assert "readiness" in result
        assert "deload" in result
        assert result["phase"]["phase"] in (
            "overload",
            "peak",
            "build",
            "base",
            "recovery",
        )
        assert "score" in result["readiness"]
        assert "signal" in result["readiness"]
        assert "recommended" in result["deload"]
