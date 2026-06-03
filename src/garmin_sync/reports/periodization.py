"""Training periodization engine.

Detects training phases, calculates readiness scores, and recommends
deload periods based on aggregated Garmin and HEVY data.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from garmin_sync.db.database import Database
from garmin_sync.reports.aggregators import DataAggregator

logger = logging.getLogger(__name__)


class PeriodizationAnalyzer:
    """Analyzes training periodization from synced fitness data.

    Uses ``DataAggregator`` methods to compute phase detection, composite
    readiness scores, and deload recommendations.
    """

    def __init__(self, db: Database) -> None:
        self.agg = DataAggregator(db)

    # ------------------------------------------------------------------
    # Phase detection
    # ------------------------------------------------------------------

    def detect_phase(self, end_date: date | None = None) -> dict:
        """Detect the current training phase from load trends.

        Combines the acute:chronic ratio with week-over-week load
        direction to classify the athlete's current periodization phase.

        Args:
            end_date: Analysis end date.  Defaults to today.

        Returns:
            Dict with ``phase``, ``description``, ``ac_ratio``,
            ``weekly_load_trend``, and ``weeks_in_current_pattern``.
        """
        if end_date is None:
            end_date = date.today()

        result: dict = {
            "phase": "recovery",
            "description": "Insufficient data to determine phase",
            "ac_ratio": None,
            "weekly_load_trend": "insufficient_data",
            "weeks_in_current_pattern": 0,
        }

        try:
            load_trend = self.agg.get_training_load_trend(end_date)
            weekly_history = self.agg.get_weekly_load_history(end_date, weeks=6)

            ac_ratio = load_trend.get("acute_chronic_ratio")
            result["ac_ratio"] = ac_ratio

            # --- Determine weekly load trend ---
            weeks = weekly_history.get("weeks", [])
            trend = self._compute_weekly_trend(weeks)
            result["weekly_load_trend"] = trend

            # --- Consecutive weeks in current pattern ---
            result["weeks_in_current_pattern"] = self._count_pattern_weeks(
                weeks, trend
            )

            # --- Phase classification ---
            if ac_ratio is None:
                result["phase"] = "recovery"
                result["description"] = (
                    "No acute:chronic ratio available; defaulting to recovery"
                )
            elif ac_ratio > 1.5:
                result["phase"] = "overload"
                result["description"] = (
                    f"A:C ratio of {ac_ratio:.2f} exceeds 1.5 — training "
                    "stress is significantly above chronic baseline"
                )
            elif ac_ratio >= 1.3:
                result["phase"] = "peak"
                result["description"] = (
                    f"A:C ratio of {ac_ratio:.2f} indicates a peaking phase "
                    "with elevated but manageable load"
                )
            elif ac_ratio >= 1.0 and trend == "rising":
                result["phase"] = "build"
                result["description"] = (
                    f"A:C ratio of {ac_ratio:.2f} with rising weekly load — "
                    "progressive overload build phase"
                )
            elif ac_ratio >= 0.8:
                result["phase"] = "base"
                result["description"] = (
                    f"A:C ratio of {ac_ratio:.2f} suggests a stable base-"
                    "building phase"
                )
            else:
                result["phase"] = "recovery"
                result["description"] = (
                    f"A:C ratio of {ac_ratio:.2f} is below 0.8 — load is "
                    "well below chronic average, indicating recovery or "
                    "detraining"
                )

        except Exception:
            # Any upstream failure should not propagate; return safe defaults.
            logger.warning("Phase detection failed", exc_info=True)

        return result

    # ------------------------------------------------------------------
    # Readiness score
    # ------------------------------------------------------------------

    def calculate_readiness_score(self, end_date: date | None = None) -> dict:
        """Compute a composite 0-100 readiness score from multiple signals.

        Without HEVY data (5 components, max 100):
          - HRV delta from baseline  (25 pts)
          - Sleep score              (20 pts)
          - Body battery morning high(20 pts)
          - Resting HR delta         (15 pts, inverted)
          - A:C ratio proximity to 1 (20 pts)

        With HEVY data (6 components, max 100):
          - HRV delta from baseline  (20 pts)
          - Sleep score              (20 pts)
          - Body battery morning high(20 pts)
          - Resting HR delta         (15 pts, inverted)
          - A:C ratio proximity to 1 (15 pts)
          - Strength fatigue         (10 pts, penalty-based)

        Args:
            end_date: Analysis end date.  Defaults to today.

        Returns:
            Dict with ``score``, ``signal`` (green/yellow/red), and
            per-component breakdown in ``components``.
        """
        if end_date is None:
            end_date = date.today()

        has_hevy = self._has_hevy_data()

        if has_hevy:
            components: dict = {
                "hrv": {"value": None, "score": 0, "max": 20, "detail": "insufficient data"},
                "sleep": {"value": None, "score": 0, "max": 20, "detail": "insufficient data"},
                "body_battery": {"value": None, "score": 0, "max": 20, "detail": "insufficient data"},
                "resting_hr": {"value": None, "score": 0, "max": 15, "detail": "insufficient data"},
                "ac_ratio": {"value": None, "score": 0, "max": 15, "detail": "insufficient data"},
                "strength_fatigue": {"value": None, "score": 0, "max": 10, "detail": "insufficient data"},
            }
        else:
            components = {
                "hrv": {"value": None, "score": 0, "max": 25, "detail": "insufficient data"},
                "sleep": {"value": None, "score": 0, "max": 20, "detail": "insufficient data"},
                "body_battery": {"value": None, "score": 0, "max": 20, "detail": "insufficient data"},
                "resting_hr": {"value": None, "score": 0, "max": 15, "detail": "insufficient data"},
                "ac_ratio": {"value": None, "score": 0, "max": 20, "detail": "insufficient data"},
            }

        try:
            self._score_hrv(end_date, components)
        except Exception:
            logger.debug("Readiness: HRV scoring failed", exc_info=True)

        try:
            self._score_sleep(end_date, components)
        except Exception:
            logger.debug("Readiness: sleep scoring failed", exc_info=True)

        try:
            self._score_body_battery(end_date, components)
        except Exception:
            logger.debug("Readiness: body battery scoring failed", exc_info=True)

        try:
            self._score_resting_hr(end_date, components)
        except Exception:
            logger.debug("Readiness: resting HR scoring failed", exc_info=True)

        try:
            self._score_ac_ratio(end_date, components)
        except Exception:
            logger.debug("Readiness: A:C ratio scoring failed", exc_info=True)

        if has_hevy:
            try:
                self._score_strength_fatigue(end_date, components)
            except Exception:
                logger.debug("Readiness: strength fatigue scoring failed", exc_info=True)

        total = sum(c["score"] for c in components.values())

        if total >= 70:
            signal = "green"
        elif total >= 50:
            signal = "yellow"
        else:
            signal = "red"

        return {
            "score": total,
            "signal": signal,
            "components": components,
        }

    # ------------------------------------------------------------------
    # Deload recommendation
    # ------------------------------------------------------------------

    def recommend_deload(self, end_date: date | None = None) -> dict:
        """Determine whether a deload week is warranted.

        A deload is recommended when at least 3 consecutive recent weeks
        exceed 120 % of the 6-week average load **and** recovery markers
        show decline (HRV, RHR, or body battery).

        NOTE: these specific cutoffs (3 weeks, 120 %) are a practical heuristic
        consistent with accumulated-fatigue/overreaching monitoring, not a
        single validated threshold — treat the recommendation as a nudge.

        Args:
            end_date: Analysis end date.  Defaults to today.

        Returns:
            Dict with ``recommended``, ``reason``, ``weeks_of_overload``,
            ``recovery_declining``, and ``suggested_volume_pct``.
        """
        if end_date is None:
            end_date = date.today()

        result: dict = {
            "recommended": False,
            "reason": None,
            "weeks_of_overload": 0,
            "recovery_declining": False,
            "suggested_volume_pct": None,
        }

        try:
            weekly_history = self.agg.get_weekly_load_history(end_date, weeks=6)
            weeks = weekly_history.get("weeks", [])

            # --- Count consecutive overload weeks from most recent ---
            overload_weeks = self._count_overload_weeks(weeks)
            result["weeks_of_overload"] = overload_weeks

            # --- Check recovery decline ---
            recovery_declining = self._check_recovery_declining(end_date)
            result["recovery_declining"] = recovery_declining

            # --- Decision ---
            if overload_weeks >= 3 and recovery_declining:
                result["recommended"] = True
                result["suggested_volume_pct"] = 55
                result["reason"] = (
                    f"{overload_weeks} consecutive weeks above 120% of "
                    "6-week average load with declining recovery markers"
                )

        except Exception:
            logger.debug("Deload recommendation failed", exc_info=True)

        return result

    # ------------------------------------------------------------------
    # Combined summary
    # ------------------------------------------------------------------

    def get_periodization_summary(self, end_date: date | None = None) -> dict:
        """Return phase, readiness, and deload data in a single call.

        Args:
            end_date: Analysis end date.  Defaults to today.

        Returns:
            Dict with ``phase``, ``readiness``, and ``deload`` sub-dicts.
        """
        if end_date is None:
            end_date = date.today()

        return {
            "phase": self.detect_phase(end_date),
            "readiness": self.calculate_readiness_score(end_date),
            "deload": self.recommend_deload(end_date),
        }

    # ==================================================================
    # Private helpers
    # ==================================================================

    @staticmethod
    def _compute_weekly_trend(weeks: list[dict]) -> str:
        """Classify the recent weekly load direction.

        Compares the average of the last 2 weeks to the average of the
        prior weeks.  Returns ``"rising"``, ``"falling"``, ``"steady"``,
        or ``"insufficient_data"``.
        """
        if len(weeks) < 3:
            return "insufficient_data"

        recent = weeks[-2:]
        prior = weeks[:-2]

        recent_avg = sum(w["total_load"] for w in recent) / len(recent)
        prior_avg = sum(w["total_load"] for w in prior) / len(prior)

        if prior_avg == 0:
            return "rising" if recent_avg > 0 else "steady"

        change_pct = ((recent_avg - prior_avg) / prior_avg) * 100

        if change_pct > 10:
            return "rising"
        if change_pct < -10:
            return "falling"
        return "steady"

    @staticmethod
    def _count_pattern_weeks(weeks: list[dict], trend: str) -> int:
        """Count consecutive weeks from the end that match *trend*.

        For ``"rising"`` each week must be higher than the previous;
        for ``"falling"`` each week must be lower; for ``"steady"`` the
        week-to-week change must be within 10 %.
        """
        if len(weeks) < 2 or trend == "insufficient_data":
            return 0

        count = 0
        for i in range(len(weeks) - 1, 0, -1):
            cur = weeks[i]["total_load"]
            prev = weeks[i - 1]["total_load"]

            if prev == 0:
                # Avoid division by zero; only count if both are zero
                # (steady) or current is positive (rising).
                if trend == "rising" and cur > 0:
                    count += 1
                    continue
                if trend == "steady" and cur == 0:
                    count += 1
                    continue
                break

            week_change = ((cur - prev) / prev) * 100

            if trend == "rising" and week_change > 0:
                count += 1
            elif trend == "falling" and week_change < 0:
                count += 1
            elif trend == "steady" and abs(week_change) <= 10:
                count += 1
            else:
                break

        return count

    @staticmethod
    def _count_overload_weeks(weeks: list[dict]) -> int:
        """Count consecutive recent weeks above 120 % of baseline.

        The baseline is computed from the *earlier* weeks (everything
        before the trailing overload run) to avoid the circular problem
        where heavy recent weeks inflate the average and hide their own
        overload.  Falls back to the full-window average only when all
        weeks are above the threshold.
        """
        if not weeks or len(weeks) < 2:
            return 0

        total_avg = sum(w["total_load"] for w in weeks) / len(weeks)
        if total_avg <= 0:
            return 0

        # First pass with full-window average to find the trailing run.
        threshold = total_avg * 1.2
        count = 0
        for w in reversed(weeks):
            if w["total_load"] > threshold:
                count += 1
            else:
                break

        # Second pass: recompute baseline from just the non-overload
        # (earlier) weeks so heavy recent weeks don't inflate it.
        if 0 < count < len(weeks):
            baseline_weeks = weeks[: len(weeks) - count]
            baseline_avg = (
                sum(w["total_load"] for w in baseline_weeks) / len(baseline_weeks)
            )
            if baseline_avg <= 0:
                return count
            threshold = baseline_avg * 1.2
            count = 0
            for w in reversed(weeks):
                if w["total_load"] > threshold:
                    count += 1
                else:
                    break

        return count

    def _check_recovery_declining(self, end_date: date) -> bool:
        """Return ``True`` if any major recovery marker shows decline."""
        # HRV delta < -10%
        try:
            hrv = self.agg.get_hrv_context(end_date)
            delta = hrv.get("delta_from_baseline")
            if delta is not None and delta < -10:
                return True
        except Exception:
            logger.debug("Recovery check: HRV lookup failed", exc_info=True)

        # RHR delta > +3 bpm
        try:
            rhr = self.agg.get_resting_hr_trend(end_date)
            rhr_delta = rhr.get("delta")
            if rhr_delta is not None and rhr_delta > 3:
                return True
        except Exception:
            logger.debug("Recovery check: RHR lookup failed", exc_info=True)

        # Body battery morning high < 40
        try:
            start = end_date - timedelta(days=6)
            bb = self.agg.get_body_battery_recovery(start, end_date)
            morning = bb.get("avg_morning_high")
            if morning is not None and morning < 40:
                return True
        except Exception:
            logger.debug("Recovery check: body battery lookup failed", exc_info=True)

        return False

    # --- Component scorers for readiness ---

    def _score_hrv(self, end_date: date, components: dict) -> None:
        """Score HRV component (max from components dict).

        Uses the smoothed 7-day-rolling-mean delta vs the longer baseline, and
        anchors the scoring ramp to the athlete's own variability: a drop within
        the smallest worthwhile change (~0.5x CV) is normal noise (full points),
        scaling to zero by ~2x CV below baseline. Falls back to a fixed -20%
        ramp when there isn't enough data to estimate CV (Plews & Buchheit).
        """
        hrv = self.agg.get_hrv_context(end_date)
        delta = hrv.get("delta_from_baseline")
        if delta is None:
            return

        max_pts = components["hrv"]["max"]
        components["hrv"]["value"] = delta
        swc = hrv.get("swc_pct")
        cv = hrv.get("cv_pct")

        if swc is not None and cv is not None and cv > 0:
            # Personalized: full above -SWC, zero at/below -(2*CV), linear between.
            hi, lo = -swc, -(2 * cv)
            if delta >= hi:
                score = max_pts
            elif delta <= lo:
                score = 0
            else:
                score = max_pts * (delta - lo) / (hi - lo)
            detail = (
                f"HRV 7d mean {delta:+.1f}% vs baseline "
                f"(personal SWC ±{swc:.1f}%, CV {cv:.1f}%)"
            )
        else:
            # Fallback: full at >=0, linear to 0 at -20%.
            score = max_pts if delta >= 0 else max(0, max_pts + (delta * max_pts / 20))
            detail = f"HRV 7d mean {delta:+.1f}% vs baseline"

        components["hrv"]["score"] = int(min(max_pts, max(0, score)))
        components["hrv"]["detail"] = detail

    def _score_sleep(self, end_date: date, components: dict) -> None:
        """Score sleep component (max 20 pts)."""
        sleep = self.agg.get_sleep_score_history(end_date, days=7)
        mean_score = sleep.get("mean")
        if mean_score is None or mean_score == 0:
            return

        components["sleep"]["value"] = mean_score
        score = int(min(20, max(0, (mean_score / 100) * 20)))
        components["sleep"]["score"] = score
        components["sleep"]["detail"] = f"7d avg sleep score {mean_score:.0f}/100"

    def _score_body_battery(self, end_date: date, components: dict) -> None:
        """Score body battery component (max 20 pts)."""
        start = end_date - timedelta(days=6)
        bb = self.agg.get_body_battery_recovery(start, end_date)
        morning = bb.get("avg_morning_high")
        if morning is None:
            return

        components["body_battery"]["value"] = morning
        score = int(min(20, max(0, (morning / 100) * 20)))
        components["body_battery"]["score"] = score
        components["body_battery"]["detail"] = f"Avg morning body battery {morning}"

    def _score_resting_hr(self, end_date: date, components: dict) -> None:
        """Score resting HR component (max 15 pts, inverted)."""
        rhr = self.agg.get_resting_hr_trend(end_date)
        delta = rhr.get("delta")
        if delta is None:
            return

        components["resting_hr"]["value"] = delta
        # 0 bpm above baseline -> 15 pts, +5 bpm -> 0 pts
        # Negative delta (below baseline) -> 15 pts
        if delta <= 0:
            score = 15
        else:
            score = max(0, 15 - (delta * 3))

        score = int(min(15, max(0, score)))
        components["resting_hr"]["score"] = score
        components["resting_hr"]["detail"] = f"RHR {delta:+d} bpm from 28d baseline"

    def _score_ac_ratio(self, end_date: date, components: dict) -> None:
        """Score A:C ratio proximity component (max from components dict)."""
        load = self.agg.get_training_load_trend(end_date)
        ratio = load.get("acute_chronic_ratio")
        if ratio is None:
            return

        max_pts = components["ac_ratio"]["max"]
        components["ac_ratio"]["value"] = ratio
        # At 1.0 -> max pts, at 0.5 or 1.5 -> 0 pts
        score = max(0, max_pts - abs(ratio - 1.0) * (max_pts * 2))
        score = int(min(max_pts, max(0, score)))
        components["ac_ratio"]["score"] = score
        components["ac_ratio"]["detail"] = f"A:C ratio {ratio:.2f} (optimal ~1.0)"

    def _score_strength_fatigue(self, end_date: date, components: dict) -> None:
        """Score strength fatigue component (max 10 pts, penalty-based).

        Checks recent strength training patterns for fatigue signals:
        - Strength session in the last 24 h
        - Same muscle groups trained on consecutive days
        - High frequency (3+ sessions in 5 days)
        """
        max_pts = components["strength_fatigue"]["max"]
        score = max_pts
        penalties: list[str] = []

        cursor = self.agg.db.connection.cursor()

        # Workouts in the last 5 days
        start_5d = (end_date - timedelta(days=4)).isoformat()
        ed = end_date.isoformat()
        yesterday = (end_date - timedelta(days=1)).isoformat()

        cursor.execute(
            """
            SELECT id, date(start_time) as workout_date
            FROM hevy_workouts
            WHERE date(start_time) BETWEEN ? AND ?
            ORDER BY start_time DESC
            """,
            (start_5d, ed),
        )
        recent_workouts = cursor.fetchall()

        if not recent_workouts:
            # No recent strength training — full points
            components["strength_fatigue"]["value"] = "no_recent_sessions"
            components["strength_fatigue"]["score"] = max_pts
            components["strength_fatigue"]["detail"] = "No recent strength sessions"
            return

        # Penalty: session in last 24h
        dates = [r["workout_date"] for r in recent_workouts]
        if ed in dates or yesterday in dates:
            score -= 3
            penalties.append("session in last 24h")

        # Penalty: same muscle groups on consecutive days
        if len(dates) >= 2 and self._consecutive_muscle_overlap(cursor, recent_workouts):
            score -= 5
            penalties.append("same muscles on consecutive days")

        # Penalty: high frequency
        if len(recent_workouts) >= 3:
            score -= 2
            penalties.append(f"{len(recent_workouts)} sessions in 5 days")

        score = max(0, score)
        components["strength_fatigue"]["value"] = len(recent_workouts)
        components["strength_fatigue"]["score"] = score
        detail = f"{len(recent_workouts)} sessions in 5d"
        if penalties:
            detail += f" ({', '.join(penalties)})"
        components["strength_fatigue"]["detail"] = detail

    @staticmethod
    def _consecutive_muscle_overlap(cursor, workouts: list) -> bool:
        """Check if any two consecutive-day workouts share muscle groups."""
        by_date: dict[str, set[str]] = {}
        for w in workouts:
            d = w["workout_date"]
            if d not in by_date:
                by_date[d] = set()
            cursor.execute(
                "SELECT DISTINCT muscle_group FROM hevy_exercises WHERE workout_id = ?",
                (w["id"],),
            )
            by_date[d].update(
                row[0] for row in cursor.fetchall() if row[0]
            )

        sorted_dates = sorted(by_date.keys())
        for i in range(len(sorted_dates) - 1):
            d1, d2 = sorted_dates[i], sorted_dates[i + 1]
            # Check if consecutive calendar days
            from datetime import date as dt_date
            date1 = dt_date.fromisoformat(d1)
            date2 = dt_date.fromisoformat(d2)
            if (date2 - date1).days == 1:
                if by_date[d1] & by_date[d2]:
                    return True
        return False

    def _has_hevy_data(self) -> bool:
        """Check if the hevy_workouts table exists and has data."""
        try:
            cursor = self.agg.db.connection.cursor()
            cursor.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name='hevy_workouts'"
            )
            if not cursor.fetchone():
                return False
            cursor.execute("SELECT COUNT(*) FROM hevy_workouts LIMIT 1")
            return cursor.fetchone()[0] > 0
        except Exception:
            return False
