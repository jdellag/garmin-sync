"""Shared tool executor for fitness data tools."""

from datetime import date, timedelta
from typing import Any

from garmin_sync.db.repository import Repository
from garmin_sync.reports.aggregators import DataAggregator

KG_TO_LBS = 2.20462


class ToolExecutor:
    """Executes fitness data tools against the database.

    This class provides a unified interface for tool execution,
    used by both MCP server and OpenAI tool calling.
    """

    def __init__(self, repository: Repository, aggregator: DataAggregator):
        """Initialize executor with database connections.

        Args:
            repository: Database repository for data access
            aggregator: Data aggregator for computed metrics
        """
        self.repo = repository
        self.agg = aggregator

    def execute(self, tool_name: str, arguments: dict[str, Any]) -> dict | list:
        """Dispatch to the appropriate tool method.

        Args:
            tool_name: Name of the tool to execute
            arguments: Tool arguments as a dictionary

        Returns:
            Tool result as dict or list

        Raises:
            ValueError: If tool_name is unknown
        """
        method = getattr(self, tool_name, None)
        if method is None:
            raise ValueError(f"Unknown tool: {tool_name}")
        return method(**arguments)

    def get_recent_activities(
        self,
        days: int = 7,
        activity_type: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """Get recent Garmin activities with metrics.

        Args:
            days: Days to look back (default: 7)
            activity_type: Filter by type (running, cycling, swimming, etc.)
            limit: Max results (default: 20)

        Returns:
            List of activities with: name, type, duration, distance, HR, training load, HR drift.
        """
        start = (date.today() - timedelta(days=days)).isoformat()
        activities = self.repo.get_activities(
            start_date=start,
            activity_type=activity_type,
            limit=limit,
        )
        return self._serialize_activities(activities)

    def get_recovery_status(self) -> dict:
        """Get current recovery metrics for training decisions.

        Returns:
            Dict with HRV (baseline, delta, status), sleep (hours, score,
            respiration, SpO2), body battery (recovery, weekday/weekend),
            resting HR (trend), and training readiness (with weakest component).
        """
        today = date.today()
        week_ago = today - timedelta(days=6)
        month_ago = today - timedelta(days=28)

        hrv = self.agg.get_hrv_context(today)
        sleep = self.agg.get_sleep_consistency(week_ago, today)
        bb = self.agg.get_body_battery_recovery(week_ago, today)
        rhr = self.agg.get_resting_hr_trend(today)
        readiness = self.agg.get_training_readiness_latest(today)
        respiration = self.agg.get_sleep_respiration_trends(week_ago, today)
        allday_resp = self.agg.get_allday_respiration_spo2(week_ago, today)
        stress_recovery = self.agg.get_stress_recovery_correlation(month_ago, today)
        sleep_performance = self.agg.get_sleep_performance_correlation(month_ago, today)

        # Identify weakest training-readiness component
        component_keys = [
            "sleep_score", "recovery_score", "hrv_score",
            "stress_history_score", "training_load_balance_score",
        ]
        weakest = None
        lowest = None
        for key in component_keys:
            val = readiness.get(key)
            if val is not None and (lowest is None or val < lowest):
                lowest = val
                weakest = key

        readiness_out = dict(readiness)
        readiness_out["weakest_component"] = weakest

        result = {
            "hrv": {
                "baseline_7d": hrv.get("baseline_7d"),
                "last_night": hrv.get("last_night"),
                "delta_pct": hrv.get("delta_from_baseline"),
                "status": hrv.get("status"),
                "days_below_baseline": hrv.get("days_below_baseline", 0),
            },
            "sleep": {
                "avg_hours": (
                    round(sleep.get("avg_sleep_seconds", 0) / 3600, 1)
                    if sleep.get("avg_sleep_seconds")
                    else None
                ),
                "bedtime_variance_mins": sleep.get("sleep_time_variance_mins"),
                "avg_deep_pct": sleep.get("avg_deep_pct"),
                "avg_rem_pct": sleep.get("avg_rem_pct"),
                "avg_respiration": respiration.get("avg_respiration"),
                "avg_spo2": respiration.get("avg_spo2"),
                "allday_avg_respiration": allday_resp.get("avg_respiration"),
                "allday_avg_spo2": allday_resp.get("avg_spo2"),
                "allday_min_spo2": allday_resp.get("min_spo2"),
            },
            "body_battery": {
                "overnight_recovery": bb.get("avg_overnight_recovery"),
                "avg_morning_high": bb.get("avg_morning_high"),
                "weekday_avg_recovery": bb.get("weekday_avg_recovery"),
                "weekend_avg_recovery": bb.get("weekend_avg_recovery"),
            },
            "resting_hr": {
                "current": rhr.get("current"),
                "baseline_28d": rhr.get("baseline_28d"),
                "delta": rhr.get("delta"),
                "trend": rhr.get("trend"),
            },
            "training_readiness": readiness_out,
            "stress_recovery": {
                "stress_on_training_days": stress_recovery.get("avg_stress_training_days"),
                "stress_on_rest_days": stress_recovery.get("avg_stress_rest_days"),
                "high_stress_poor_recovery_days": stress_recovery.get(
                    "high_stress_poor_recovery_days", 0
                ),
                "patterns": stress_recovery.get("patterns", []),
            },
            "sleep_performance": {
                "data_points": sleep_performance.get("data_points", 0),
                "by_sleep_grade": sleep_performance.get("by_sleep_grade", {}),
                "hrv_performance_link": sleep_performance.get("hrv_performance_link"),
                "insight": sleep_performance.get("insight"),
            },
            "last_sync": self.repo.get_latest_sync_timestamp(),
        }

        # Enrich with anomaly detection
        try:
            from garmin_sync.reports.anomaly_detector import AnomalyDetector

            detector = AnomalyDetector(self.repo.db)
            anomalies = detector.detect_anomalies()
            if anomalies:
                result["anomalies"] = anomalies
        except Exception:
            pass

        return result

    def get_training_load_analysis(self) -> dict:
        """Analyze training load for injury prevention.

        Returns:
            Dict with acute (7d) and chronic (28d) load, acute:chronic ratio,
            week-over-week change, breakdown by activity type, and risk assessment.

            A:C ratio thresholds: <0.8 detraining, 0.8-1.3 optimal, >1.5 high risk.
        """
        load = self.agg.get_training_load_trend(date.today())

        ac = load.get("acute_chronic_ratio")
        if ac is None:
            risk = "insufficient_data"
        elif ac < 0.8:
            risk = "detraining"
        elif ac <= 1.3:
            risk = "optimal"
        elif ac <= 1.5:
            risk = "building"
        else:
            risk = "high_risk"

        return {
            "acute_load_7d": load.get("acute_load_7d"),
            "chronic_load_28d": load.get("chronic_load_28d"),
            "acute_chronic_ratio": ac,
            "week_change_pct": load.get("week_change_pct"),
            "by_activity_type": load.get("by_type", {}),
            "risk_assessment": risk,
            "avg_training_effect_aerobic": load.get("avg_training_effect_aerobic"),
            "avg_training_effect_anaerobic": load.get("avg_training_effect_anaerobic"),
            "training_effect_balance": load.get("training_effect_balance"),
        }

    def get_strength_training_summary(self, days: int = 7) -> dict:
        """Get HEVY strength training summary.

        Args:
            days: Days to analyze (default: 7)

        Returns:
            Dict with sessions, total volume (lbs), sets by muscle group,
            and recent workouts with exercise details.
        """
        count = self.repo.get_hevy_workout_count(days=days)

        if count == 0:
            return {
                "configured": True,
                "total_sessions": 0,
                "message": f"No workouts in last {days} days",
            }

        data = self.agg.get_strength_volume_summary(days=days)

        by_muscle = {}
        for group, info in data.get("by_muscle_group", {}).items():
            by_muscle[group] = {
                "volume_lbs": round((info.get("volume_kg", 0) or 0) * KG_TO_LBS),
                "sets": info.get("sets", 0),
            }

        result = {
            "configured": True,
            "total_sessions": data.get("total_sessions", 0),
            "total_volume_lbs": round((data.get("total_volume_kg", 0) or 0) * KG_TO_LBS),
            "total_sets": data.get("total_sets", 0),
            "by_muscle_group": by_muscle,
            "recent_workouts": data.get("recent_workouts", []),
        }

        # Add RPE analysis if RPE data exists
        rpe_data = self.agg.get_rpe_analysis(days=days)
        if rpe_data.get("rpe_coverage_pct", 0) > 0:
            result["rpe"] = {
                "avg_session_rpe": rpe_data.get("overall_avg_rpe"),
                "rpe_coverage_pct": rpe_data.get("rpe_coverage_pct"),
                "overreaching_flag": rpe_data.get("overreaching_flag", False),
            }

        # Add strength PRs from HEVY's is_pr flag
        strength_prs = self.agg.get_strength_prs(days=days)
        if strength_prs:
            result["prs"] = strength_prs

        return result

    def get_exercise_progression(self, exercise_name: str, days: int = 90) -> dict:
        """Track strength progression for a specific exercise.

        Args:
            exercise_name: Exercise to track (e.g., "Bench Press", "Squat")
            days: Days to analyze (default: 90)

        Returns:
            Dict with estimated 1RM, max weights, and progression percentage.
        """
        data = self.agg.get_strength_exercise_progression(exercise_name, days=days)

        if not data.get("sessions"):
            return {
                "exercise": exercise_name,
                "found": False,
                "message": f"No data found for '{exercise_name}' in last {days} days",
            }

        # Get RPE trend for this exercise
        rpe_data = self.agg.get_exercise_rpe_trend(exercise_name, days=days)
        rpe_by_date = {
            s["date"]: s.get("avg_rpe")
            for s in rpe_data.get("sessions", [])
        }

        sessions = []
        for s in data.get("sessions", []):
            entry = {
                "date": s.get("date"),
                "max_weight_lbs": round((s.get("max_weight") or 0) * KG_TO_LBS),
                "est_1rm_lbs": round((s.get("est_1rm") or 0) * KG_TO_LBS) if s.get("est_1rm") else None,
            }
            # Merge RPE data for this session date
            rpe_val = rpe_by_date.get(s.get("date"))
            if rpe_val is not None:
                entry["avg_rpe"] = rpe_val
            sessions.append(entry)

        result = {
            "exercise": exercise_name,
            "found": True,
            "sessions": sessions,
            "current_1rm_lbs": round((data.get("current_1rm") or 0) * KG_TO_LBS) if data.get("current_1rm") else None,
            "progression_pct": data.get("progression_pct"),
        }

        if rpe_data.get("rpe_trend"):
            result["rpe_trend"] = rpe_data["rpe_trend"]

        return result

    def get_workout_details(self, days: int = 7) -> list[dict]:
        """Get detailed HEVY workouts with exercise and set breakdown.

        Args:
            days: Days to look back (default: 7)

        Returns:
            List of workouts with exercises and sets (e.g., "135x10, 155x8").
        """
        return self.repo.get_hevy_workout_details(days=days)

    def get_weekly_comparison(self) -> dict:
        """Compare this week vs last week across all metrics.

        Returns:
            Dict with current week, previous week, percentage changes,
            and month-to-date context (accumulated totals for this month
            plus previous month's completed totals).
        """
        today = date.today()
        comparison = self.agg.get_weekly_comparison(today)

        # Month-to-date context
        month_start = today.replace(day=1)
        mtd_activities = self.agg.get_activity_summary(month_start, today)

        # Previous month totals
        import calendar
        if today.month == 1:
            prev_year, prev_month = today.year - 1, 12
        else:
            prev_year, prev_month = today.year, today.month - 1
        _, prev_days = calendar.monthrange(prev_year, prev_month)
        prev_start = date(prev_year, prev_month, 1)
        prev_end = date(prev_year, prev_month, prev_days)
        prev_activities = self.agg.get_activity_summary(prev_start, prev_end)

        return {
            "current_week": comparison.current,
            "previous_week": comparison.previous,
            "changes_pct": comparison.changes,
            "month_to_date": {
                "activities": mtd_activities.total_count,
                "duration_hours": mtd_activities.total_duration_hours,
                "distance_km": mtd_activities.total_distance_km,
            },
            "previous_month": {
                "activities": prev_activities.total_count,
                "duration_hours": prev_activities.total_duration_hours,
                "distance_km": prev_activities.total_distance_km,
            },
            "prs_this_week": (
                self.repo.get_recent_prs(days=7)
                + self.agg.get_strength_prs(days=7)
            ),
        }

    def get_longitudinal_summary(
        self,
        start_year: int | None = None,
        end_year: int | None = None,
        granularity: str = "year",
    ) -> dict:
        """Multi-year fitness summary across aerobic efficiency, health baselines, volume, drift.

        Args:
            start_year: First year (default: earliest year present in sleep_daily).
            end_year: Last year (default: current year).
            granularity: 'year' or 'quarter'.

        Returns dict with keys: aerobic_efficiency, health_baselines, volume, hr_drift, range.
        """
        if granularity not in ("year", "quarter"):
            granularity = "year"

        today = date.today()
        if end_year is None:
            end_year = today.year
        if start_year is None:
            cursor = self.repo.db.connection.cursor()
            cursor.execute("SELECT MIN(date) AS d FROM sleep_daily")
            row = cursor.fetchone()
            start_year = int(row["d"][:4]) if row and row["d"] else 2021

        return {
            "aerobic_efficiency": self.agg.get_aerobic_efficiency_by_period(
                start_year, end_year, granularity
            ),
            "health_baselines": self.agg.get_yearly_health_baselines(start_year, end_year),
            "volume": self.agg.get_volume_by_period(start_year, end_year, granularity),
            "hr_drift": self.agg.get_hr_drift_by_period(start_year, end_year),
            "range": {
                "start_year": start_year,
                "end_year": end_year,
                "granularity": granularity,
            },
        }

    def get_cardio_performance(self, days: int = 28) -> dict:
        """Get cardio performance metrics.

        Bundles running cadence trends, VO2 max progression, elevation
        summary, and aerobic/anaerobic training effect balance.

        Args:
            days: Number of days to analyse (default: 28)

        Returns:
            Dict with cadence, vo2_max, elevation, and training_effect
            sections.
        """
        today = date.today()
        start = today - timedelta(days=days - 1)

        cadence = self.agg.get_cadence_analysis(start, today)
        vo2 = self.agg.get_vo2_max_trend(start, today)
        elevation = self.agg.get_elevation_summary(start, today)
        load = self.agg.get_training_load_trend(today)
        pacing = self.agg.get_pacing_trends(start, today)

        result = {
            "cadence": {
                "avg": cadence.get("avg_cadence"),
                "max": cadence.get("max_cadence"),
                "total_activities": cadence.get("total_activities_with_cadence", 0),
                "weekly_trend": cadence.get("weekly_trend", []),
                "by_type": cadence.get("by_activity_type", {}),
            },
            "vo2_max": {
                "current": vo2.get("current"),
                "delta": vo2.get("delta"),
                "trend": vo2.get("trend"),
                "data_points": vo2.get("data_points", 0),
                "values": vo2.get("values", []),
            },
            "elevation": {
                "total_gain_meters": elevation.get("total_gain_meters"),
                "total_loss_meters": elevation.get("total_loss_meters"),
                "total_activities": elevation.get("total_activities", 0),
                "vert_per_hour": elevation.get("vert_per_hour"),
                "by_type": elevation.get("by_activity_type", {}),
            },
            "training_effect": {
                "avg_aerobic": load.get("avg_training_effect_aerobic"),
                "avg_anaerobic": load.get("avg_training_effect_anaerobic"),
                "balance": load.get("training_effect_balance"),
            },
        }

        if pacing.get("activities_with_splits", 0) > 0:
            result["pacing"] = {
                "activities_with_splits": pacing["activities_with_splits"],
                "avg_pace_cov": pacing.get("avg_pace_cov"),
                "negative_split_pct": pacing.get("negative_split_pct"),
                "consistency_rating": pacing.get("consistency_rating"),
            }

        return result

    def get_anomaly_report(self) -> dict:
        """Scan recent health and training data for anomalies.

        Returns:
            Dict with anomaly list (sorted by severity) and summary
            counts per severity level.
        """
        from garmin_sync.reports.anomaly_detector import AnomalyDetector

        detector = AnomalyDetector(self.repo.db)
        anomalies = detector.detect_anomalies()

        summary = {"critical": 0, "warning": 0, "info": 0}
        for a in anomalies:
            summary[a["severity"]] = summary.get(a["severity"], 0) + 1

        return {
            "anomalies": anomalies,
            "summary": summary,
            "total": len(anomalies),
        }

    def get_periodization_status(self) -> dict:
        """Get current training phase, readiness score, and deload recommendation.

        Returns:
            Dict with ``phase``, ``readiness`` (0-100 composite score with
            traffic-light signal), and ``deload`` recommendation.
        """
        from garmin_sync.reports.periodization import PeriodizationAnalyzer

        analyzer = PeriodizationAnalyzer(self.repo.db)
        return analyzer.get_periodization_summary()

    def sync_garmin_data(self, days: int = 1) -> dict:
        """Sync latest data from Garmin Connect (and HEVY if configured).

        Args:
            days: Days to sync (default: 1 for today only)

        Returns:
            Dict with sync results for each data type.
        """
        from garmin_sync.sync.sync_manager import SyncManager

        try:
            sync_manager = SyncManager(db=self.repo.db)
            results = sync_manager.sync_all(days=days, force=False, detailed=False)

            synced = {}
            errors = []
            for data_type, result in results.items():
                synced[data_type] = result.records_synced
                errors.extend(result.errors)

            return {
                "success": len(errors) == 0,
                "synced": synced,
                "errors": errors[:5],  # Limit error output
            }
        except Exception as e:
            return {
                "success": False,
                "synced": {},
                "errors": [str(e)],
            }

    def _serialize_activities(self, activities: list) -> list[dict]:
        """Serialize activity models to dicts for JSON output."""
        result = []
        for act in activities:
            data = {
                "activity_id": act.activity_id,
                "name": act.activity_name,
                "type": act.activity_type,
                "start_time": act.start_time,
                "start_time_local": act.start_time_local,
                "duration_seconds": act.duration_seconds,
                "distance_meters": act.distance_meters,
                "average_hr": act.average_hr,
                "max_hr": act.max_hr,
                "calories": act.calories,
                "training_load": act.training_load,
                "training_effect_aerobic": act.training_effect_aerobic,
                "training_effect_anaerobic": act.training_effect_anaerobic,
                "hr_drift": act.hr_drift,
                "elevation_gain_meters": act.elevation_gain_meters,
                "avg_cadence": act.avg_cadence,
                "max_cadence": act.max_cadence,
                "vo2_max": act.vo2_max,
            }
            # Calculate pace for running activities
            if act.distance_meters and act.duration_seconds and act.activity_type in (
                "running", "treadmill_running", "trail_running"
            ):
                pace_sec_per_km = act.duration_seconds / (act.distance_meters / 1000)
                data["pace_min_per_km"] = round(pace_sec_per_km / 60, 2)

            # Add splits summary for activities with FIT-parsed split data
            if getattr(act, "fit_parsed", False):
                pacing = self.agg.get_pacing_analysis(act.activity_id)
                if pacing:
                    data["splits_summary"] = {
                        "count": pacing["split_count"],
                        "avg_pace": pacing["avg_pace"],
                        "pace_cov": pacing["pace_cov"],
                        "is_negative_split": pacing["is_negative_split"],
                    }

            result.append(data)
        return result
