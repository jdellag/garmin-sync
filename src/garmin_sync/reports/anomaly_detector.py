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
            self._check_overreaching,
            self._check_spo2_concern,
            self._check_strength_overload,
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
        """Flag a warning when the HRV trend drops meaningfully below baseline.

        Uses the smoothed 7-day-rolling-mean delta vs the longer baseline, with a
        PERSONALIZED trigger: a drop beyond ~1x the athlete's own CV (= 2x the
        smallest worthwhile change) is a clear, sustained suppression. Falls back
        to a fixed -15% when there isn't enough data to estimate CV. Also flags
        3+ consecutive nights below the 7-day mean.
        """
        ctx = self.agg.get_hrv_context(end_date)

        delta = ctx.get("delta_from_baseline")
        days_below = ctx.get("days_below_baseline", 0)
        cv = ctx.get("cv_pct")
        # Personalized threshold (1x CV below baseline) or fixed -15% fallback.
        threshold = -cv if cv is not None and cv > 0 else -15.0

        if delta is not None and delta < threshold:
            return [
                {
                    "check": "hrv_crash",
                    "severity": "warning",
                    "message": (
                        f"HRV trend is down: 7-day mean is {abs(delta):.0f}% below your "
                        f"baseline (beyond your normal day-to-day variability)"
                    ),
                    "data": {
                        "delta_from_baseline": delta,
                        "trigger_threshold_pct": round(threshold, 1),
                        "cv_pct": cv,
                        "days_below_baseline": days_below,
                        "baseline_7d": ctx.get("baseline_7d"),
                        "baseline_28d": ctx.get("baseline_28d"),
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
        """Flag a rapid load ramp (acute:chronic ratio > 1.5).

        This is a descriptive ramp-rate signal, NOT an injury prediction: the
        ACWR has no validated injury "danger zone" (Impellizzeri et al. 2020),
        so it's surfaced as a warning to check recovery, not a critical alarm.
        """
        load = self.agg.get_training_load_trend(end_date)

        ratio = load.get("acute_chronic_ratio")
        # Requires an established (uncoupled) baseline; the aggregator leaves the
        # ratio undefined when all load sits in the last 7 days.
        if ratio is not None and ratio > 1.5 and load.get("chronic_baseline_load"):
            return [
                {
                    "check": "training_overload",
                    "severity": "warning",
                    "message": (
                        f"Training load ramped fast: last 7d is {ratio:.1f}x your "
                        f"prior 3-week weekly average — monitor recovery if it stays high"
                    ),
                    "data": {
                        "acute_chronic_ratio": ratio,
                        "acute_load_7d": load.get("acute_load_7d"),
                        "chronic_baseline_weekly": load.get("chronic_baseline_weekly"),
                    },
                }
            ]

        return []

    def _check_training_detraining(self, end_date: date) -> list[dict]:
        """Flag info when recent load drops well below the recent baseline (A:C < 0.8)."""
        load = self.agg.get_training_load_trend(end_date)

        ratio = load.get("acute_chronic_ratio")
        if ratio is not None and ratio < 0.8:
            return [
                {
                    "check": "training_detraining",
                    "severity": "info",
                    "message": (
                        f"Training load is down: last 7d is {ratio:.1f}x your prior "
                        f"3-week weekly average (intentional if tapering/resting)"
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

    def _check_strength_overload(self, end_date: date) -> list[dict]:
        """Flag when strength-specific A:C ratio exceeds 1.5.

        Catches sudden lifting volume spikes that the overall A:C ratio
        might mask if cardio load is low or stable.  Silently returns
        empty when HEVY data is absent.
        """
        cursor = self.db.connection.cursor()

        # Check if table exists and has training_load data
        cursor.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='hevy_workouts'"
        )
        if not cursor.fetchone():
            return []

        # Acute (7d) and chronic (28d) strength loads
        start_7d = (end_date - timedelta(days=6)).isoformat()
        start_28d = (end_date - timedelta(days=27)).isoformat()
        ed = end_date.isoformat()

        cursor.execute(
            """
            SELECT date(start_time) as d, training_load
            FROM hevy_workouts
            WHERE date(start_time) BETWEEN ? AND ?
                AND training_load IS NOT NULL
            """,
            (start_28d, ed),
        )
        rows = cursor.fetchall()
        if not rows:
            return []

        acute = sum(
            r["training_load"] for r in rows
            if r["d"] >= start_7d and r["training_load"]
        )

        # Uncoupled chronic: weekly average of the prior 3 weeks (days 8-28),
        # EXCLUDING the acute window so the ratio isn't mathematically coupled
        # (Lolli et al. 2019). If there's no load before the acute window there
        # is no baseline to compare against, so we don't flag.
        baseline = sum(
            r["training_load"] for r in rows
            if r["d"] < start_7d and r["training_load"]
        )
        if baseline <= 0:
            return []
        chronic_weekly = baseline / 3

        strength_ac = round(acute / chronic_weekly, 2)

        # Descriptive load-ramp signal, not an injury prediction (the ACWR
        # injury "sweet spot" is unsupported — Impellizzeri 2020). Reported as
        # an informational nudge to check recovery, not a critical alarm.
        if strength_ac > 1.5:
            return [
                {
                    "check": "strength_overload",
                    "severity": "info",
                    "message": (
                        f"Strength load ramped fast: last 7d is {strength_ac:.1f}x "
                        f"your prior 3-week weekly average "
                        f"(acute {acute:.0f} / weekly avg {chronic_weekly:.0f}) "
                        "— worth checking recovery if it stays elevated"
                    ),
                    "data": {
                        "strength_ac_ratio": strength_ac,
                        "acute_strength_7d": round(acute, 1),
                        "chronic_strength_weekly": round(chronic_weekly, 1),
                    },
                }
            ]

        return []
