"""Tests for garmin_sync.reports.anomaly_detector.AnomalyDetector."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_agg():
    """Return a MagicMock standing in for DataAggregator."""
    return MagicMock()


@pytest.fixture
def detector(mock_agg):
    """Build an AnomalyDetector whose internal aggregator is *mock_agg*."""
    with patch(
        "garmin_sync.reports.anomaly_detector.DataAggregator",
        return_value=mock_agg,
    ):
        from garmin_sync.reports.anomaly_detector import AnomalyDetector

        d = AnomalyDetector(MagicMock())
    return d


# ---------------------------------------------------------------------------
# Helpers — "normal / healthy" return values for every aggregator method
# ---------------------------------------------------------------------------

def _healthy_hrv():
    return {
        "delta_from_baseline": -5,
        "days_below_baseline": 0,
        "baseline_7d": 45,
        "last_night": 42,
    }


def _healthy_rhr():
    return {"delta": 1, "baseline_28d": 52, "current": 53, "trend": "stable"}


def _healthy_training_load():
    return {
        "acute_chronic_ratio": 1.1,
        "acute_load_7d": 320,
        "chronic_load_28d": 290,
        "chronic_baseline_load": 230,
    }


def _healthy_sleep_scores():
    # All scores comfortably above threshold (mean - std = 81).
    return {
        "scores": [
            {"date": f"2026-05-{10 + i:02d}", "score": 83 + (i % 3)}
            for i in range(14)
        ],
        "mean": 85.0,
        "std": 4.0,
    }


def _healthy_body_battery():
    return {
        "daily_values": [
            {"date": f"2026-05-{17 + i:02d}", "morning_high": 55 + i}
            for i in range(7)
        ]
    }


def _healthy_stress():
    return {
        "high_stress_poor_recovery_days": 1,
        "avg_stress_training_days": 35,
    }


def _healthy_rpe():
    return {"overreaching_flag": False, "overall_avg_rpe": 6.5}


def _healthy_spo2():
    return {"avg_spo2": 97.2, "min_spo2": 94}


def _set_all_healthy(mock_agg):
    """Configure mock_agg to return normal data for every method."""
    mock_agg.get_hrv_context.return_value = _healthy_hrv()
    mock_agg.get_resting_hr_trend.return_value = _healthy_rhr()
    mock_agg.get_training_load_trend.return_value = _healthy_training_load()
    mock_agg.get_sleep_score_history.return_value = _healthy_sleep_scores()
    mock_agg.get_body_battery_recovery.return_value = _healthy_body_battery()
    mock_agg.get_stress_recovery_correlation.return_value = _healthy_stress()
    mock_agg.get_rpe_analysis.return_value = _healthy_rpe()
    mock_agg.get_allday_respiration_spo2.return_value = _healthy_spo2()


# ---------------------------------------------------------------------------
# 1. Individual trigger tests — one per check
# ---------------------------------------------------------------------------

class TestHrvCrash:
    def test_triggers_on_large_negative_delta(self, detector, mock_agg):
        mock_agg.get_hrv_context.return_value = {
            "delta_from_baseline": -20,
            "days_below_baseline": 1,
            "baseline_7d": 48,
            "last_night": 38,
        }
        results = detector._check_hrv_crash(date(2026, 5, 23))
        assert len(results) == 1
        assert results[0]["check"] == "hrv_crash"
        assert results[0]["severity"] == "warning"
        assert results[0]["data"]["delta_from_baseline"] == -20

    def test_triggers_on_consecutive_days_below(self, detector, mock_agg):
        mock_agg.get_hrv_context.return_value = {
            "delta_from_baseline": -5,
            "days_below_baseline": 4,
            "baseline_7d": 48,
            "last_night": 45,
        }
        results = detector._check_hrv_crash(date(2026, 5, 23))
        assert len(results) == 1
        assert results[0]["data"]["days_below_baseline"] == 4


class TestRhrSpike:
    def test_triggers_on_high_delta(self, detector, mock_agg):
        mock_agg.get_resting_hr_trend.return_value = {
            "delta": 8,
            "baseline_28d": 52,
            "current": 60,
            "trend": "rising",
        }
        results = detector._check_rhr_spike(date(2026, 5, 23))
        assert len(results) == 1
        assert results[0]["check"] == "rhr_spike"
        assert results[0]["severity"] == "warning"
        assert results[0]["data"]["delta"] == 8


class TestTrainingOverload:
    def test_triggers_when_ratio_above_1_5(self, detector, mock_agg):
        mock_agg.get_training_load_trend.return_value = {
            "acute_chronic_ratio": 1.8,
            "acute_load_7d": 540,
            "chronic_load_28d": 300,
            "chronic_baseline_load": 240,
        }
        results = detector._check_training_overload(date(2026, 5, 23))
        assert len(results) == 1
        assert results[0]["check"] == "training_overload"
        # Reframed as a descriptive load-ramp signal, not an injury "critical".
        assert results[0]["severity"] == "warning"
        assert results[0]["data"]["acute_chronic_ratio"] == 1.8


class TestTrainingDetraining:
    def test_triggers_when_ratio_below_0_8(self, detector, mock_agg):
        mock_agg.get_training_load_trend.return_value = {
            "acute_chronic_ratio": 0.5,
            "acute_load_7d": 100,
            "chronic_load_28d": 200,
        }
        results = detector._check_training_detraining(date(2026, 5, 23))
        assert len(results) == 1
        assert results[0]["check"] == "training_detraining"
        assert results[0]["severity"] == "info"


class TestSleepDegradation:
    def test_triggers_on_3_consecutive_low_nights(self, detector, mock_agg):
        # mean=80, std=10 => threshold=70.  Scores: 65,65,65 then normal.
        mock_agg.get_sleep_score_history.return_value = {
            "scores": [
                {"date": "2026-05-10", "score": 65},
                {"date": "2026-05-11", "score": 65},
                {"date": "2026-05-12", "score": 65},
                {"date": "2026-05-13", "score": 85},
                {"date": "2026-05-14", "score": 88},
            ],
            "mean": 80.0,
            "std": 10.0,
        }
        results = detector._check_sleep_degradation(date(2026, 5, 23))
        assert len(results) == 1
        assert results[0]["check"] == "sleep_degradation"
        assert results[0]["severity"] == "warning"
        assert results[0]["data"]["consecutive_low_nights"] == 3


class TestBodyBatteryDepleted:
    def test_triggers_on_2_consecutive_low_mornings(self, detector, mock_agg):
        mock_agg.get_body_battery_recovery.return_value = {
            "daily_values": [
                {"date": "2026-05-20", "morning_high": 20},
                {"date": "2026-05-21", "morning_high": 18},
                {"date": "2026-05-22", "morning_high": 60},
            ]
        }
        results = detector._check_body_battery_depleted(date(2026, 5, 23))
        assert len(results) == 1
        assert results[0]["check"] == "body_battery_depleted"
        assert results[0]["severity"] == "warning"
        assert results[0]["data"]["depleted_days"] == 2


class TestStressRecovery:
    def test_triggers_on_3_or_more_bad_days(self, detector, mock_agg):
        mock_agg.get_stress_recovery_correlation.return_value = {
            "high_stress_poor_recovery_days": 4,
            "avg_stress_training_days": 50,
        }
        results = detector._check_stress_recovery(date(2026, 5, 23))
        assert len(results) == 1
        assert results[0]["check"] == "stress_recovery"
        assert results[0]["severity"] == "warning"
        assert results[0]["data"]["high_stress_poor_recovery_days"] == 4


class TestOverreaching:
    def test_triggers_when_flag_true(self, detector, mock_agg):
        mock_agg.get_rpe_analysis.return_value = {
            "overreaching_flag": True,
            "overall_avg_rpe": 8.2,
        }
        results = detector._check_overreaching(date(2026, 5, 23))
        assert len(results) == 1
        assert results[0]["check"] == "overreaching"
        assert results[0]["severity"] == "warning"
        assert results[0]["data"]["overall_avg_rpe"] == 8.2


class TestSpo2Concern:
    def test_triggers_when_avg_below_92(self, detector, mock_agg):
        mock_agg.get_allday_respiration_spo2.return_value = {
            "avg_spo2": 89.5,
            "min_spo2": 85,
        }
        results = detector._check_spo2_concern(date(2026, 5, 23))
        assert len(results) == 1
        assert results[0]["check"] == "spo2_concern"
        assert results[0]["severity"] == "critical"
        assert results[0]["data"]["avg_spo2"] == 89.5


# ---------------------------------------------------------------------------
# 2. Healthy / no-anomalies test
# ---------------------------------------------------------------------------

class TestHealthyDataNoAnomalies:
    def test_no_anomalies_with_healthy_values(self, detector, mock_agg):
        _set_all_healthy(mock_agg)
        anomalies = detector.detect_anomalies(end_date=date(2026, 5, 23))
        assert anomalies == []


# ---------------------------------------------------------------------------
# 3. Severity sorting
# ---------------------------------------------------------------------------

class TestSeveritySorting:
    def test_anomalies_sorted_critical_warning_info(self, detector, mock_agg):
        _set_all_healthy(mock_agg)

        # Trigger one of each severity level:
        # critical — low SpO2 (<92). (Training overload is now a *warning*, not
        # a critical, since the A:C ratio is a descriptive ramp signal.)
        mock_agg.get_allday_respiration_spo2.return_value = {"avg_spo2": 88, "min_spo2": 84}
        # warning — rhr_spike (delta > 5)
        mock_agg.get_resting_hr_trend.return_value = {
            "delta": 7,
            "baseline_28d": 52,
            "current": 59,
            "trend": "rising",
        }
        # warning — training overload (ratio > 1.5) on the first load call;
        # info — detraining (ratio < 0.8) on the second call. The overload and
        # detraining checks each call get_training_load_trend once, so we feed
        # different values via side_effect.
        load_results = iter([
            {"acute_chronic_ratio": 1.9, "acute_load_7d": 570, "chronic_load_28d": 300,
             "chronic_baseline_load": 240, "chronic_baseline_weekly": 100},
            {"acute_chronic_ratio": 0.5, "acute_load_7d": 100, "chronic_load_28d": 200},
        ])
        mock_agg.get_training_load_trend.side_effect = lambda *a, **kw: next(load_results)

        anomalies = detector.detect_anomalies(end_date=date(2026, 5, 23))

        severities = [a["severity"] for a in anomalies]
        assert len(anomalies) >= 3
        # Verify ordering: all criticals first, then warnings, then infos
        assert severities == sorted(
            severities, key=lambda s: {"critical": 0, "warning": 1, "info": 2}[s]
        )
        assert severities[0] == "critical"
        assert severities[-1] == "info"


# ---------------------------------------------------------------------------
# 4. Default end_date is today
# ---------------------------------------------------------------------------

class TestDefaultEndDate:
    def test_default_end_date_is_today(self, detector, mock_agg):
        _set_all_healthy(mock_agg)

        with patch(
            "garmin_sync.reports.anomaly_detector.date"
        ) as mock_date:
            mock_date.today.return_value = date(2026, 5, 23)
            # Allow normal date construction to still work
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)

            detector.detect_anomalies()  # no end_date argument

            mock_date.today.assert_called_once()


# ---------------------------------------------------------------------------
# 5. Individual check failure does not block others
# ---------------------------------------------------------------------------

class TestCheckIsolation:
    def test_one_check_raising_does_not_block_others(self, detector, mock_agg):
        _set_all_healthy(mock_agg)

        # Make the first check (HRV) explode
        mock_agg.get_hrv_context.side_effect = RuntimeError("DB connection lost")

        # Make spo2 trigger a critical to prove later checks still ran
        mock_agg.get_allday_respiration_spo2.return_value = {
            "avg_spo2": 88.0,
            "min_spo2": 82,
        }

        anomalies = detector.detect_anomalies(end_date=date(2026, 5, 23))

        # spo2_concern should still appear despite hrv_crash failing
        checks = [a["check"] for a in anomalies]
        assert "spo2_concern" in checks
        assert "hrv_crash" not in checks
