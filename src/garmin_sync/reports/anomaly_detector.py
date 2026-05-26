"""Anomaly detection engine for fitness and health metrics.

Scans recent data for concerning patterns (HRV crashes, training overload,
sleep degradation, etc.) and returns prioritised anomaly dicts that the
CLI or AI tools can surface to the user.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

from garmin_sync.db.database import Database
from garmin_sync.reports.aggregators import DataAggregator

logger = logging.getLogger(__name__)

_SEVERITY_ORDER: dict[str, int] = {"critical": 0, "warning": 1, "info": 2}


class AnomalyDetector:
    """Detect anomalies across health and training metrics.

    Wraps :class:`DataAggregator` and runs a battery of checks against
    recent data.  Each check returns zero or one anomaly dict; the
    public :meth:`detect_anomalies` entry point collects them all and
    returns a severity-sorted list.

    Args:
        db: An initialised :class:`Database` instance.
    """

    def __init__(self, db: Database) -> None:
        self.db = db
        self.agg = DataAggregator(db)

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def detect_anomalies(self, end_date: Optional[date] = None) -> list[dict]:
        """Run all anomaly checks and return results sorted by severity.

        Args:
            end_date: Reference date for lookback windows.  Defaults to
                today when *None*.

        Returns:
            List of anomaly dicts, each containing:
            - ``check``  : identifier for the check that fired
            - ``severity``: ``"critical"``, ``"warning"``, or ``"info"``
            - ``message`` : human-readable description
            - ``data``    : supporting metric values
        """
        if end_date is None:
            end_date = date.today()

        checks = [
            self._check_hrv_crash,
            self._check_rhr_spike,
            self._check_training_overload,
            self._check_training_detraining,
            self._check_sleep_degradation,
            self._check_body_battery_depleted,
            self._check_stress_recovery,
            self._check_overreaching,
            self._check_spo2_concern,
        ]

        anomalies: list[dict] = []
        for check in checks:
            try:
                anomalies.extend(check(end_date))
            except Exception:
                # Individual check failures must never block other checks.
                logger.debug("Anomaly check %s failed", check.__name__, exc_info=True)
                continue

        anomalies.sort(key=lambda a: _SEVERITY_ORDER.get(a["severity"], 99))
        return anomalies

    # ------------------------------------------------------------------
    # Private check methods
    # ------------------------------------------------------------------

    def _check_hrv_crash(self, end_date: date) -> list[dict]:
        """Flag a warning when HRV drops significantly below baseline.

        Triggers when the delta from the 7-day baseline exceeds -15 % or
        when HRV has been below baseline for 3+ consecutive days.
        """
        ctx = self.agg.get_hrv_context(end_date)

        delta = ctx.get("delta_from_baseline")
        days_below = ctx.get("days_below_baseline", 0)

        if delta is not None and delta < -15:
            return [
                {
                    "check": "hrv_crash",
                    "severity": "warning",
                    "message": (
                        f"HRV dropped {abs(delta):.0f}% below your 7-day baseline "
                        f"(baseline {ctx.get('baseline_7d')}, last night {ctx.get('last_night')})"
                    ),
                    "data": {
                        "delta_from_baseline": delta,
                        "days_below_baseline": days_below,
                        "baseline_7d": ctx.get("baseline_7d"),
                        "last_night": ctx.get("last_night"),
                    },
                }
            ]

        if days_below >= 3:
            return [
                {
                    "check": "hrv_crash",
                    "severity": "warning",
                    "message": (
                        f"HRV has been below your 7-day baseline for "
                        f"{days_below} consecutive days"
                    ),
                    "data": {
                        "delta_from_baseline": delta,
                        "days_below_baseline": days_below,
                        "baseline_7d": ctx.get("baseline_7d"),
                        "last_night": ctx.get("last_night"),
                    },
                }
            ]

        return []

    def _check_rhr_spike(self, end_date: date) -> list[dict]:
        """Flag a warning when resting heart rate rises >5 bpm above baseline."""
        trend = self.agg.get_resting_hr_trend(end_date)

        delta = trend.get("delta")
        if delta is not None and delta > 5:
            return [
                {
                    "check": "rhr_spike",
                    "severity": "warning",
                    "message": (
                        f"Resting heart rate is {delta} bpm above your 28-day "
                        f"baseline ({trend.get('current')} vs {trend.get('baseline_28d')} bpm)"
                    ),
                    "data": {
                        "delta": delta,
                        "baseline_28d": trend.get("baseline_28d"),
                        "current": trend.get("current"),
                        "trend": trend.get("trend"),
                    },
                }
            ]

        return []

    def _check_training_overload(self, end_date: date) -> list[dict]:
        """Flag critical when acute:chronic training load ratio exceeds 1.5."""
        load = self.agg.get_training_load_trend(end_date)

        ratio = load.get("acute_chronic_ratio")
        if ratio is not None and ratio > 1.5:
            return [
                {
                    "check": "training_overload",
                    "severity": "critical",
                    "message": (
                        f"Acute:chronic training load ratio is {ratio:.2f} — "
                        f"high injury risk zone (>1.5)"
                    ),
                    "data": {
                        "acute_chronic_ratio": ratio,
                        "acute_load_7d": load.get("acute_load_7d"),
                        "chronic_load_28d": load.get("chronic_load_28d"),
                    },
                }
            ]

        return []

    def _check_training_detraining(self, end_date: date) -> list[dict]:
        """Flag info when acute:chronic ratio drops below 0.8 (detraining)."""
        load = self.agg.get_training_load_trend(end_date)

        ratio = load.get("acute_chronic_ratio")
        if ratio is not None and ratio < 0.8:
            return [
                {
                    "check": "training_detraining",
                    "severity": "info",
                    "message": (
                        f"Acute:chronic training load ratio is {ratio:.2f} — "
                        f"below the 0.8 threshold, possible detraining"
                    ),
                    "data": {
                        "acute_chronic_ratio": ratio,
                    },
                }
            ]

        return []

    def _check_sleep_degradation(self, end_date: date) -> list[dict]:
        """Flag a warning for 3+ consecutive nights with unusually low sleep scores.

        "Low" is defined as more than 1 standard deviation below the
        personal mean over the lookback window (14 days).
        """
        history = self.agg.get_sleep_score_history(end_date, days=14)

        scores = history.get("scores", [])
        mean = history.get("mean", 0.0)
        std = history.get("std", 0.0)

        if not scores or std == 0:
            return []

        threshold = mean - std

        # Walk scores chronologically and find the longest consecutive
        # run below the threshold.
        max_streak = 0
        current_streak = 0
        for entry in scores:
            if entry["score"] < threshold:
                current_streak += 1
                max_streak = max(max_streak, current_streak)
            else:
                current_streak = 0

        if max_streak >= 3:
            return [
                {
                    "check": "sleep_degradation",
                    "severity": "warning",
                    "message": (
                        f"{max_streak} consecutive nights with sleep score "
                        f"below {threshold:.0f} (mean {mean:.0f}, std {std:.1f})"
                    ),
                    "data": {
                        "consecutive_low_nights": max_streak,
                        "mean": mean,
                        "std": std,
                        "threshold": round(threshold, 1),
                    },
                }
            ]

        return []

    def _check_body_battery_depleted(self, end_date: date) -> list[dict]:
        """Flag a warning when morning body battery is critically low for 2+ days."""
        start = end_date - timedelta(days=6)
        bb = self.agg.get_body_battery_recovery(start, end_date)

        daily = bb.get("daily_values", [])
        if not daily:
            return []

        # Sort chronologically (aggregator returns DESC).
        daily_sorted = sorted(daily, key=lambda d: d["date"])

        # Find longest consecutive stretch of morning_high < 25.
        max_streak = 0
        current_streak = 0
        current_highs: list[int] = []
        best_highs: list[int] = []
        for day in daily_sorted:
            mh = day.get("morning_high")
            if mh is not None and mh < 25:
                current_streak += 1
                current_highs.append(mh)
                if current_streak > max_streak:
                    max_streak = current_streak
                    best_highs = list(current_highs)
            else:
                current_streak = 0
                current_highs = []

        if max_streak >= 2:
            avg_mh = round(sum(best_highs) / len(best_highs), 1)
            return [
                {
                    "check": "body_battery_depleted",
                    "severity": "warning",
                    "message": (
                        f"Morning body battery below 25 for {max_streak} "
                        f"consecutive days (avg {avg_mh})"
                    ),
                    "data": {
                        "depleted_days": max_streak,
                        "avg_morning_high": avg_mh,
                    },
                }
            ]

        return []

    def _check_stress_recovery(self, end_date: date) -> list[dict]:
        """Flag a warning when high-stress/poor-recovery days accumulate."""
        start = end_date - timedelta(days=6)
        corr = self.agg.get_stress_recovery_correlation(start, end_date)

        bad_days = corr.get("high_stress_poor_recovery_days", 0)
        if bad_days >= 3:
            return [
                {
                    "check": "stress_recovery",
                    "severity": "warning",
                    "message": (
                        f"{bad_days} high-stress / poor-recovery days in "
                        f"the past week"
                    ),
                    "data": {
                        "high_stress_poor_recovery_days": bad_days,
                        "avg_stress_training_days": corr.get(
                            "avg_stress_training_days"
                        ),
                    },
                }
            ]

        return []

    def _check_overreaching(self, end_date: date) -> list[dict]:
        """Flag a warning when RPE analysis indicates overreaching."""
        rpe = self.agg.get_rpe_analysis(days=14)

        if rpe.get("overreaching_flag"):
            return [
                {
                    "check": "overreaching",
                    "severity": "warning",
                    "message": (
                        "RPE trend suggests overreaching — perceived effort "
                        f"rising (avg RPE {rpe.get('overall_avg_rpe')}) while "
                        "volume is flat or falling"
                    ),
                    "data": {
                        "overall_avg_rpe": rpe.get("overall_avg_rpe"),
                        "overreaching_flag": rpe.get("overreaching_flag"),
                    },
                }
            ]

        return []

    def _check_spo2_concern(self, end_date: date) -> list[dict]:
        """Flag critical when average SpO2 drops below 92%."""
        start = end_date - timedelta(days=6)
        resp = self.agg.get_allday_respiration_spo2(start, end_date)

        avg_spo2 = resp.get("avg_spo2")
        if avg_spo2 is not None and avg_spo2 < 92:
            return [
                {
                    "check": "spo2_concern",
                    "severity": "critical",
                    "message": (
                        f"Average SpO2 over the past week is {avg_spo2:.1f}% "
                        f"(below 92% threshold)"
                    ),
                    "data": {
                        "avg_spo2": avg_spo2,
                        "min_spo2": resp.get("min_spo2"),
                    },
                }
            ]

        return []
