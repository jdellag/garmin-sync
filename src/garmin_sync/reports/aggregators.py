"""Data aggregation functions for reports."""

import calendar
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Optional

from garmin_sync.db.database import Database


@dataclass
class ActivitySummary:
    """Summary of activities for a period."""

    total_count: int = 0
    total_duration_seconds: float = 0
    total_distance_meters: float = 0
    total_calories: int = 0
    avg_hr: Optional[float] = None
    max_hr: Optional[int] = None

    # By activity type
    by_type: dict = field(default_factory=dict)

    @property
    def total_duration_hours(self) -> float:
        return self.total_duration_seconds / 3600

    @property
    def total_distance_km(self) -> float:
        return self.total_distance_meters / 1000


@dataclass
class HealthSummary:
    """Summary of health metrics for a period."""

    # Steps
    avg_steps: Optional[int] = None
    total_steps: Optional[int] = None
    step_goal_pct: Optional[float] = None

    # Sleep (basic)
    avg_sleep_seconds: Optional[int] = None
    avg_sleep_score: Optional[int] = None
    avg_deep_sleep_pct: Optional[float] = None

    # Sleep (enhanced - requires detailed sync)
    avg_rem_sleep_pct: Optional[float] = None
    avg_awake_during_sleep_mins: Optional[float] = None
    sleep_time_variance_mins: Optional[float] = None
    wake_time_variance_mins: Optional[float] = None

    # Heart Rate (basic)
    avg_resting_hr: Optional[int] = None
    min_resting_hr: Optional[int] = None
    max_resting_hr: Optional[int] = None

    # Heart Rate (enhanced trends)
    resting_hr_baseline_28d: Optional[int] = None
    resting_hr_delta: Optional[int] = None
    resting_hr_trend: Optional[str] = None  # "rising", "stable", "falling"

    # Stress
    avg_stress: Optional[int] = None

    # HRV (basic)
    avg_hrv: Optional[float] = None

    # HRV (enhanced context)
    hrv_baseline_7d: Optional[float] = None
    hrv_baseline_28d: Optional[float] = None
    hrv_last_night: Optional[float] = None
    hrv_delta_from_baseline: Optional[float] = None
    hrv_days_below_baseline: int = 0
    hrv_status: Optional[str] = None  # BALANCED, UNBALANCED, LOW, etc.

    # Body Battery (basic)
    avg_morning_bb: Optional[int] = None
    avg_evening_bb: Optional[int] = None

    # Body Battery (enhanced recovery)
    avg_overnight_recovery: Optional[int] = None

    # Training Load
    weekly_training_load: Optional[float] = None
    prev_week_training_load: Optional[float] = None
    training_load_change_pct: Optional[float] = None
    acute_load_7d: Optional[float] = None
    chronic_load_28d: Optional[float] = None
    acute_chronic_ratio: Optional[float] = None

    # Training Readiness
    training_readiness_score: Optional[int] = None
    training_readiness_level: Optional[str] = None
    training_readiness_feedback: Optional[str] = None

    @property
    def avg_sleep_hours(self) -> Optional[float]:
        if self.avg_sleep_seconds:
            return self.avg_sleep_seconds / 3600
        return None


@dataclass
class PeriodComparison:
    """Comparison between two periods."""

    current: dict
    previous: dict
    changes: dict = field(default_factory=dict)

    def calculate_changes(self):
        """Calculate percentage changes between periods."""
        for key in self.current:
            curr = self.current.get(key)
            prev = self.previous.get(key)

            if curr is not None and prev is not None and prev != 0:
                change = ((curr - prev) / prev) * 100
                self.changes[key] = round(change, 1)
            else:
                self.changes[key] = None


class DataAggregator:
    """Aggregates data from database for reports."""

    def __init__(self, db: Database):
        self.db = db

        # Lazy import to avoid circular dependency at module level.
        from garmin_sync.db.repository import Repository  # noqa: E402

        self.repo = Repository(db)

    def get_activity_summary(
        self,
        start_date: date,
        end_date: date,
    ) -> ActivitySummary:
        """Get activity summary for date range."""
        cursor = self.db.connection.cursor()

        # Overall stats
        cursor.execute(
            """
            SELECT
                COUNT(*) as count,
                COALESCE(SUM(duration_seconds), 0) as total_duration,
                COALESCE(SUM(distance_meters), 0) as total_distance,
                COALESCE(SUM(calories), 0) as total_calories,
                AVG(average_hr) as avg_hr,
                MAX(max_hr) as max_hr
            FROM activities
            WHERE date(start_time) >= ? AND date(start_time) <= ?
            """,
            (start_date.isoformat(), end_date.isoformat())
        )
        row = cursor.fetchone()

        summary = ActivitySummary(
            total_count=row["count"] or 0,
            total_duration_seconds=row["total_duration"] or 0,
            total_distance_meters=row["total_distance"] or 0,
            total_calories=row["total_calories"] or 0,
            avg_hr=round(row["avg_hr"], 1) if row["avg_hr"] else None,
            max_hr=row["max_hr"],
        )

        # By activity type
        cursor.execute(
            """
            SELECT
                activity_type,
                COUNT(*) as count,
                COALESCE(SUM(duration_seconds), 0) as total_duration,
                COALESCE(SUM(distance_meters), 0) as total_distance,
                AVG(average_hr) as avg_hr
            FROM activities
            WHERE date(start_time) >= ? AND date(start_time) <= ?
            GROUP BY activity_type
            ORDER BY count DESC
            """,
            (start_date.isoformat(), end_date.isoformat())
        )

        for row in cursor.fetchall():
            activity_type = row["activity_type"] or "unknown"
            summary.by_type[activity_type] = {
                "count": row["count"],
                "duration_seconds": row["total_duration"],
                "distance_meters": row["total_distance"],
                "avg_hr": round(row["avg_hr"], 1) if row["avg_hr"] else None,
            }

        return summary

    def get_health_summary(
        self,
        start_date: date,
        end_date: date,
    ) -> HealthSummary:
        """Get health metrics summary for date range."""
        cursor = self.db.connection.cursor()
        summary = HealthSummary()

        # Daily summary stats (steps, calories)
        cursor.execute(
            """
            SELECT
                AVG(total_steps) as avg_steps,
                SUM(total_steps) as total_steps,
                AVG(CAST(total_steps AS FLOAT) / NULLIF(step_goal, 0) * 100) as step_goal_pct
            FROM daily_summaries
            WHERE date >= ? AND date <= ?
            """,
            (start_date.isoformat(), end_date.isoformat())
        )
        row = cursor.fetchone()
        if row:
            summary.avg_steps = int(row["avg_steps"]) if row["avg_steps"] else None
            summary.total_steps = int(row["total_steps"]) if row["total_steps"] else None
            summary.step_goal_pct = round(row["step_goal_pct"], 1) if row["step_goal_pct"] else None

        # Sleep stats
        cursor.execute(
            """
            SELECT
                AVG(total_sleep_seconds) as avg_sleep,
                AVG(sleep_score) as avg_score,
                AVG(CAST(deep_sleep_seconds AS FLOAT) / NULLIF(total_sleep_seconds, 0) * 100) as deep_pct
            FROM sleep_daily
            WHERE date >= ? AND date <= ?
            """,
            (start_date.isoformat(), end_date.isoformat())
        )
        row = cursor.fetchone()
        if row:
            summary.avg_sleep_seconds = int(row["avg_sleep"]) if row["avg_sleep"] else None
            summary.avg_sleep_score = int(row["avg_score"]) if row["avg_score"] else None
            summary.avg_deep_sleep_pct = round(row["deep_pct"], 1) if row["deep_pct"] else None

        # Heart rate stats
        cursor.execute(
            """
            SELECT
                AVG(resting_hr) as avg_rhr,
                MIN(resting_hr) as min_rhr,
                MAX(resting_hr) as max_rhr
            FROM heart_rate_daily
            WHERE date >= ? AND date <= ? AND resting_hr IS NOT NULL
            """,
            (start_date.isoformat(), end_date.isoformat())
        )
        row = cursor.fetchone()
        if row:
            summary.avg_resting_hr = int(row["avg_rhr"]) if row["avg_rhr"] else None
            summary.min_resting_hr = row["min_rhr"]
            summary.max_resting_hr = row["max_rhr"]

        # Stress stats
        cursor.execute(
            """
            SELECT AVG(avg_stress_level) as avg_stress
            FROM stress_daily
            WHERE date >= ? AND date <= ? AND avg_stress_level IS NOT NULL
            """,
            (start_date.isoformat(), end_date.isoformat())
        )
        row = cursor.fetchone()
        if row and row["avg_stress"]:
            summary.avg_stress = int(row["avg_stress"])

        # HRV stats
        cursor.execute(
            """
            SELECT AVG(hrv_value) as avg_hrv
            FROM hrv_daily
            WHERE date >= ? AND date <= ? AND hrv_value IS NOT NULL
            """,
            (start_date.isoformat(), end_date.isoformat())
        )
        row = cursor.fetchone()
        if row and row["avg_hrv"]:
            summary.avg_hrv = round(row["avg_hrv"], 1)

        # Body Battery stats
        cursor.execute(
            """
            SELECT
                AVG(max_level) as avg_morning,
                AVG(min_level) as avg_evening
            FROM body_battery_daily
            WHERE date >= ? AND date <= ?
            """,
            (start_date.isoformat(), end_date.isoformat())
        )
        row = cursor.fetchone()
        if row:
            summary.avg_morning_bb = int(row["avg_morning"]) if row["avg_morning"] else None
            summary.avg_evening_bb = int(row["avg_evening"]) if row["avg_evening"] else None

        return summary

    def get_top_activities(
        self,
        start_date: date,
        end_date: date,
        limit: int = 5,
    ) -> list[dict]:
        """Get top activities by training load or distance."""
        cursor = self.db.connection.cursor()
        cursor.execute(
            """
            SELECT
                activity_id,
                activity_name,
                activity_type,
                start_time,
                duration_seconds,
                distance_meters,
                average_hr,
                calories,
                training_load
            FROM activities
            WHERE date(start_time) >= ? AND date(start_time) <= ?
            ORDER BY COALESCE(training_load, 0) DESC, distance_meters DESC
            LIMIT ?
            """,
            (start_date.isoformat(), end_date.isoformat(), limit)
        )

        return [dict(row) for row in cursor.fetchall()]

    def get_weekly_comparison(self, end_date: date) -> PeriodComparison:
        """Get comparison between this week and last week."""
        # This week
        week_start = end_date - timedelta(days=6)
        current_activities = self.get_activity_summary(week_start, end_date)
        current_health = self.get_health_summary(week_start, end_date)

        # Last week
        prev_end = week_start - timedelta(days=1)
        prev_start = prev_end - timedelta(days=6)
        prev_activities = self.get_activity_summary(prev_start, prev_end)
        prev_health = self.get_health_summary(prev_start, prev_end)

        comparison = PeriodComparison(
            current={
                "activities": current_activities.total_count,
                "duration_hours": current_activities.total_duration_hours,
                "distance_km": current_activities.total_distance_km,
                "calories": current_activities.total_calories,
                "avg_steps": current_health.avg_steps,
                "avg_sleep_hours": current_health.avg_sleep_hours,
                "avg_resting_hr": current_health.avg_resting_hr,
            },
            previous={
                "activities": prev_activities.total_count,
                "duration_hours": prev_activities.total_duration_hours,
                "distance_km": prev_activities.total_distance_km,
                "calories": prev_activities.total_calories,
                "avg_steps": prev_health.avg_steps,
                "avg_sleep_hours": prev_health.avg_sleep_hours,
                "avg_resting_hr": prev_health.avg_resting_hr,
            },
        )
        comparison.calculate_changes()

        return comparison

    def get_hrv_context(self, end_date: date) -> dict:
        """Calculate HRV baseline and context for trend analysis.

        Args:
            end_date: End date for analysis

        Returns:
            Dict with HRV context metrics:
            - baseline_7d: 7-day rolling average
            - baseline_28d: 28-day rolling average
            - last_night: Most recent HRV value
            - delta_from_baseline: Percentage difference from 7-day baseline
            - days_below_baseline: Consecutive days below 7-day baseline
            - status: Most recent HRV status from Garmin
        """
        cursor = self.db.connection.cursor()
        result = {
            "baseline_7d": None,
            "baseline_28d": None,
            "last_night": None,
            "delta_from_baseline": None,
            "days_below_baseline": 0,
            "status": None,
            "daily_values": [],
        }

        # Get 28 days of HRV data
        start_28d = end_date - timedelta(days=27)
        cursor.execute(
            """
            SELECT date, hrv_value, weekly_avg, last_night_avg, hrv_status
            FROM hrv_daily
            WHERE date >= ? AND date <= ? AND hrv_value IS NOT NULL
            ORDER BY date DESC
            """,
            (start_28d.isoformat(), end_date.isoformat())
        )
        rows = cursor.fetchall()

        if not rows:
            return result

        # Calculate baselines
        values_28d = [row["hrv_value"] for row in rows if row["hrv_value"]]
        values_7d = [row["hrv_value"] for row in rows[:7] if row["hrv_value"]]

        if values_28d:
            result["baseline_28d"] = round(sum(values_28d) / len(values_28d), 1)
        if values_7d:
            result["baseline_7d"] = round(sum(values_7d) / len(values_7d), 1)

        # Most recent values
        most_recent = rows[0]
        result["last_night"] = most_recent["last_night_avg"] or most_recent["hrv_value"]
        result["status"] = most_recent["hrv_status"]

        # Calculate delta from baseline
        if result["baseline_7d"] and result["last_night"]:
            delta = ((result["last_night"] - result["baseline_7d"]) / result["baseline_7d"]) * 100
            result["delta_from_baseline"] = round(delta, 1)

        # Count consecutive days below baseline
        if result["baseline_7d"]:
            days_below = 0
            for row in rows:
                if row["hrv_value"] and row["hrv_value"] < result["baseline_7d"]:
                    days_below += 1
                else:
                    break
            result["days_below_baseline"] = days_below

        # Daily values for report (most recent 7 days)
        for row in rows[:7]:
            delta_pct = None
            if result["baseline_7d"] and row["hrv_value"]:
                delta_pct = round(((row["hrv_value"] - result["baseline_7d"]) / result["baseline_7d"]) * 100, 1)
            result["daily_values"].append({
                "date": row["date"],
                "hrv": row["hrv_value"],
                "delta_pct": delta_pct,
            })

        return result

    def get_sleep_consistency(self, start_date: date, end_date: date) -> dict:
        """Calculate sleep timing consistency metrics.

        Args:
            start_date: Start date
            end_date: End date

        Returns:
            Dict with sleep consistency metrics:
            - sleep_time_variance_mins: Standard deviation of bedtime in minutes
            - wake_time_variance_mins: Standard deviation of wake time in minutes
            - avg_awake_mins: Average time awake during sleep
            - avg_rem_pct: Average REM sleep percentage
            - avg_deep_pct: Average deep sleep percentage
        """
        cursor = self.db.connection.cursor()
        result = {
            "sleep_time_variance_mins": None,
            "wake_time_variance_mins": None,
            "avg_awake_mins": None,
            "avg_rem_pct": None,
            "avg_deep_pct": None,
            "daily_values": [],
        }

        cursor.execute(
            """
            SELECT
                date,
                sleep_start,
                sleep_end,
                total_sleep_seconds,
                deep_sleep_seconds,
                rem_sleep_seconds,
                awake_seconds,
                sleep_score
            FROM sleep_daily
            WHERE date >= ? AND date <= ?
            ORDER BY date DESC
            """,
            (start_date.isoformat(), end_date.isoformat())
        )
        rows = cursor.fetchall()

        if not rows:
            return result

        # Calculate averages
        awake_values = [r["awake_seconds"] for r in rows if r["awake_seconds"]]
        if awake_values:
            result["avg_awake_mins"] = round(sum(awake_values) / len(awake_values) / 60, 1)

        # Calculate sleep stage percentages
        rem_pcts = []
        deep_pcts = []
        for row in rows:
            total = row["total_sleep_seconds"]
            if total and total > 0:
                if row["rem_sleep_seconds"]:
                    rem_pcts.append((row["rem_sleep_seconds"] / total) * 100)
                if row["deep_sleep_seconds"]:
                    deep_pcts.append((row["deep_sleep_seconds"] / total) * 100)

        if rem_pcts:
            result["avg_rem_pct"] = round(sum(rem_pcts) / len(rem_pcts), 1)
        if deep_pcts:
            result["avg_deep_pct"] = round(sum(deep_pcts) / len(deep_pcts), 1)

        # Calculate bedtime/waketime variance using timestamps
        # Note: This requires parsing the timestamp strings
        sleep_times = []
        wake_times = []
        for row in rows:
            if row["sleep_start"]:
                try:
                    # Parse timestamp and extract time as minutes from midnight
                    from datetime import datetime
                    dt = datetime.fromisoformat(row["sleep_start"].replace("Z", "+00:00"))
                    # Convert to minutes, handling times after midnight
                    mins = dt.hour * 60 + dt.minute
                    if mins < 720:  # Before noon = after midnight
                        mins += 1440  # Add 24 hours
                    sleep_times.append(mins)
                except (ValueError, AttributeError):
                    pass
            if row["sleep_end"]:
                try:
                    dt = datetime.fromisoformat(row["sleep_end"].replace("Z", "+00:00"))
                    wake_times.append(dt.hour * 60 + dt.minute)
                except (ValueError, AttributeError):
                    pass

        # Calculate standard deviation of times
        if len(sleep_times) >= 2:
            import statistics
            result["sleep_time_variance_mins"] = round(statistics.stdev(sleep_times), 1)
        if len(wake_times) >= 2:
            import statistics
            result["wake_time_variance_mins"] = round(statistics.stdev(wake_times), 1)

        # Daily values for report
        for row in rows:
            total = row["total_sleep_seconds"] or 0
            result["daily_values"].append({
                "date": row["date"],
                "sleep_hours": round(total / 3600, 1) if total else None,
                "sleep_score": row["sleep_score"],
                "deep_pct": round((row["deep_sleep_seconds"] / total) * 100, 1) if total and row["deep_sleep_seconds"] else None,
                "rem_pct": round((row["rem_sleep_seconds"] / total) * 100, 1) if total and row["rem_sleep_seconds"] else None,
                "awake_mins": round(row["awake_seconds"] / 60, 1) if row["awake_seconds"] else None,
            })

        return result

    def get_sleep_score_history(
        self, end_date: date, days: int = 14
    ) -> dict:
        """Return per-night sleep scores with personal mean and stddev.

        Used by anomaly detection to check for consecutive low-score nights.

        Args:
            end_date: End date (inclusive)
            days: Number of days to look back

        Returns:
            Dict with scores list, mean, and std.
        """
        import statistics

        cursor = self.db.connection.cursor()
        start = (end_date - timedelta(days=days - 1)).isoformat()
        ed = end_date.isoformat()

        cursor.execute(
            """
            SELECT date, sleep_score
            FROM sleep_daily
            WHERE date BETWEEN ? AND ?
                AND sleep_score IS NOT NULL
            ORDER BY date ASC
            """,
            (start, ed),
        )
        rows = cursor.fetchall()
        scores = [{"date": r["date"], "score": r["sleep_score"]} for r in rows]
        values = [r["sleep_score"] for r in rows]

        if len(values) >= 2:
            mean = statistics.mean(values)
            std = statistics.stdev(values)
        elif len(values) == 1:
            mean = values[0]
            std = 0.0
        else:
            mean = 0.0
            std = 0.0

        return {"scores": scores, "mean": round(mean, 1), "std": round(std, 1)}

    def get_training_load_trend(self, end_date: date) -> dict:
        """Calculate training load trends and acute:chronic ratio.

        Args:
            end_date: End date for analysis

        Returns:
            Dict with training load metrics:
            - acute_load_7d: Total training load for last 7 days
            - chronic_load_28d: Average weekly training load over 28 days
            - acute_chronic_ratio: A:C ratio (7-day / chronic weekly avg)
            - week_change_pct: Week-over-week load change
            - by_type: Training load breakdown by activity type
        """
        cursor = self.db.connection.cursor()
        result = {
            "acute_load_7d": None,
            "chronic_load_28d": None,
            "chronic_baseline_load": None,
            "chronic_baseline_weekly": None,
            "acute_chronic_ratio": None,
            "cardio_load_7d": None,
            "strength_load_7d": None,
            "strength_pct_of_total": None,
            "this_week_load": None,
            "prev_week_load": None,
            "week_change_pct": None,
            "by_type": {},
            "daily_loads": [],
            "avg_training_effect_aerobic": None,
            "avg_training_effect_anaerobic": None,
            "training_effect_balance": None,
        }

        # Get 28 days of training load data — UNION cardio + strength
        start_28d = end_date - timedelta(days=27)
        sd = start_28d.isoformat()
        ed = end_date.isoformat()

        # Check if hevy_workouts table exists (HEVY may not be configured)
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='hevy_workouts'"
        )
        has_hevy = cursor.fetchone() is not None

        if has_hevy:
            cursor.execute(
                """
                SELECT activity_date, source, activity_type, training_load,
                       training_effect_aerobic, training_effect_anaerobic,
                       activity_name
                FROM (
                    SELECT date(start_time) as activity_date,
                           'garmin' as source,
                           activity_type,
                           training_load,
                           training_effect_aerobic,
                           training_effect_anaerobic,
                           activity_name
                    FROM activities
                    WHERE date(start_time) >= ? AND date(start_time) <= ?
                        AND training_load IS NOT NULL

                    UNION ALL

                    SELECT date(start_time) as activity_date,
                           'hevy' as source,
                           'strength_training' as activity_type,
                           training_load,
                           NULL as training_effect_aerobic,
                           NULL as training_effect_anaerobic,
                           title as activity_name
                    FROM hevy_workouts
                    WHERE date(start_time) >= ? AND date(start_time) <= ?
                        AND training_load IS NOT NULL
                )
                ORDER BY activity_date DESC
                """,
                (sd, ed, sd, ed),
            )
        else:
            cursor.execute(
                """
                SELECT date(start_time) as activity_date,
                       'garmin' as source,
                       activity_type,
                       training_load,
                       training_effect_aerobic,
                       training_effect_anaerobic,
                       activity_name
                FROM activities
                WHERE date(start_time) >= ? AND date(start_time) <= ?
                    AND training_load IS NOT NULL
                ORDER BY start_time DESC
                """,
                (sd, ed),
            )
        # Convert to dicts so downstream code can use .get() safely
        rows = [dict(r) for r in cursor.fetchall()]

        if not rows:
            return result

        # Calculate acute (7-day) load with cardio/strength breakdown
        start_7d = end_date - timedelta(days=6)
        acute_loads = [r["training_load"] for r in rows
                       if r["activity_date"] >= start_7d.isoformat() and r["training_load"]]
        if acute_loads:
            result["acute_load_7d"] = round(sum(acute_loads), 1)

        # Breakdown by source (cardio vs strength)
        cardio_7d = sum(
            r["training_load"] for r in rows
            if r["activity_date"] >= start_7d.isoformat()
            and r["training_load"]
            and r.get("source") != "hevy"
        )
        strength_7d = sum(
            r["training_load"] for r in rows
            if r["activity_date"] >= start_7d.isoformat()
            and r["training_load"]
            and r.get("source") == "hevy"
        )
        if cardio_7d or strength_7d:
            result["cardio_load_7d"] = round(cardio_7d, 1)
            result["strength_load_7d"] = round(strength_7d, 1)
            total = cardio_7d + strength_7d
            result["strength_pct_of_total"] = (
                round((strength_7d / total) * 100, 1) if total > 0 else 0
            )

        # Calculate chronic (28-day) weekly average
        all_loads = [r["training_load"] for r in rows if r["training_load"]]
        if all_loads:
            total_28d = sum(all_loads)
            # Calculate as weekly average (total / 4 weeks)
            result["chronic_load_28d"] = round(total_28d / 4, 1)

        # Chronic baseline = load accrued BEFORE the acute 7d window (days 8-28
        # = the prior 3 weeks).  This is the UNCOUPLED chronic denominator: the
        # acute window is deliberately excluded so the A:C ratio is not
        # mathematically coupled (the classic ACWR flaw — the acute load sitting
        # inside the chronic denominator produces a spurious correlation; Lolli
        # et al. 2019, PMID 29101104).  When it's zero, all training sits in the
        # last week (no established baseline) and the ratio is left undefined.
        baseline_loads = [r["training_load"] for r in rows
                          if r["activity_date"] < start_7d.isoformat() and r["training_load"]]
        chronic_baseline = round(sum(baseline_loads), 1) if baseline_loads else 0
        result["chronic_baseline_load"] = chronic_baseline
        # Weekly average over the prior 3 weeks (uncoupled chronic).
        result["chronic_baseline_weekly"] = round(chronic_baseline / 3, 1) if chronic_baseline else 0

        # A:C ratio = acute (7d) vs the uncoupled prior-3-week weekly average.
        # NOTE: this is a DESCRIPTIVE load-ramp indicator, not a validated injury
        # predictor — the ACWR's injury-risk "sweet spot" is not supported by
        # evidence (Impellizzeri et al. 2020, PMID 32502973).
        if result["acute_load_7d"] and result["chronic_baseline_weekly"]:
            result["acute_chronic_ratio"] = round(
                result["acute_load_7d"] / result["chronic_baseline_weekly"], 2
            )

        # Week-over-week comparison
        start_this_week = end_date - timedelta(days=6)
        start_prev_week = start_this_week - timedelta(days=7)
        end_prev_week = start_this_week - timedelta(days=1)

        this_week_loads = [r["training_load"] for r in rows
                          if r["activity_date"] >= start_this_week.isoformat() and r["training_load"]]
        prev_week_loads = [r["training_load"] for r in rows
                          if start_prev_week.isoformat() <= r["activity_date"] <= end_prev_week.isoformat()
                          and r["training_load"]]

        if this_week_loads:
            result["this_week_load"] = round(sum(this_week_loads), 1)
        if prev_week_loads:
            result["prev_week_load"] = round(sum(prev_week_loads), 1)

        if result["this_week_load"] and result["prev_week_load"] and result["prev_week_load"] > 0:
            change = ((result["this_week_load"] - result["prev_week_load"]) / result["prev_week_load"]) * 100
            result["week_change_pct"] = round(change, 1)

        # Breakdown by activity type (last 7 days)
        for row in rows:
            if row["activity_date"] >= start_7d.isoformat():
                activity_type = row["activity_type"] or "unknown"
                if activity_type not in result["by_type"]:
                    result["by_type"][activity_type] = {
                        "load": 0,
                        "count": 0,
                        "aerobic_effect": [],
                        "anaerobic_effect": [],
                    }
                result["by_type"][activity_type]["load"] += row["training_load"] or 0
                result["by_type"][activity_type]["count"] += 1
                if row["training_effect_aerobic"]:
                    result["by_type"][activity_type]["aerobic_effect"].append(row["training_effect_aerobic"])
                if row["training_effect_anaerobic"]:
                    result["by_type"][activity_type]["anaerobic_effect"].append(row["training_effect_anaerobic"])

        # Calculate percentages and averages for by_type
        total_load = result["acute_load_7d"] or 0
        for activity_type, data in result["by_type"].items():
            data["load"] = round(data["load"], 1)
            data["pct_of_total"] = round((data["load"] / total_load) * 100, 1) if total_load > 0 else 0
            data["avg_aerobic"] = round(sum(data["aerobic_effect"]) / len(data["aerobic_effect"]), 1) if data["aerobic_effect"] else None
            data["avg_anaerobic"] = round(sum(data["anaerobic_effect"]) / len(data["anaerobic_effect"]), 1) if data["anaerobic_effect"] else None
            del data["aerobic_effect"]
            del data["anaerobic_effect"]

        # Overall training effect averages (7-day window)
        all_aerobic = [
            r["training_effect_aerobic"]
            for r in rows
            if r["activity_date"] >= start_7d.isoformat()
            and r["training_effect_aerobic"]
        ]
        all_anaerobic = [
            r["training_effect_anaerobic"]
            for r in rows
            if r["activity_date"] >= start_7d.isoformat()
            and r["training_effect_anaerobic"]
        ]
        if all_aerobic:
            result["avg_training_effect_aerobic"] = round(
                sum(all_aerobic) / len(all_aerobic), 1
            )
        if all_anaerobic:
            result["avg_training_effect_anaerobic"] = round(
                sum(all_anaerobic) / len(all_anaerobic), 1
            )
        if result["avg_training_effect_aerobic"] and result["avg_training_effect_anaerobic"]:
            diff = result["avg_training_effect_aerobic"] - result["avg_training_effect_anaerobic"]
            if diff > 0.5:
                result["training_effect_balance"] = "aerobic_dominant"
            elif diff < -0.5:
                result["training_effect_balance"] = "anaerobic_dominant"
            else:
                result["training_effect_balance"] = "balanced"

        # Daily loads for detailed report (last 7 days, grouped by date)
        from collections import defaultdict
        daily = defaultdict(lambda: {"load": 0, "activities": []})
        for row in rows:
            if row["activity_date"] >= start_7d.isoformat():
                d = row["activity_date"]
                daily[d]["load"] += row["training_load"] or 0
                daily[d]["activities"].append(row["activity_name"] or row["activity_type"])

        for d in sorted(daily.keys(), reverse=True):
            result["daily_loads"].append({
                "date": d,
                "load": round(daily[d]["load"], 1),
                "activities": daily[d]["activities"],
            })

        return result

    def get_weekly_load_history(
        self, end_date: date, weeks: int = 6
    ) -> dict:
        """Return per-week training load totals for phase detection.

        Args:
            end_date: End date (inclusive)
            weeks: Number of weeks to look back

        Returns:
            Dict with a ``weeks`` list (oldest first) containing
            week_start, total_load, count, and avg_hr per ISO week.
        """
        cursor = self.db.connection.cursor()
        start = end_date - timedelta(weeks=weeks)
        sd = start.isoformat()
        ed = end_date.isoformat()

        # Check if hevy_workouts table exists
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='hevy_workouts'"
        )
        has_hevy = cursor.fetchone() is not None

        if has_hevy:
            cursor.execute(
                """
                SELECT yw, MIN(week_start) AS week_start,
                       SUM(training_load) AS total_load,
                       SUM(CASE WHEN source = 'garmin' THEN training_load ELSE 0 END) AS cardio_load,
                       SUM(CASE WHEN source = 'hevy' THEN training_load ELSE 0 END) AS strength_load,
                       COUNT(*) AS count,
                       AVG(avg_hr) AS avg_hr
                FROM (
                    SELECT strftime('%Y-%W', start_time_local) AS yw,
                           date(start_time_local) AS week_start,
                           'garmin' AS source,
                           COALESCE(training_load, 0) AS training_load,
                           average_hr AS avg_hr
                    FROM activities
                    WHERE date(start_time_local) BETWEEN ? AND ?

                    UNION ALL

                    -- HEVY stores start_time in UTC; activities bucket by
                    -- local wall-clock (start_time_local).  Convert HEVY to
                    -- local time so a late-evening lift lands in the same ISO
                    -- week as a same-evening cardio session.
                    SELECT strftime('%Y-%W', datetime(start_time, 'localtime')) AS yw,
                           date(datetime(start_time, 'localtime')) AS week_start,
                           'hevy' AS source,
                           COALESCE(training_load, 0) AS training_load,
                           NULL AS avg_hr
                    FROM hevy_workouts
                    WHERE date(datetime(start_time, 'localtime')) BETWEEN ? AND ?
                        AND training_load IS NOT NULL
                )
                GROUP BY yw
                ORDER BY yw ASC
                """,
                (sd, ed, sd, ed),
            )
        else:
            cursor.execute(
                """
                SELECT strftime('%Y-%W', start_time_local) AS yw,
                       MIN(date(start_time_local)) AS week_start,
                       SUM(COALESCE(training_load, 0)) AS total_load,
                       0 AS cardio_load,
                       0 AS strength_load,
                       COUNT(*) AS count,
                       AVG(average_hr) AS avg_hr
                FROM activities
                WHERE date(start_time_local) BETWEEN ? AND ?
                GROUP BY yw
                ORDER BY yw ASC
                """,
                (sd, ed),
            )
        rows = cursor.fetchall()

        week_list = [
            {
                "week_start": r["week_start"],
                "total_load": round(r["total_load"], 1),
                "cardio_load": round(r["cardio_load"], 1) if r["cardio_load"] else 0,
                "strength_load": round(r["strength_load"], 1) if r["strength_load"] else 0,
                "count": r["count"],
                "avg_hr": round(r["avg_hr"], 1) if r["avg_hr"] else None,
            }
            for r in rows
        ]

        return {"weeks": week_list}

    def get_resting_hr_trend(self, end_date: date) -> dict:
        """Calculate resting heart rate trends.

        Args:
            end_date: End date for analysis

        Returns:
            Dict with RHR trend metrics:
            - baseline_28d: 28-day average RHR
            - current: Most recent RHR
            - delta: Difference from baseline
            - trend: "rising", "stable", or "falling"
            - daily_values: Last 7 days of RHR data
        """
        cursor = self.db.connection.cursor()
        result = {
            "baseline_28d": None,
            "current": None,
            "delta": None,
            "trend": None,
            "daily_values": [],
        }

        start_28d = end_date - timedelta(days=27)
        cursor.execute(
            """
            SELECT date, resting_hr
            FROM heart_rate_daily
            WHERE date >= ? AND date <= ? AND resting_hr IS NOT NULL
            ORDER BY date DESC
            """,
            (start_28d.isoformat(), end_date.isoformat())
        )
        rows = cursor.fetchall()

        if not rows:
            return result

        # Calculate 28-day baseline
        all_hr = [r["resting_hr"] for r in rows if r["resting_hr"]]
        if all_hr:
            result["baseline_28d"] = round(sum(all_hr) / len(all_hr))

        # Current (most recent)
        result["current"] = rows[0]["resting_hr"]

        # Delta from baseline
        if result["baseline_28d"] and result["current"]:
            result["delta"] = result["current"] - result["baseline_28d"]

        # Determine trend based on 7-day data
        recent_hr = [r["resting_hr"] for r in rows[:7] if r["resting_hr"]]
        if len(recent_hr) >= 3:
            # Simple trend: compare first half average to second half average
            first_half_avg = sum(recent_hr[:len(recent_hr)//2]) / (len(recent_hr)//2)
            second_half_avg = sum(recent_hr[len(recent_hr)//2:]) / (len(recent_hr) - len(recent_hr)//2)
            diff = first_half_avg - second_half_avg  # Note: reversed for "most recent first"
            if diff > 2:
                result["trend"] = "rising"
            elif diff < -2:
                result["trend"] = "falling"
            else:
                result["trend"] = "stable"

        # Daily values for report
        for row in rows[:7]:
            delta = None
            if result["baseline_28d"] and row["resting_hr"]:
                delta = row["resting_hr"] - result["baseline_28d"]
            result["daily_values"].append({
                "date": row["date"],
                "rhr": row["resting_hr"],
                "delta": delta,
            })

        return result

    def get_training_readiness_latest(self, end_date: date) -> dict:
        """Get most recent training readiness data.

        Args:
            end_date: Date to check for training readiness

        Returns:
            Dict with training readiness metrics
        """
        cursor = self.db.connection.cursor()
        result = {
            "score": None,
            "level": None,
            "feedback": None,
            "sleep_score": None,
            "recovery_score": None,
            "hrv_score": None,
            "stress_history_score": None,
            "training_load_balance_score": None,
        }

        cursor.execute(
            """
            SELECT *
            FROM training_readiness
            WHERE date <= ?
            ORDER BY date DESC
            LIMIT 1
            """,
            (end_date.isoformat(),)
        )
        row = cursor.fetchone()

        if row:
            result["score"] = row["score"]
            result["level"] = row["level"]
            result["feedback"] = row["feedback_phrase"]
            result["sleep_score"] = row["sleep_score"]
            result["recovery_score"] = row["recovery_score"]
            result["hrv_score"] = row["hrv_score"]
            result["stress_history_score"] = row["stress_history_score"]
            result["training_load_balance_score"] = row["training_load_balance_score"]

        return result

    def get_body_battery_recovery(self, start_date: date, end_date: date) -> dict:
        """Calculate body battery recovery metrics.

        Args:
            start_date: Start date
            end_date: End date

        Returns:
            Dict with body battery recovery metrics
        """
        cursor = self.db.connection.cursor()
        result: dict = {
            "avg_overnight_recovery": None,
            "avg_morning_high": None,
            "avg_evening_low": None,
            "avg_start_level": None,
            "avg_end_level": None,
            "avg_charged": None,
            "avg_drained": None,
            "weekday_avg_recovery": None,
            "weekend_avg_recovery": None,
            "daily_values": [],
        }

        cursor.execute(
            """
            SELECT date, max_level, min_level, start_level, end_level,
                   charged, drained
            FROM body_battery_daily
            WHERE date >= ? AND date <= ?
            ORDER BY date DESC
            """,
            (start_date.isoformat(), end_date.isoformat())
        )
        rows = cursor.fetchall()

        if not rows:
            return result

        # Calculate averages
        morning_highs = [r["max_level"] for r in rows if r["max_level"]]
        evening_lows = [r["min_level"] for r in rows if r["min_level"]]
        start_levels = [r["start_level"] for r in rows if r["start_level"] is not None]
        end_levels = [r["end_level"] for r in rows if r["end_level"] is not None]
        charged_vals = [r["charged"] for r in rows if r["charged"] is not None]
        drained_vals = [r["drained"] for r in rows if r["drained"] is not None]

        if morning_highs:
            result["avg_morning_high"] = round(sum(morning_highs) / len(morning_highs))
        if evening_lows:
            result["avg_evening_low"] = round(sum(evening_lows) / len(evening_lows))
        if start_levels:
            result["avg_start_level"] = round(sum(start_levels) / len(start_levels))
        if end_levels:
            result["avg_end_level"] = round(sum(end_levels) / len(end_levels))
        if charged_vals:
            result["avg_charged"] = round(sum(charged_vals) / len(charged_vals))
        if drained_vals:
            result["avg_drained"] = round(sum(drained_vals) / len(drained_vals))

        # Overnight recovery = morning high - previous evening low (approximated as max - start)
        recoveries = []
        weekday_recoveries = []
        weekend_recoveries = []
        for row in rows:
            if row["max_level"] and row["start_level"]:
                recovery = row["max_level"] - row["start_level"]
                recoveries.append(recovery)
                # Weekday vs weekend split
                try:
                    d = datetime.fromisoformat(row["date"])
                    if d.weekday() < 5:  # Mon-Fri
                        weekday_recoveries.append(recovery)
                    else:
                        weekend_recoveries.append(recovery)
                except (ValueError, TypeError):
                    pass

        if recoveries:
            result["avg_overnight_recovery"] = round(sum(recoveries) / len(recoveries))
        if weekday_recoveries:
            result["weekday_avg_recovery"] = round(
                sum(weekday_recoveries) / len(weekday_recoveries)
            )
        if weekend_recoveries:
            result["weekend_avg_recovery"] = round(
                sum(weekend_recoveries) / len(weekend_recoveries)
            )

        # Daily values
        for row in rows:
            recovery = None
            if row["max_level"] and row["start_level"]:
                recovery = row["max_level"] - row["start_level"]
            result["daily_values"].append({
                "date": row["date"],
                "morning_high": row["max_level"],
                "evening_low": row["min_level"],
                "overnight_recovery": recovery,
            })

        return result

    def get_strength_volume_summary(self, days: int = 7) -> dict:
        """Get strength training volume summary from HEVY data.

        Args:
            days: Number of days to aggregate

        Returns:
            Dict with strength training metrics:
            - total_sessions: Number of workouts
            - total_volume_kg: Total weight × reps
            - total_sets: Total working sets
            - total_reps: Total reps
            - by_muscle_group: Breakdown by muscle group
            - recent_workouts: List with exercise details
        """
        cursor = self.db.connection.cursor()
        start_date = (date.today() - timedelta(days=days)).isoformat()

        result = {
            "total_sessions": 0,
            "total_volume_kg": 0,
            "total_sets": 0,
            "total_reps": 0,
            "by_muscle_group": {},
            "recent_workouts": [],
        }

        # Check if HEVY tables exist
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='hevy_workouts'"
        )
        if not cursor.fetchone():
            return result

        # Get workout count
        cursor.execute(
            "SELECT COUNT(*) FROM hevy_workouts WHERE start_time >= ?",
            (start_date,)
        )
        result["total_sessions"] = cursor.fetchone()[0]

        if result["total_sessions"] == 0:
            return result

        # Get totals
        cursor.execute(
            """
            SELECT
                COALESCE(SUM(volume_kg), 0) as total_volume,
                COALESCE(SUM(set_count), 0) as total_sets,
                COALESCE(SUM(rep_count), 0) as total_reps
            FROM hevy_workouts
            WHERE start_time >= ?
            """,
            (start_date,)
        )
        row = cursor.fetchone()
        result["total_volume_kg"] = row["total_volume"] or 0
        result["total_sets"] = row["total_sets"] or 0
        result["total_reps"] = row["total_reps"] or 0

        # Get volume by muscle group
        cursor.execute(
            """
            SELECT
                e.muscle_group,
                COALESCE(SUM(s.weight_kg * s.reps), 0) as volume_kg,
                COUNT(CASE WHEN s.set_type != 'warmup' THEN 1 END) as sets
            FROM hevy_exercises e
            JOIN hevy_workouts w ON e.workout_id = w.id
            JOIN hevy_sets s ON s.exercise_id = e.id
            WHERE w.start_time >= ?
            GROUP BY e.muscle_group
            ORDER BY volume_kg DESC
            """,
            (start_date,)
        )
        for row in cursor.fetchall():
            group = row["muscle_group"] or "other"
            result["by_muscle_group"][group] = {
                "volume_kg": row["volume_kg"] or 0,
                "sets": row["sets"] or 0,
            }

        # Get recent workouts with exercise details
        kg_to_lbs = 2.20462

        def utc_to_local_date(utc_str: str) -> str | None:
            """Convert UTC timestamp to local date string."""
            from datetime import datetime as dt, timezone
            try:
                if not utc_str:
                    return None
                if '+' in utc_str or utc_str.endswith('Z'):
                    utc_str = utc_str.replace('Z', '+00:00')
                    parsed = dt.fromisoformat(utc_str)
                else:
                    parsed = dt.fromisoformat(utc_str).replace(tzinfo=timezone.utc)
                return parsed.astimezone().strftime("%Y-%m-%d")
            except (ValueError, TypeError):
                return utc_str[:10] if utc_str else None

        cursor.execute(
            """
            SELECT id, title, start_time, duration_seconds, volume_kg, set_count
            FROM hevy_workouts
            WHERE start_time >= ?
            ORDER BY start_time DESC
            LIMIT 7
            """,
            (start_date,)
        )
        workout_rows = cursor.fetchall()

        for workout_row in workout_rows:
            workout_id = workout_row["id"]
            duration_seconds = workout_row["duration_seconds"] or 0

            # Get exercises for this workout
            cursor.execute(
                """
                SELECT e.id, e.exercise_name, e.muscle_group
                FROM hevy_exercises e
                WHERE e.workout_id = ?
                ORDER BY e.exercise_order
                """,
                (workout_id,)
            )
            exercises = []

            for exercise_row in cursor.fetchall():
                exercise_id = exercise_row["id"]

                # Get sets for this exercise (non-warmup only)
                cursor.execute(
                    """
                    SELECT weight_kg, reps, set_type
                    FROM hevy_sets
                    WHERE exercise_id = ?
                    ORDER BY set_index
                    """,
                    (exercise_id,)
                )
                sets_data = cursor.fetchall()

                # Format sets compactly: "135×10, 145×8, 155×6"
                set_strings = []
                for s in sets_data:
                    if s["set_type"] == "warmup":
                        continue
                    weight_lbs = round((s["weight_kg"] or 0) * kg_to_lbs)
                    reps = s["reps"] or 0
                    if weight_lbs > 0 and reps > 0:
                        set_strings.append(f"{weight_lbs}×{reps}")
                    elif reps > 0:
                        set_strings.append(f"BW×{reps}")

                if set_strings:
                    exercises.append({
                        "name": exercise_row["exercise_name"],
                        "muscle_group": exercise_row["muscle_group"] or "other",
                        "sets": ", ".join(set_strings),
                    })

            result["recent_workouts"].append({
                "id": workout_id,
                "date": utc_to_local_date(workout_row["start_time"]),
                "title": workout_row["title"],
                "volume_kg": workout_row["volume_kg"],
                "duration_minutes": round(duration_seconds / 60) if duration_seconds else None,
                "exercises": exercises,
            })

        return result

    def get_strength_exercise_progression(
        self,
        exercise_name: str,
        days: int = 90,
    ) -> dict:
        """Track progression for a specific exercise.

        Args:
            exercise_name: Name of the exercise to track
            days: Number of days to analyze

        Returns:
            Dict with progression data
        """
        cursor = self.db.connection.cursor()
        start_date = (date.today() - timedelta(days=days)).isoformat()

        result = {
            "exercise": exercise_name,
            "sessions": [],
            "current_1rm": None,
            "progression_pct": None,
        }

        # Check if HEVY tables exist
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='hevy_exercises'"
        )
        if not cursor.fetchone():
            return result

        cursor.execute(
            """
            SELECT
                w.start_time,
                MAX(s.weight_kg) as max_weight,
                MAX(CASE WHEN s.reps BETWEEN 1 AND 10 THEN s.weight_kg * (1 + s.reps / 30.0) END) as est_1rm
            FROM hevy_exercises e
            JOIN hevy_workouts w ON e.workout_id = w.id
            JOIN hevy_sets s ON s.exercise_id = e.id
            WHERE e.exercise_name LIKE ?
                AND w.start_time >= ?
                AND s.set_type = 'normal'
                AND s.weight_kg > 0
            GROUP BY w.id
            ORDER BY w.start_time DESC
            """,
            (f"%{exercise_name}%", start_date)
        )

        sessions = []
        for row in cursor.fetchall():
            sessions.append({
                "date": row["start_time"][:10] if row["start_time"] else None,
                "max_weight": row["max_weight"],
                "est_1rm": round(row["est_1rm"], 1) if row["est_1rm"] else None,
            })

        if not sessions:
            return result

        result["sessions"] = sessions[:10]
        result["current_1rm"] = sessions[0]["est_1rm"] if sessions else None

        # Calculate progression
        if len(sessions) >= 2 and result["current_1rm"]:
            older_sessions = sessions[len(sessions)//2:]
            older_1rms = [s["est_1rm"] for s in older_sessions if s["est_1rm"]]
            if older_1rms:
                older_avg = sum(older_1rms) / len(older_1rms)
                if older_avg > 0:
                    result["progression_pct"] = round(
                        ((result["current_1rm"] - older_avg) / older_avg) * 100, 1
                    )

        return result

    # ==================== Longitudinal (multi-year) ====================

    def get_aerobic_efficiency_by_period(
        self,
        start_year: int,
        end_year: int,
        granularity: str = "year",
    ) -> dict:
        """Pace, HR, and meters-per-heartbeat for runs, bucketed by year or quarter.

        meters_per_beat = total_meters / sum(avg_hr * duration_minutes); higher means
        more aerobic fitness at a given HR.
        """
        cursor = self.db.connection.cursor()

        if granularity == "quarter":
            bucket = (
                "strftime('%Y', start_time) || '-Q' || "
                "((CAST(strftime('%m', start_time) AS INTEGER) - 1)/3 + 1)"
            )
        else:
            bucket = "strftime('%Y', start_time)"

        cursor.execute(
            f"""
            SELECT
                {bucket} AS label,
                COUNT(*) AS run_count,
                SUM(distance_meters) AS total_meters,
                SUM(duration_seconds) AS total_seconds,
                AVG(average_hr) AS avg_hr,
                SUM(average_hr * duration_seconds / 60.0) AS hr_minutes
            FROM activities
            WHERE activity_type IN ('running', 'treadmill_running')
                AND average_hr IS NOT NULL AND average_hr > 0
                AND distance_meters > 0
                AND duration_seconds > 0
                AND CAST(strftime('%Y', start_time) AS INTEGER) BETWEEN ? AND ?
            GROUP BY label
            ORDER BY label
            """,
            (start_year, end_year),
        )

        periods = []
        for row in cursor.fetchall():
            total_m = row["total_meters"] or 0
            total_s = row["total_seconds"] or 0
            hr_minutes = row["hr_minutes"] or 0
            pace = (total_s / total_m * 1000 / 60) if total_m > 0 else None
            mpb = (total_m / hr_minutes) if hr_minutes > 0 else None
            periods.append({
                "label": row["label"],
                "run_count": row["run_count"],
                "total_km": round(total_m / 1000, 1) if total_m else 0.0,
                "avg_pace_min_per_km": round(pace, 2) if pace else None,
                "avg_hr": round(row["avg_hr"], 1) if row["avg_hr"] else None,
                "meters_per_beat": round(mpb, 2) if mpb else None,
            })

        return {"granularity": granularity, "periods": periods}

    def get_yearly_health_baselines(
        self,
        start_year: int,
        end_year: int,
    ) -> dict:
        """Per-year RHR / HRV / sleep / stress baselines, plus sleep-duration CoV."""
        cursor = self.db.connection.cursor()
        years = []

        for year in range(start_year, end_year + 1):
            year_start = f"{year}-01-01"
            year_end = f"{year}-12-31"
            entry: dict = {"year": year}

            cursor.execute(
                "SELECT AVG(resting_hr) AS avg_rhr, COUNT(*) AS n FROM heart_rate_daily "
                "WHERE resting_hr IS NOT NULL AND date BETWEEN ? AND ?",
                (year_start, year_end),
            )
            row = cursor.fetchone()
            entry["avg_resting_hr"] = round(row["avg_rhr"], 1) if row["avg_rhr"] else None
            entry["rhr_n_days"] = row["n"] or 0

            cursor.execute(
                "SELECT AVG(hrv_value) AS avg_hrv, COUNT(*) AS n FROM hrv_daily "
                "WHERE hrv_value IS NOT NULL AND date BETWEEN ? AND ?",
                (year_start, year_end),
            )
            row = cursor.fetchone()
            entry["avg_hrv"] = round(row["avg_hrv"], 1) if row["avg_hrv"] else None
            entry["hrv_n_days"] = row["n"] or 0

            cursor.execute(
                "SELECT total_sleep_seconds FROM sleep_daily "
                "WHERE total_sleep_seconds IS NOT NULL AND total_sleep_seconds > 0 "
                "AND date BETWEEN ? AND ?",
                (year_start, year_end),
            )
            secs = [r["total_sleep_seconds"] for r in cursor.fetchall()]
            if secs:
                avg = sum(secs) / len(secs)
                variance = sum((x - avg) ** 2 for x in secs) / len(secs)
                stddev = variance ** 0.5
                entry["avg_sleep_hours"] = round(avg / 3600, 2)
                entry["sleep_cov"] = round(stddev / avg, 3) if avg > 0 else None
                entry["sleep_n_days"] = len(secs)
            else:
                entry["avg_sleep_hours"] = None
                entry["sleep_cov"] = None
                entry["sleep_n_days"] = 0

            cursor.execute(
                "SELECT AVG(avg_stress_level) AS avg_stress, COUNT(*) AS n FROM stress_daily "
                "WHERE avg_stress_level IS NOT NULL AND avg_stress_level > 0 "
                "AND date BETWEEN ? AND ?",
                (year_start, year_end),
            )
            row = cursor.fetchone()
            entry["avg_stress"] = round(row["avg_stress"], 1) if row["avg_stress"] else None
            entry["stress_n_days"] = row["n"] or 0

            years.append(entry)

        return {"years": years}

    def get_volume_by_period(
        self,
        start_year: int,
        end_year: int,
        granularity: str = "year",
    ) -> dict:
        """Training volume bucketed by year or quarter, plus weekly-volume CoV per bucket."""
        cursor = self.db.connection.cursor()

        if granularity == "quarter":
            bucket = (
                "strftime('%Y', start_time) || '-Q' || "
                "((CAST(strftime('%m', start_time) AS INTEGER) - 1)/3 + 1)"
            )
        else:
            bucket = "strftime('%Y', start_time)"

        cursor.execute(
            f"""
            SELECT
                {bucket} AS label,
                activity_type,
                SUM(duration_seconds) AS total_seconds,
                SUM(distance_meters) AS total_meters,
                COUNT(*) AS n
            FROM activities
            WHERE duration_seconds > 0
                AND CAST(strftime('%Y', start_time) AS INTEGER) BETWEEN ? AND ?
            GROUP BY label, activity_type
            ORDER BY label, activity_type
            """,
            (start_year, end_year),
        )

        by_period: dict[str, dict] = {}
        for row in cursor.fetchall():
            label = row["label"]
            entry = by_period.setdefault(label, {
                "label": label,
                "total_hours": 0.0,
                "total_km": 0.0,
                "by_type": {},
            })
            hours = (row["total_seconds"] or 0) / 3600
            km = (row["total_meters"] or 0) / 1000
            entry["total_hours"] += hours
            entry["total_km"] += km
            entry["by_type"][row["activity_type"]] = {
                "hours": round(hours, 1),
                "km": round(km, 1),
                "count": row["n"],
            }

        for label, entry in by_period.items():
            if granularity == "year":
                period_start = f"{label}-01-01"
                period_end = f"{label}-12-31 23:59:59"
            else:
                year, q = label.split("-Q")
                q_int = int(q)
                m1 = (q_int - 1) * 3 + 1
                m_end = m1 + 2
                period_start = f"{year}-{m1:02d}-01"
                # SQLite text-compares dates fine; pad day to 31 even if month is shorter.
                period_end = f"{year}-{m_end:02d}-31 23:59:59"

            cursor.execute(
                """
                SELECT strftime('%Y-%W', start_time) AS week,
                       SUM(duration_seconds) / 3600.0 AS hours
                FROM activities
                WHERE duration_seconds > 0
                    AND start_time BETWEEN ? AND ?
                GROUP BY week
                """,
                (period_start, period_end),
            )
            weekly = [r["hours"] for r in cursor.fetchall() if r["hours"]]
            if len(weekly) >= 2:
                avg_w = sum(weekly) / len(weekly)
                var_w = sum((x - avg_w) ** 2 for x in weekly) / len(weekly)
                stddev_w = var_w ** 0.5
                entry["weekly_hours_cov"] = round(stddev_w / avg_w, 3) if avg_w > 0 else None
            else:
                entry["weekly_hours_cov"] = None
            entry["weeks_with_activity"] = len(weekly)
            entry["total_hours"] = round(entry["total_hours"], 1)
            entry["total_km"] = round(entry["total_km"], 1)

        return {
            "granularity": granularity,
            "periods": [by_period[k] for k in sorted(by_period.keys())],
        }

    def get_hr_drift_by_period(
        self,
        start_year: int,
        end_year: int,
    ) -> dict:
        """Long-run HR drift bucketed by year. Uses activities.hr_drift populated by fit_parser."""
        cursor = self.db.connection.cursor()
        cursor.execute(
            """
            SELECT strftime('%Y', start_time) AS year, hr_drift
            FROM activities
            WHERE hr_drift IS NOT NULL
                AND duration_seconds >= 2700
                AND CAST(strftime('%Y', start_time) AS INTEGER) BETWEEN ? AND ?
            ORDER BY year
            """,
            (start_year, end_year),
        )

        by_year: dict[str, list[float]] = {}
        for row in cursor.fetchall():
            by_year.setdefault(row["year"], []).append(row["hr_drift"])

        import statistics
        periods = []
        for year, drifts in sorted(by_year.items()):
            median = statistics.median(drifts)
            periods.append({
                "year": year,
                "n": len(drifts),
                "avg_drift_pct": round(sum(drifts) / len(drifts), 2),
                "median_drift_pct": round(median, 2),
            })

        return {"periods": periods}

    # ------------------------------------------------------------------
    # Tier 1 analytics — cadence, VO2 max, elevation, sleep respiration
    # ------------------------------------------------------------------

    _RUNNING_TYPES = ("running", "treadmill_running", "trail_running")

    def get_cadence_analysis(self, start_date: date, end_date: date) -> dict:
        """Analyse running cadence trends over a date range.

        Args:
            start_date: Start date (inclusive)
            end_date: End date (inclusive)

        Returns:
            Dict with overall averages, weekly trend, and per-activity-type
            breakdown.  All cadence values are in steps-per-minute.
        """
        cursor = self.db.connection.cursor()
        result: dict = {
            "avg_cadence": None,
            "max_cadence": None,
            "total_activities_with_cadence": 0,
            "weekly_trend": [],
            "by_activity_type": {},
        }

        cursor.execute(
            """
            SELECT
                date(start_time) AS activity_date,
                activity_type,
                avg_cadence,
                max_cadence
            FROM activities
            WHERE date(start_time) >= ? AND date(start_time) <= ?
                AND avg_cadence IS NOT NULL
            ORDER BY start_time
            """,
            (start_date.isoformat(), end_date.isoformat()),
        )
        rows = cursor.fetchall()

        if not rows:
            return result

        all_avg = [r["avg_cadence"] for r in rows if r["avg_cadence"]]
        all_max = [r["max_cadence"] for r in rows if r["max_cadence"]]

        result["total_activities_with_cadence"] = len(all_avg)
        if all_avg:
            result["avg_cadence"] = round(sum(all_avg) / len(all_avg), 1)
        if all_max:
            result["max_cadence"] = round(max(all_max), 1)

        # Weekly trend (ISO week)
        from collections import defaultdict

        weekly: dict[str, list[float]] = defaultdict(list)
        for row in rows:
            d = date.fromisoformat(row["activity_date"])
            week_label = f"{d.isocalendar().year}-W{d.isocalendar().week:02d}"
            weekly[week_label].append(row["avg_cadence"])

        for week_label in sorted(weekly):
            vals = weekly[week_label]
            result["weekly_trend"].append({
                "week": week_label,
                "avg_cadence": round(sum(vals) / len(vals), 1),
                "count": len(vals),
            })

        # By activity type
        by_type: dict[str, dict] = defaultdict(lambda: {"avgs": [], "maxes": []})
        for row in rows:
            at = row["activity_type"] or "unknown"
            by_type[at]["avgs"].append(row["avg_cadence"])
            if row["max_cadence"]:
                by_type[at]["maxes"].append(row["max_cadence"])

        for at, data in by_type.items():
            result["by_activity_type"][at] = {
                "avg": round(sum(data["avgs"]) / len(data["avgs"]), 1),
                "max": round(max(data["maxes"]), 1) if data["maxes"] else None,
                "count": len(data["avgs"]),
            }

        return result

    def get_vo2_max_trend(self, start_date: date, end_date: date) -> dict:
        """Track VO2 max progression over a date range.

        Args:
            start_date: Start date (inclusive)
            end_date: End date (inclusive)

        Returns:
            Dict with current value, earliest in range, delta, trend
            direction, and individual data points.
        """
        cursor = self.db.connection.cursor()
        result: dict = {
            "current": None,
            "period_start": None,
            "delta": None,
            "trend": None,
            "data_points": 0,
            "values": [],
        }

        cursor.execute(
            """
            SELECT date(start_time) AS activity_date,
                   vo2_max,
                   activity_type
            FROM activities
            WHERE date(start_time) >= ? AND date(start_time) <= ?
                AND vo2_max IS NOT NULL
            ORDER BY start_time
            """,
            (start_date.isoformat(), end_date.isoformat()),
        )
        rows = cursor.fetchall()

        if not rows:
            return result

        result["data_points"] = len(rows)
        result["period_start"] = rows[0]["vo2_max"]
        result["current"] = rows[-1]["vo2_max"]
        delta = result["current"] - result["period_start"]
        result["delta"] = round(delta, 1)

        if delta > 1.0:
            result["trend"] = "improving"
        elif delta < -1.0:
            result["trend"] = "declining"
        else:
            result["trend"] = "stable"

        for row in rows:
            result["values"].append({
                "date": row["activity_date"],
                "vo2_max": row["vo2_max"],
                "activity_type": row["activity_type"],
            })

        return result

    def get_elevation_summary(self, start_date: date, end_date: date) -> dict:
        """Summarise elevation gain/loss over a date range.

        Args:
            start_date: Start date (inclusive)
            end_date: End date (inclusive)

        Returns:
            Dict with total gain/loss, average per activity,
            vertical metres per hour, and per-activity-type breakdown.
        """
        cursor = self.db.connection.cursor()
        result: dict = {
            "total_gain_meters": None,
            "total_loss_meters": None,
            "total_activities": 0,
            "avg_gain_per_activity": None,
            "vert_per_hour": None,
            "by_activity_type": {},
        }

        cursor.execute(
            """
            SELECT activity_type,
                   elevation_gain_meters,
                   elevation_loss_meters,
                   duration_seconds
            FROM activities
            WHERE date(start_time) >= ? AND date(start_time) <= ?
                AND elevation_gain_meters IS NOT NULL
            ORDER BY start_time
            """,
            (start_date.isoformat(), end_date.isoformat()),
        )
        rows = cursor.fetchall()

        if not rows:
            return result

        total_gain = sum(r["elevation_gain_meters"] for r in rows)
        total_loss = sum(r["elevation_loss_meters"] or 0 for r in rows)
        total_duration_s = sum(r["duration_seconds"] or 0 for r in rows)

        result["total_gain_meters"] = round(total_gain, 1)
        result["total_loss_meters"] = round(total_loss, 1)
        result["total_activities"] = len(rows)
        result["avg_gain_per_activity"] = round(total_gain / len(rows), 1)

        total_hours = total_duration_s / 3600
        if total_hours > 0:
            result["vert_per_hour"] = round(total_gain / total_hours, 1)

        # By activity type
        from collections import defaultdict

        by_type: dict[str, dict] = defaultdict(
            lambda: {"gain": 0.0, "loss": 0.0, "count": 0}
        )
        for row in rows:
            at = row["activity_type"] or "unknown"
            by_type[at]["gain"] += row["elevation_gain_meters"]
            by_type[at]["loss"] += row["elevation_loss_meters"] or 0
            by_type[at]["count"] += 1

        for at, data in by_type.items():
            result["by_activity_type"][at] = {
                "gain": round(data["gain"], 1),
                "loss": round(data["loss"], 1),
                "count": data["count"],
            }

        return result

    def get_sleep_respiration_trends(
        self, start_date: date, end_date: date
    ) -> dict:
        """Analyse sleep respiration rate and SpO2 trends.

        Args:
            start_date: Start date (inclusive)
            end_date: End date (inclusive)

        Returns:
            Dict with average respiration/SpO2, min SpO2, trend direction,
            and daily values.
        """
        cursor = self.db.connection.cursor()
        result: dict = {
            "avg_respiration": None,
            "avg_spo2": None,
            "min_spo2": None,
            "respiration_trend": None,
            "data_points": 0,
            "daily_values": [],
        }

        cursor.execute(
            """
            SELECT date, avg_respiration, avg_spo2
            FROM sleep_daily
            WHERE date >= ? AND date <= ?
                AND (avg_respiration IS NOT NULL OR avg_spo2 IS NOT NULL)
            ORDER BY date
            """,
            (start_date.isoformat(), end_date.isoformat()),
        )
        rows = cursor.fetchall()

        if not rows:
            return result

        result["data_points"] = len(rows)

        resp_vals = [r["avg_respiration"] for r in rows if r["avg_respiration"]]
        spo2_vals = [r["avg_spo2"] for r in rows if r["avg_spo2"]]

        if resp_vals:
            result["avg_respiration"] = round(sum(resp_vals) / len(resp_vals), 1)

            # Trend: compare first half vs second half
            mid = len(resp_vals) // 2
            if mid > 0:
                first_half = sum(resp_vals[:mid]) / mid
                second_half = sum(resp_vals[mid:]) / len(resp_vals[mid:])
                diff = second_half - first_half
                if diff > 0.5:
                    result["respiration_trend"] = "rising"
                elif diff < -0.5:
                    result["respiration_trend"] = "falling"
                else:
                    result["respiration_trend"] = "stable"

        if spo2_vals:
            result["avg_spo2"] = round(sum(spo2_vals) / len(spo2_vals), 1)
            result["min_spo2"] = round(min(spo2_vals), 1)

        for row in rows:
            result["daily_values"].append({
                "date": row["date"],
                "respiration": row["avg_respiration"],
                "spo2": row["avg_spo2"],
            })

        return result

    # ==================== Tier 2: RPE Analytics ====================

    def get_rpe_analysis(self, days: int = 7) -> dict:
        """Get RPE-weighted volume and effort trends from HEVY data.

        Args:
            days: Number of days to analyze

        Returns:
            Dict with RPE metrics:
            - sessions: Per-workout RPE and volume data
            - overall_avg_rpe: Average RPE across all sessions
            - rpe_coverage_pct: Percentage of sets that have RPE
            - overreaching_flag: True if RPE rising while volume flat/falling
        """
        cursor = self.db.connection.cursor()
        start_date = (date.today() - timedelta(days=days)).isoformat()

        result: dict = {
            "sessions": [],
            "overall_avg_rpe": None,
            "rpe_coverage_pct": 0.0,
            "overreaching_flag": False,
        }

        # Check if HEVY tables exist
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='hevy_workouts'"
        )
        if not cursor.fetchone():
            return result

        cursor.execute(
            """
            SELECT
                w.id AS workout_id,
                w.start_time,
                AVG(CASE WHEN s.rpe IS NOT NULL THEN s.rpe END) AS avg_rpe,
                COALESCE(SUM(s.weight_kg * s.reps), 0) AS raw_volume_kg,
                COALESCE(SUM(
                    CASE WHEN s.rpe IS NOT NULL
                         THEN s.weight_kg * s.reps * (s.rpe / 10.0)
                         ELSE NULL
                    END
                ), 0) AS rpe_adjusted_volume_kg,
                COUNT(CASE WHEN s.rpe IS NOT NULL THEN 1 END) AS sets_with_rpe,
                COUNT(*) AS total_sets
            FROM hevy_workouts w
            JOIN hevy_exercises e ON e.workout_id = w.id
            JOIN hevy_sets s ON s.exercise_id = e.id
            WHERE w.start_time >= ?
              AND s.set_type = 'normal'
            GROUP BY w.id
            ORDER BY w.start_time ASC
            """,
            (start_date,),
        )
        rows = cursor.fetchall()

        if not rows:
            return result

        all_rpes: list[float] = []
        total_sets_with_rpe = 0
        total_sets_all = 0

        for row in rows:
            avg_rpe = round(row["avg_rpe"], 1) if row["avg_rpe"] is not None else None
            total = row["total_sets"] or 0
            with_rpe = row["sets_with_rpe"] or 0
            coverage = round((with_rpe / total) * 100, 1) if total > 0 else 0.0

            result["sessions"].append({
                "date": row["start_time"][:10] if row["start_time"] else None,
                "avg_rpe": avg_rpe,
                "raw_volume_kg": round(row["raw_volume_kg"], 1),
                "rpe_adjusted_volume_kg": round(row["rpe_adjusted_volume_kg"], 1),
                "rpe_coverage_pct": coverage,
            })

            if avg_rpe is not None:
                all_rpes.append(avg_rpe)
            total_sets_with_rpe += with_rpe
            total_sets_all += total

        if all_rpes:
            result["overall_avg_rpe"] = round(sum(all_rpes) / len(all_rpes), 1)

        result["rpe_coverage_pct"] = (
            round((total_sets_with_rpe / total_sets_all) * 100, 1)
            if total_sets_all > 0 else 0.0
        )

        # Overreaching detection: RPE rising while volume flat/falling
        sessions = result["sessions"]
        if len(sessions) >= 4:
            mid = len(sessions) // 2
            first_half = sessions[:mid]
            second_half = sessions[mid:]

            first_rpes = [s["avg_rpe"] for s in first_half if s["avg_rpe"] is not None]
            second_rpes = [s["avg_rpe"] for s in second_half if s["avg_rpe"] is not None]
            first_vols = [s["raw_volume_kg"] for s in first_half]
            second_vols = [s["raw_volume_kg"] for s in second_half]

            if first_rpes and second_rpes and first_vols and second_vols:
                avg_rpe_first = sum(first_rpes) / len(first_rpes)
                avg_rpe_second = sum(second_rpes) / len(second_rpes)
                avg_vol_first = sum(first_vols) / len(first_vols)
                avg_vol_second = sum(second_vols) / len(second_vols)

                rpe_increasing = (avg_rpe_second - avg_rpe_first) > 0.5
                vol_flat_or_falling = avg_vol_second <= avg_vol_first
                result["overreaching_flag"] = rpe_increasing and vol_flat_or_falling

        return result

    def get_exercise_rpe_trend(self, exercise_name: str, days: int = 90) -> dict:
        """Get RPE trend for a specific exercise alongside 1RM progression.

        Args:
            exercise_name: Name of the exercise to track
            days: Number of days to analyze

        Returns:
            Dict with per-session RPE and 1RM, plus overall trend
        """
        cursor = self.db.connection.cursor()
        start_date = (date.today() - timedelta(days=days)).isoformat()

        result: dict = {
            "sessions": [],
            "rpe_trend": None,
        }

        # Check if HEVY tables exist
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='hevy_exercises'"
        )
        if not cursor.fetchone():
            return result

        cursor.execute(
            """
            SELECT
                w.start_time,
                AVG(s.rpe) AS avg_rpe,
                MAX(CASE WHEN s.reps BETWEEN 1 AND 10
                    THEN s.weight_kg * (1 + s.reps / 30.0) END) AS est_1rm
            FROM hevy_exercises e
            JOIN hevy_workouts w ON e.workout_id = w.id
            JOIN hevy_sets s ON s.exercise_id = e.id
            WHERE e.exercise_name LIKE ?
                AND w.start_time >= ?
                AND s.set_type = 'normal'
                AND s.weight_kg > 0
                AND s.rpe IS NOT NULL
            GROUP BY w.id
            ORDER BY w.start_time ASC
            """,
            (f"%{exercise_name}%", start_date),
        )
        rows = cursor.fetchall()

        if not rows:
            return result

        rpe_values: list[float] = []
        for row in rows:
            avg_rpe = round(row["avg_rpe"], 1) if row["avg_rpe"] is not None else None
            result["sessions"].append({
                "date": row["start_time"][:10] if row["start_time"] else None,
                "avg_rpe": avg_rpe,
                "est_1rm_kg": round(row["est_1rm"], 1) if row["est_1rm"] else None,
            })
            if avg_rpe is not None:
                rpe_values.append(avg_rpe)

        # Determine trend using first-half vs second-half comparison
        if len(rpe_values) >= 4:
            mid = len(rpe_values) // 2
            avg_first = sum(rpe_values[:mid]) / mid
            avg_second = sum(rpe_values[mid:]) / len(rpe_values[mid:])
            diff = avg_second - avg_first
            if diff > 0.5:
                result["rpe_trend"] = "rising"
            elif diff < -0.5:
                result["rpe_trend"] = "falling"
            else:
                result["rpe_trend"] = "stable"

        return result

    # ------------------------------------------------------------------
    # Tier 2: Stress-Recovery Correlation
    # ------------------------------------------------------------------

    def get_stress_recovery_correlation(
        self, start_date: date, end_date: date
    ) -> dict:
        """Correlate daily stress with next-day body battery recovery.

        Cross-references stress_daily, body_battery_daily, and activities
        to surface patterns like high-stress days followed by poor recovery.

        Args:
            start_date: Start of date range
            end_date: End of date range

        Returns:
            Dict with avg stress on training vs rest days,
            high-stress-poor-recovery day count, and pattern descriptions.
        """
        cursor = self.db.connection.cursor()
        sd = start_date.isoformat()
        ed = end_date.isoformat()

        # Build a day-level view joining stress, body battery (next day),
        # and whether a training session happened that day.
        cursor.execute(
            """
            SELECT
                s.date,
                s.avg_stress_level,
                s.high_stress_duration,
                bb_next.start_level AS next_day_bb_start,
                COALESCE(act.daily_load, 0) AS daily_load
            FROM stress_daily s
            LEFT JOIN body_battery_daily bb_next
                ON bb_next.date = date(s.date, '+1 day')
            LEFT JOIN (
                SELECT date(start_time_local) AS act_date,
                       SUM(training_load) AS daily_load
                FROM activities
                WHERE date(start_time_local) BETWEEN ? AND ?
                GROUP BY date(start_time_local)
            ) act ON act.act_date = s.date
            WHERE s.date BETWEEN ? AND ?
            ORDER BY s.date
            """,
            (sd, ed, sd, ed),
        )
        rows = cursor.fetchall()

        if not rows:
            return {
                "days_analyzed": 0,
                "avg_stress_training_days": None,
                "avg_stress_rest_days": None,
                "high_stress_poor_recovery_days": 0,
                "patterns": [],
            }

        stress_training: list[int] = []
        stress_rest: list[int] = []
        high_stress_poor_recovery = 0
        pattern_dates: list[dict] = []

        for row in rows:
            avg_stress = row["avg_stress_level"]
            daily_load = row["daily_load"] or 0
            next_bb = row["next_day_bb_start"]

            if avg_stress is None:
                continue

            if daily_load > 0:
                stress_training.append(avg_stress)
            else:
                stress_rest.append(avg_stress)

            # Pattern: high stress day → poor BB start next morning
            if avg_stress > 50 and next_bb is not None and next_bb < 30:
                high_stress_poor_recovery += 1
                pattern_dates.append({
                    "date": row["date"],
                    "stress": avg_stress,
                    "next_day_bb_start": next_bb,
                })

        patterns = []
        if high_stress_poor_recovery > 0:
            avg_next_bb = round(
                sum(p["next_day_bb_start"] for p in pattern_dates)
                / len(pattern_dates),
                1,
            )
            patterns.append({
                "pattern": "high_stress_poor_recovery",
                "description": (
                    f"High stress (>50) followed by poor body battery start (<30) "
                    f"on {high_stress_poor_recovery} days"
                ),
                "occurrences": high_stress_poor_recovery,
                "avg_next_day_bb_start": avg_next_bb,
            })

        return {
            "days_analyzed": len(rows),
            "avg_stress_training_days": (
                round(sum(stress_training) / len(stress_training), 1)
                if stress_training
                else None
            ),
            "avg_stress_rest_days": (
                round(sum(stress_rest) / len(stress_rest), 1)
                if stress_rest
                else None
            ),
            "high_stress_poor_recovery_days": high_stress_poor_recovery,
            "patterns": patterns,
        }

    # ------------------------------------------------------------------
    # Tier 2: Sleep-Performance Correlation
    # ------------------------------------------------------------------

    def get_sleep_performance_correlation(
        self, start_date: date, end_date: date
    ) -> dict:
        """Correlate sleep quality with next-day training performance.

        Uses personal A-F grading based on the user's own sleep score
        distribution (mean ± σ), then links each grade to the next day's
        training load, HR drift, and aerobic training effect.

        Args:
            start_date: Start of date range
            end_date: End of date range

        Returns:
            Dict with sleep score stats, performance by grade bucket,
            HRV-performance link, and optional insight string.
        """
        cursor = self.db.connection.cursor()
        sd = start_date.isoformat()
        ed = end_date.isoformat()

        # Join sleep on day D → activities on day D+1
        cursor.execute(
            """
            SELECT
                sl.date AS sleep_date,
                sl.sleep_score,
                sl.avg_hrv,
                a.training_load,
                a.hr_drift,
                a.training_effect_aerobic
            FROM sleep_daily sl
            INNER JOIN activities a
                ON date(a.start_time_local) = date(sl.date, '+1 day')
            WHERE sl.date BETWEEN ? AND ?
                AND sl.sleep_score IS NOT NULL
            ORDER BY sl.date
            """,
            (sd, ed),
        )
        rows = cursor.fetchall()

        if not rows:
            return {
                "data_points": 0,
                "sleep_score_stats": None,
                "by_sleep_grade": {},
                "hrv_performance_link": None,
                "insight": None,
            }

        # Compute personal distribution
        scores = [r["sleep_score"] for r in rows]
        n = len(scores)
        mean = sum(scores) / n
        variance = sum((s - mean) ** 2 for s in scores) / n
        std = variance ** 0.5

        # Avoid division by zero for perfectly uniform scores
        if std < 0.01:
            std = 1.0

        def _grade(score: float) -> str:
            if score >= mean + std:
                return "A"
            elif score >= mean + 0.5 * std:
                return "B"
            elif score >= mean - 0.5 * std:
                return "C"
            elif score >= mean - std:
                return "D"
            else:
                return "F"

        # Bucket by grade
        grade_data: dict[str, list[dict]] = {g: [] for g in "ABCDF"}
        hrv_values: list[tuple[float, float]] = []  # (hrv, training_load)

        for row in rows:
            g = _grade(row["sleep_score"])
            grade_data[g].append({
                "training_load": row["training_load"],
                "hr_drift": row["hr_drift"],
                "training_effect": row["training_effect_aerobic"],
            })
            if row["avg_hrv"] is not None and row["training_load"] is not None:
                hrv_values.append((row["avg_hrv"], row["training_load"]))

        # Build grade summary
        by_grade = {}
        for g in "ABCDF":
            entries = grade_data[g]
            if not entries:
                continue
            loads = [e["training_load"] for e in entries if e["training_load"] is not None]
            drifts = [e["hr_drift"] for e in entries if e["hr_drift"] is not None]
            effects = [e["training_effect"] for e in entries if e["training_effect"] is not None]
            by_grade[g] = {
                "count": len(entries),
                "avg_training_load": round(sum(loads) / len(loads), 1) if loads else None,
                "avg_hr_drift": round(sum(drifts) / len(drifts), 3) if drifts else None,
                "avg_training_effect": round(sum(effects) / len(effects), 1) if effects else None,
            }

        # HRV-performance link: above-median vs below-median HRV
        hrv_link = None
        if len(hrv_values) >= 4:
            hrv_sorted = sorted(hrv_values, key=lambda x: x[0])
            mid = len(hrv_sorted) // 2
            low_loads = [v[1] for v in hrv_sorted[:mid]]
            high_loads = [v[1] for v in hrv_sorted[mid:]]
            hrv_link = {
                "high_hrv_avg_load": (
                    round(sum(high_loads) / len(high_loads), 1) if high_loads else None
                ),
                "low_hrv_avg_load": (
                    round(sum(low_loads) / len(low_loads), 1) if low_loads else None
                ),
            }

        # Generate insight comparing A vs F grades
        insight = None
        if "A" in by_grade and "F" in by_grade:
            a_load = by_grade["A"].get("avg_training_load")
            f_load = by_grade["F"].get("avg_training_load")
            if a_load and f_load and f_load > 0:
                pct = round((a_load / f_load - 1) * 100)
                if abs(pct) >= 10:
                    direction = "higher" if pct > 0 else "lower"
                    insight = (
                        f"A-grade sleep nights predict {abs(pct)}% {direction} "
                        f"training load vs F-grade"
                    )

        return {
            "data_points": n,
            "sleep_score_stats": {
                "mean": round(mean, 1),
                "std": round(std, 1),
            },
            "by_sleep_grade": by_grade,
            "hrv_performance_link": hrv_link,
            "insight": insight,
        }

    # ------------------------------------------------------------------
    # Tier 2: Monthly/Quarterly Progress Reports
    # ------------------------------------------------------------------

    def get_monthly_comparison(self, year: int, month: int) -> PeriodComparison:
        """Compare a month against the previous month.

        Follows the same pattern as ``get_weekly_comparison`` but uses
        calendar month boundaries.

        Args:
            year: Year of the target month
            month: Month number (1-12)

        Returns:
            PeriodComparison with current vs previous month metrics.
        """
        _, days_in_month = calendar.monthrange(year, month)
        current_start = date(year, month, 1)
        current_end = date(year, month, days_in_month)

        # Previous month
        if month == 1:
            prev_year, prev_month = year - 1, 12
        else:
            prev_year, prev_month = year, month - 1
        _, prev_days = calendar.monthrange(prev_year, prev_month)
        prev_start = date(prev_year, prev_month, 1)
        prev_end = date(prev_year, prev_month, prev_days)

        current_activities = self.get_activity_summary(current_start, current_end)
        current_health = self.get_health_summary(current_start, current_end)

        prev_activities = self.get_activity_summary(prev_start, prev_end)
        prev_health = self.get_health_summary(prev_start, prev_end)

        comparison = PeriodComparison(
            current={
                "activities": current_activities.total_count,
                "duration_hours": current_activities.total_duration_hours,
                "distance_km": current_activities.total_distance_km,
                "calories": current_activities.total_calories,
                "avg_steps": current_health.avg_steps,
                "avg_sleep_hours": current_health.avg_sleep_hours,
                "avg_resting_hr": current_health.avg_resting_hr,
            },
            previous={
                "activities": prev_activities.total_count,
                "duration_hours": prev_activities.total_duration_hours,
                "distance_km": prev_activities.total_distance_km,
                "calories": prev_activities.total_calories,
                "avg_steps": prev_health.avg_steps,
                "avg_sleep_hours": prev_health.avg_sleep_hours,
                "avg_resting_hr": prev_health.avg_resting_hr,
            },
        )
        comparison.calculate_changes()
        return comparison

    def get_monthly_best_activities(
        self, start_date: date, end_date: date
    ) -> dict:
        """Find notable activities within a date range.

        Returns the longest distance, highest training load, and best
        aerobic efficiency (lowest absolute HR drift) activities.

        Args:
            start_date: Start of date range
            end_date: End of date range

        Returns:
            Dict with best activities by category (may be empty dicts
            if no qualifying activities found).
        """
        cursor = self.db.connection.cursor()
        sd = start_date.isoformat()
        ed = end_date.isoformat()

        result: dict[str, dict] = {
            "longest_distance": {},
            "highest_training_load": {},
            "best_aerobic_efficiency": {},
        }

        # Longest distance
        cursor.execute(
            """
            SELECT activity_name, activity_type, distance_meters,
                   date(start_time_local) AS act_date
            FROM activities
            WHERE date(start_time_local) BETWEEN ? AND ?
                AND distance_meters IS NOT NULL
            ORDER BY distance_meters DESC
            LIMIT 1
            """,
            (sd, ed),
        )
        row = cursor.fetchone()
        if row and row["distance_meters"]:
            result["longest_distance"] = {
                "name": row["activity_name"],
                "type": row["activity_type"],
                "distance_km": round(row["distance_meters"] / 1000, 2),
                "date": row["act_date"],
            }

        # Highest training load
        cursor.execute(
            """
            SELECT activity_name, activity_type, training_load,
                   date(start_time_local) AS act_date
            FROM activities
            WHERE date(start_time_local) BETWEEN ? AND ?
                AND training_load IS NOT NULL
            ORDER BY training_load DESC
            LIMIT 1
            """,
            (sd, ed),
        )
        row = cursor.fetchone()
        if row and row["training_load"]:
            result["highest_training_load"] = {
                "name": row["activity_name"],
                "type": row["activity_type"],
                "training_load": round(row["training_load"], 1),
                "date": row["act_date"],
            }

        # Best aerobic efficiency (lowest absolute HR drift)
        cursor.execute(
            """
            SELECT activity_name, activity_type, hr_drift,
                   date(start_time_local) AS act_date
            FROM activities
            WHERE date(start_time_local) BETWEEN ? AND ?
                AND hr_drift IS NOT NULL
            ORDER BY ABS(hr_drift) ASC
            LIMIT 1
            """,
            (sd, ed),
        )
        row = cursor.fetchone()
        if row and row["hr_drift"] is not None:
            result["best_aerobic_efficiency"] = {
                "name": row["activity_name"],
                "type": row["activity_type"],
                "hr_drift": round(row["hr_drift"], 3),
                "date": row["act_date"],
            }

        return result

    # ------------------------------------------------------------------
    # Tier 2: Personal Records
    # ------------------------------------------------------------------

    # Cardio PR distance buckets: (metric_name, target_meters, tolerance_pct)
    _CARDIO_PR_BUCKETS = [
        ("fastest_5k", 5000, 0.05),
        ("fastest_10k", 10000, 0.05),
        ("fastest_half_marathon", 21097, 0.05),
    ]

    _RUNNING_TYPES = frozenset({
        "running", "treadmill_running", "trail_running",
    })

    def detect_activity_prs(self, activity_id: str) -> list[dict]:
        """Check whether an activity sets any personal records.

        Detects:
        - Fastest 5K / 10K / half marathon (normalized pace)
        - Longest run (distance)
        - Highest training load (any activity type)

        Validates against the full activities table — not just the
        personal_records table — so PRs are correct even when the records
        table is empty or stale (e.g. activities synced before PR tracking
        was added).

        Calls ``repo.upsert_personal_record`` for each beaten record.

        Args:
            activity_id: The activity to evaluate

        Returns:
            List of PR dicts for any records set (empty if none).
        """
        from garmin_sync.db.repository import Repository

        cursor = self.db.connection.cursor()
        cursor.execute(
            """
            SELECT activity_id, activity_name, activity_type,
                   distance_meters, duration_seconds, training_load,
                   date(start_time_local) AS act_date
            FROM activities
            WHERE activity_id = ?
            """,
            (activity_id,),
        )
        row = cursor.fetchone()
        if not row:
            return []

        repo = Repository(self.db)
        new_prs: list[dict] = []
        act_date = row["act_date"] or date.today().isoformat()
        running_types_sql = ",".join(f"'{t}'" for t in self._RUNNING_TYPES)

        # --- Distance-based pace PRs (running only) ---
        if (
            row["activity_type"] in self._RUNNING_TYPES
            and row["distance_meters"]
            and row["duration_seconds"]
        ):
            for metric, target_m, tol in self._CARDIO_PR_BUCKETS:
                lo = target_m * (1 - tol)
                hi = target_m * (1 + tol)
                if lo <= row["distance_meters"] <= hi:
                    # Normalize to time-for-exact-distance
                    normalized_time = (
                        row["duration_seconds"] / row["distance_meters"]
                    ) * target_m

                    # Validate against ALL historical activities, not just
                    # the PR table.  Find the fastest normalized time from
                    # any other activity that covers this distance bucket.
                    cursor.execute(
                        f"""
                        SELECT MIN(
                            (duration_seconds / distance_meters) * {target_m}
                        ) AS best
                        FROM activities
                        WHERE activity_type IN ({running_types_sql})
                            AND distance_meters BETWEEN ? AND ?
                            AND duration_seconds IS NOT NULL
                            AND activity_id != ?
                        """,
                        (lo, hi, activity_id),
                    )
                    hist = cursor.fetchone()
                    historical_best = hist["best"] if hist and hist["best"] else None

                    if historical_best is None or normalized_time < historical_best:
                        pr = repo.upsert_personal_record(
                            category="cardio",
                            metric_name=metric,
                            value=round(normalized_time, 1),
                            date_set=act_date,
                            activity_id=activity_id,
                        )
                        if pr:
                            new_prs.append(pr)

            # Longest run — validate against all historical runs
            cursor.execute(
                f"""
                SELECT MAX(distance_meters) AS best
                FROM activities
                WHERE activity_type IN ({running_types_sql})
                    AND distance_meters IS NOT NULL
                    AND activity_id != ?
                """,
                (activity_id,),
            )
            hist = cursor.fetchone()
            historical_best = hist["best"] if hist and hist["best"] else 0
            if row["distance_meters"] > historical_best:
                pr = repo.upsert_personal_record(
                    category="cardio",
                    metric_name="longest_run",
                    value=round(row["distance_meters"], 1),
                    date_set=act_date,
                    activity_id=activity_id,
                )
                if pr:
                    new_prs.append(pr)

        # --- Highest training load (any activity) ---
        if row["training_load"]:
            # Validate against all historical activities
            cursor.execute(
                """
                SELECT MAX(training_load) AS best
                FROM activities
                WHERE training_load IS NOT NULL
                    AND activity_id != ?
                """,
                (activity_id,),
            )
            hist = cursor.fetchone()
            historical_best = hist["best"] if hist and hist["best"] else 0
            if row["training_load"] > historical_best:
                pr = repo.upsert_personal_record(
                    category="cardio",
                    metric_name="highest_training_load",
                    value=round(row["training_load"], 1),
                    date_set=act_date,
                    activity_id=activity_id,
                )
                if pr:
                    new_prs.append(pr)

        return new_prs

    def backfill_cardio_prs(self) -> list[dict]:
        """Re-scan all activities to set correct personal records.

        Fixes PRs that are wrong because activities were synced before
        PR tracking existed.  Safe to run multiple times.

        Returns:
            List of PR dicts that were set or updated.
        """
        from garmin_sync.db.repository import Repository

        cursor = self.db.connection.cursor()
        repo = Repository(self.db)
        results: list[dict] = []
        running_types_sql = ",".join(f"'{t}'" for t in self._RUNNING_TYPES)

        # --- Highest training load ---
        cursor.execute(
            """
            SELECT activity_id, training_load,
                   date(start_time_local) AS act_date
            FROM activities
            WHERE training_load IS NOT NULL
            ORDER BY training_load DESC
            LIMIT 1
            """
        )
        row = cursor.fetchone()
        if row and row["training_load"]:
            pr = repo.upsert_personal_record(
                category="cardio",
                metric_name="highest_training_load",
                value=round(row["training_load"], 1),
                date_set=row["act_date"] or date.today().isoformat(),
                activity_id=row["activity_id"],
            )
            if pr:
                results.append(pr)

        # --- Longest run ---
        cursor.execute(
            f"""
            SELECT activity_id, distance_meters,
                   date(start_time_local) AS act_date
            FROM activities
            WHERE activity_type IN ({running_types_sql})
                AND distance_meters IS NOT NULL
            ORDER BY distance_meters DESC
            LIMIT 1
            """
        )
        row = cursor.fetchone()
        if row and row["distance_meters"]:
            pr = repo.upsert_personal_record(
                category="cardio",
                metric_name="longest_run",
                value=round(row["distance_meters"], 1),
                date_set=row["act_date"] or date.today().isoformat(),
                activity_id=row["activity_id"],
            )
            if pr:
                results.append(pr)

        # --- Fastest pace PRs ---
        for metric, target_m, tol in self._CARDIO_PR_BUCKETS:
            lo = target_m * (1 - tol)
            hi = target_m * (1 + tol)
            cursor.execute(
                f"""
                SELECT activity_id,
                       (duration_seconds / distance_meters) * {target_m} AS norm_time,
                       date(start_time_local) AS act_date
                FROM activities
                WHERE activity_type IN ({running_types_sql})
                    AND distance_meters BETWEEN ? AND ?
                    AND duration_seconds IS NOT NULL
                ORDER BY norm_time ASC
                LIMIT 1
                """,
                (lo, hi),
            )
            row = cursor.fetchone()
            if row and row["norm_time"]:
                pr = repo.upsert_personal_record(
                    category="cardio",
                    metric_name=metric,
                    value=round(row["norm_time"], 1),
                    date_set=row["act_date"] or date.today().isoformat(),
                    activity_id=row["activity_id"],
                )
                if pr:
                    results.append(pr)

        return results

    def get_strength_prs(self, days: int = 7) -> list[dict]:
        """Surface HEVY-flagged strength PRs from recent workouts.

        HEVY marks sets as PRs when logged (``hevy_sets.is_pr = 1``).
        This method queries those flags and returns them with context.

        Args:
            days: Days to look back

        Returns:
            List of strength PR dicts with exercise, weight, reps, date.
        """
        cursor = self.db.connection.cursor()

        # Check table exists
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='hevy_sets'"
        )
        if not cursor.fetchone():
            return []

        start_date = (date.today() - timedelta(days=days)).isoformat()

        cursor.execute(
            """
            SELECT
                e.exercise_name,
                e.muscle_group,
                s.weight_kg,
                s.reps,
                w.start_time,
                w.title AS workout_title
            FROM hevy_sets s
            JOIN hevy_exercises e ON s.exercise_id = e.id
            JOIN hevy_workouts w ON e.workout_id = w.id
            WHERE s.is_pr = 1
                AND w.start_time >= ?
                AND s.set_type = 'normal'
            ORDER BY w.start_time DESC
            """,
            (start_date,),
        )
        rows = cursor.fetchall()

        KG_TO_LBS = 2.20462
        prs = []
        for row in rows:
            prs.append({
                "category": "strength",
                "exercise_name": row["exercise_name"],
                "muscle_group": row["muscle_group"],
                "weight_lbs": round((row["weight_kg"] or 0) * KG_TO_LBS),
                "reps": row["reps"],
                "date": row["start_time"][:10] if row["start_time"] else None,
                "workout_title": row["workout_title"],
            })

        return prs

    # ------------------------------------------------------------------
    # Pacing analysis (from activity_splits)
    # ------------------------------------------------------------------

    def get_pacing_analysis(self, activity_id: str) -> dict:
        """Pacing analysis for a single activity.

        Returns split count, average pace, coefficient of variation (CoV),
        negative split detection, fastest/slowest splits, and per-split
        detail.  Empty dict if no splits are available.
        """
        splits = self.repo.get_activity_splits(activity_id)
        if not splits:
            return {}

        # Only consider full km splits for pacing consistency
        full_splits = [s for s in splits if s["distance"] >= 999.0]
        if not full_splits:
            return {}

        paces = [s["pace_seconds_per_km"] for s in full_splits if s.get("pace_seconds_per_km")]
        if not paces:
            return {}

        import statistics

        avg_pace = statistics.mean(paces)
        stdev = statistics.stdev(paces) if len(paces) > 1 else 0.0
        cov = stdev / avg_pace if avg_pace > 0 else 0.0

        # Negative split: second half faster than first half
        mid = len(paces) // 2
        if mid > 0 and len(paces) > 1:
            first_half_avg = statistics.mean(paces[:mid])
            second_half_avg = statistics.mean(paces[mid:])
            is_negative = second_half_avg < first_half_avg
        else:
            is_negative = False

        def _fmt_pace(secs: float) -> str:
            m, s = divmod(int(secs), 60)
            return f"{m}:{s:02d}/km"

        fastest = min(full_splits, key=lambda s: s.get("pace_seconds_per_km", 9999))
        slowest = max(full_splits, key=lambda s: s.get("pace_seconds_per_km", 0))

        return {
            "split_count": len(full_splits),
            "avg_pace": _fmt_pace(avg_pace),
            "avg_pace_seconds": round(avg_pace, 1),
            "pace_cov": round(cov, 4),
            "is_negative_split": is_negative,
            "fastest_split": {
                "index": fastest["split_index"],
                "pace": _fmt_pace(fastest["pace_seconds_per_km"]),
            },
            "slowest_split": {
                "index": slowest["split_index"],
                "pace": _fmt_pace(slowest["pace_seconds_per_km"]),
            },
            "splits": [
                {
                    "km": s["split_index"],
                    "pace": _fmt_pace(s["pace_seconds_per_km"]) if s.get("pace_seconds_per_km") else None,
                    "hr": s.get("avg_heart_rate"),
                }
                for s in full_splits
            ],
        }

    def get_pacing_trends(
        self,
        start_date: date | str,
        end_date: date | str,
    ) -> dict:
        """Pacing consistency across activities in a date range.

        Returns activities_with_splits, average pace CoV across all
        activities, percentage of runs with negative splits, and a
        per-activity trend list.

        The *consistency_rating* key uses:
          CoV < 0.05 = good, < 0.08 = moderate, else = variable
        """
        import statistics

        if isinstance(start_date, date):
            start_date = start_date.isoformat()
        if isinstance(end_date, date):
            end_date = end_date.isoformat()

        cursor = self.db.connection.cursor()

        # Check if fit_parsed column exists (added in migration v5→v6).
        cursor.execute("PRAGMA table_info(activities)")
        columns = {row[1] for row in cursor.fetchall()}
        has_fit_parsed = "fit_parsed" in columns

        fit_filter = "AND a.fit_parsed = 1" if has_fit_parsed else ""
        cursor.execute(
            f"""
            SELECT a.activity_id, a.activity_type, a.start_time_local, a.distance_meters
            FROM activities a
            WHERE a.start_time_local >= ? AND a.start_time_local <= ?
              {fit_filter}
            ORDER BY a.start_time_local
            """,
            (start_date, end_date + "T23:59:59"),
        )
        activities = cursor.fetchall()

        trend: list[dict] = []
        covs: list[float] = []
        neg_count = 0
        total = 0

        for row in activities:
            analysis = self.get_pacing_analysis(row["activity_id"])
            if not analysis:
                continue

            total += 1
            covs.append(analysis["pace_cov"])
            if analysis["is_negative_split"]:
                neg_count += 1

            trend.append({
                "date": row["start_time_local"][:10] if row["start_time_local"] else None,
                "activity_type": row["activity_type"],
                "splits": analysis["split_count"],
                "avg_pace": analysis["avg_pace"],
                "pace_cov": analysis["pace_cov"],
                "negative_split": analysis["is_negative_split"],
            })

        if not covs:
            return {"activities_with_splits": 0}

        avg_cov = statistics.mean(covs)
        if avg_cov < 0.05:
            rating = "good"
        elif avg_cov < 0.08:
            rating = "moderate"
        else:
            rating = "variable"

        return {
            "activities_with_splits": total,
            "avg_pace_cov": round(avg_cov, 4),
            "negative_split_pct": round(neg_count / total * 100, 1) if total else 0,
            "consistency_rating": rating,
            "trend": trend,
        }

    # ------------------------------------------------------------------
    # All-day respiration & SpO2 (from dedicated daily tables)
    # ------------------------------------------------------------------

    def get_allday_respiration_spo2(
        self, start_date: date, end_date: date
    ) -> dict:
        """Recent all-day respiration and SpO2 averages.

        Queries the ``respiration_daily`` and ``spo2_daily`` tables
        (separate from sleep-only metrics in ``sleep_daily``).

        Returns dict with ``avg_respiration``, ``avg_spo2``, ``min_spo2``,
        and ``data_points``.  All values are None when no data exists.
        """
        cursor = self.db.connection.cursor()
        out: dict = {
            "avg_respiration": None,
            "avg_spo2": None,
            "min_spo2": None,
            "data_points": 0,
        }

        # Respiration
        try:
            cursor.execute(
                """
                SELECT AVG(avg_respiration) AS avg_resp,
                       COUNT(*) AS cnt
                FROM respiration_daily
                WHERE date >= ? AND date <= ?
                  AND avg_respiration IS NOT NULL
                """,
                (start_date.isoformat(), end_date.isoformat()),
            )
            row = cursor.fetchone()
            if row and row["cnt"]:
                out["avg_respiration"] = round(row["avg_resp"], 1)
                out["data_points"] += row["cnt"]
        except Exception:
            pass  # Table may not exist on old schemas

        # SpO2
        try:
            cursor.execute(
                """
                SELECT AVG(avg_spo2) AS avg_spo2,
                       MIN(min_spo2) AS min_spo2,
                       COUNT(*) AS cnt
                FROM spo2_daily
                WHERE date >= ? AND date <= ?
                  AND avg_spo2 IS NOT NULL
                """,
                (start_date.isoformat(), end_date.isoformat()),
            )
            row = cursor.fetchone()
            if row and row["cnt"]:
                out["avg_spo2"] = round(row["avg_spo2"], 1)
                out["min_spo2"] = row["min_spo2"]
                out["data_points"] += row["cnt"]
        except Exception:
            pass

        return out
