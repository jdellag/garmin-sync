"""Data access layer for CRUD operations."""

import json
from datetime import date, datetime, timedelta
from typing import Optional

from garmin_sync.db.database import Database
from garmin_sync.db.models import (
    Activity,
    BodyBatteryDaily,
    ChatMessage,
    DailySummary,
    HeartRateDaily,
    HRVDaily,
    SleepDaily,
    StressDaily,
    SyncMetadata,
    TrainingReadiness,
)
from garmin_sync.hevy.models import HevyExerciseTemplate, HevyWorkout


class Repository:
    """Data access repository for Garmin data."""

    def __init__(self, db: Database):
        """Initialize repository with database connection."""
        self.db = db

    # ==================== Sync Metadata ====================

    def get_sync_metadata(self, data_type: str) -> Optional[SyncMetadata]:
        """Get sync metadata for a data type."""
        cursor = self.db.connection.cursor()
        cursor.execute(
            "SELECT * FROM sync_metadata WHERE data_type = ?",
            (data_type,)
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return SyncMetadata(
            data_type=row["data_type"],
            last_sync_timestamp=row["last_sync_timestamp"],
            last_sync_date=row["last_sync_date"],
            sync_status=row["sync_status"],
            records_synced=row["records_synced"],
            error_message=row["error_message"],
        )

    def update_sync_metadata(self, metadata: SyncMetadata) -> None:
        """Insert or update sync metadata."""
        with self.db.transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO sync_metadata
                    (data_type, last_sync_timestamp, last_sync_date, sync_status,
                     records_synced, error_message)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(data_type) DO UPDATE SET
                    last_sync_timestamp = excluded.last_sync_timestamp,
                    last_sync_date = excluded.last_sync_date,
                    sync_status = excluded.sync_status,
                    records_synced = excluded.records_synced,
                    error_message = excluded.error_message
                """,
                (
                    metadata.data_type,
                    metadata.last_sync_timestamp,
                    metadata.last_sync_date,
                    metadata.sync_status,
                    metadata.records_synced,
                    metadata.error_message,
                )
            )

    # ==================== Activities ====================

    def activity_exists(self, activity_id: str) -> bool:
        """Check if an activity exists."""
        cursor = self.db.connection.cursor()
        cursor.execute(
            "SELECT 1 FROM activities WHERE activity_id = ?",
            (activity_id,)
        )
        return cursor.fetchone() is not None

    def get_activity(self, activity_id: str) -> Optional[Activity]:
        """Get an activity by ID."""
        cursor = self.db.connection.cursor()
        cursor.execute(
            "SELECT * FROM activities WHERE activity_id = ?",
            (activity_id,)
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return self._row_to_activity(row)

    def get_activities(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        activity_type: Optional[str] = None,
        limit: int = 100,
    ) -> list[Activity]:
        """Get activities with optional filtering."""
        query = "SELECT * FROM activities WHERE 1=1"
        params: list = []

        if start_date:
            query += " AND start_time >= ?"
            params.append(start_date)
        if end_date:
            query += " AND start_time <= ?"
            params.append(end_date)
        if activity_type:
            query += " AND activity_type = ?"
            params.append(activity_type)

        query += " ORDER BY start_time DESC LIMIT ?"
        params.append(limit)

        cursor = self.db.connection.cursor()
        cursor.execute(query, params)
        return [self._row_to_activity(row) for row in cursor.fetchall()]

    def get_activities_by_local_date(
        self,
        local_date: str,
        activity_type: Optional[str] = None,
    ) -> list[Activity]:
        """Get activities for a specific local date.

        Uses start_time_local column to correctly match activities
        by the user's local date, avoiding UTC timezone issues.

        Args:
            local_date: Date string in YYYY-MM-DD format (local timezone)
            activity_type: Optional filter by activity type

        Returns:
            List of activities that occurred on the specified local date
        """
        query = "SELECT * FROM activities WHERE date(start_time_local) = ?"
        params: list = [local_date]

        if activity_type:
            query += " AND activity_type = ?"
            params.append(activity_type)

        query += " ORDER BY start_time_local DESC"

        cursor = self.db.connection.cursor()
        cursor.execute(query, params)
        return [self._row_to_activity(row) for row in cursor.fetchall()]

    def get_latest_sync_timestamp(self) -> Optional[str]:
        """Get the most recent sync timestamp across all data types.

        Returns:
            ISO timestamp string of the most recent sync, or None if no syncs
        """
        cursor = self.db.connection.cursor()
        cursor.execute(
            """
            SELECT MAX(last_sync_timestamp) as latest
            FROM sync_metadata
            WHERE sync_status = 'success'
            """
        )
        row = cursor.fetchone()
        return row["latest"] if row else None

    def upsert_activity(self, activity: Activity) -> None:
        """Insert or update an activity."""
        with self.db.transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO activities (
                    activity_id, activity_name, activity_type, start_time,
                    start_time_local, timezone, duration_seconds, moving_duration_seconds,
                    distance_meters, average_speed_mps, max_speed_mps,
                    average_hr, max_hr, min_hr,
                    elevation_gain_meters, elevation_loss_meters, calories,
                    training_effect_aerobic, training_effect_anaerobic,
                    training_load, vo2_max, avg_cadence, max_cadence,
                    average_power, max_power, normalized_power,
                    device_name, has_fit_file, fit_file_path, hr_drift, raw_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(activity_id) DO UPDATE SET
                    activity_name = excluded.activity_name,
                    activity_type = excluded.activity_type,
                    duration_seconds = excluded.duration_seconds,
                    distance_meters = excluded.distance_meters,
                    average_hr = excluded.average_hr,
                    max_hr = excluded.max_hr,
                    calories = excluded.calories,
                    hr_drift = excluded.hr_drift,
                    raw_json = excluded.raw_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    activity.activity_id,
                    activity.activity_name,
                    activity.activity_type,
                    activity.start_time,
                    activity.start_time_local,
                    activity.timezone,
                    activity.duration_seconds,
                    activity.moving_duration_seconds,
                    activity.distance_meters,
                    activity.average_speed_mps,
                    activity.max_speed_mps,
                    activity.average_hr,
                    activity.max_hr,
                    activity.min_hr,
                    activity.elevation_gain_meters,
                    activity.elevation_loss_meters,
                    activity.calories,
                    activity.training_effect_aerobic,
                    activity.training_effect_anaerobic,
                    activity.training_load,
                    activity.vo2_max,
                    activity.avg_cadence,
                    activity.max_cadence,
                    activity.average_power,
                    activity.max_power,
                    activity.normalized_power,
                    activity.device_name,
                    1 if activity.has_fit_file else 0,
                    activity.fit_file_path,
                    activity.hr_drift,
                    activity.raw_json,
                )
            )

    def get_activity_ids(self, since_date: Optional[str] = None) -> set[str]:
        """Get set of activity IDs for efficient deduplication."""
        cursor = self.db.connection.cursor()
        if since_date:
            cursor.execute(
                "SELECT activity_id FROM activities WHERE start_time >= ?",
                (since_date,)
            )
        else:
            cursor.execute("SELECT activity_id FROM activities")
        return {row[0] for row in cursor.fetchall()}

    def _row_to_activity(self, row) -> Activity:
        """Convert database row to Activity model."""
        return Activity(
            activity_id=row["activity_id"],
            activity_name=row["activity_name"],
            activity_type=row["activity_type"],
            start_time=row["start_time"],
            start_time_local=row["start_time_local"],
            timezone=row["timezone"],
            duration_seconds=row["duration_seconds"],
            moving_duration_seconds=row["moving_duration_seconds"],
            distance_meters=row["distance_meters"],
            average_speed_mps=row["average_speed_mps"],
            max_speed_mps=row["max_speed_mps"],
            average_hr=row["average_hr"],
            max_hr=row["max_hr"],
            min_hr=row["min_hr"],
            elevation_gain_meters=row["elevation_gain_meters"],
            elevation_loss_meters=row["elevation_loss_meters"],
            calories=row["calories"],
            training_effect_aerobic=row["training_effect_aerobic"],
            training_effect_anaerobic=row["training_effect_anaerobic"],
            training_load=row["training_load"],
            vo2_max=row["vo2_max"],
            avg_cadence=row["avg_cadence"],
            max_cadence=row["max_cadence"],
            average_power=row["average_power"],
            max_power=row["max_power"],
            normalized_power=row["normalized_power"],
            device_name=row["device_name"],
            has_fit_file=bool(row["has_fit_file"]),
            fit_file_path=row["fit_file_path"],
            hr_drift=row["hr_drift"],
            raw_json=row["raw_json"],
        )

    # ==================== Existence Checks ====================

    _ALLOWED_DAILY_TABLES = frozenset({
        "heart_rate_daily",
        "sleep_daily",
        "stress_daily",
        "hrv_daily",
        "training_readiness",
        "body_battery_daily",
    })

    def has_daily_record(self, table: str, date_str: str) -> bool:
        """Return True if a row already exists for this date in the given table.

        ``table`` is validated against an allowlist to prevent SQL injection.
        """
        if table not in self._ALLOWED_DAILY_TABLES:
            raise ValueError(f"Invalid table name: {table!r}")
        cursor = self.db.connection.cursor()
        cursor.execute(f"SELECT 1 FROM {table} WHERE date = ? LIMIT 1", (date_str,))
        return cursor.fetchone() is not None

    # ==================== Daily Summaries ====================

    def upsert_daily_summary(self, summary: DailySummary) -> None:
        """Insert or update a daily summary."""
        with self.db.transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO daily_summaries (
                    date, total_steps, step_goal, steps_distance_meters,
                    total_calories, active_calories, bmr_calories,
                    highly_active_seconds, active_seconds, sedentary_seconds,
                    floors_ascended, floors_descended, raw_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(date) DO UPDATE SET
                    total_steps = excluded.total_steps,
                    step_goal = excluded.step_goal,
                    total_calories = excluded.total_calories,
                    raw_json = excluded.raw_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    summary.date,
                    summary.total_steps,
                    summary.step_goal,
                    summary.steps_distance_meters,
                    summary.total_calories,
                    summary.active_calories,
                    summary.bmr_calories,
                    summary.highly_active_seconds,
                    summary.active_seconds,
                    summary.sedentary_seconds,
                    summary.floors_ascended,
                    summary.floors_descended,
                    summary.raw_json,
                )
            )

    def get_daily_summary(self, date: str) -> Optional[DailySummary]:
        """Get daily summary for a date."""
        cursor = self.db.connection.cursor()
        cursor.execute("SELECT * FROM daily_summaries WHERE date = ?", (date,))
        row = cursor.fetchone()
        if row is None:
            return None
        return DailySummary(
            date=row["date"],
            total_steps=row["total_steps"],
            step_goal=row["step_goal"],
            steps_distance_meters=row["steps_distance_meters"],
            total_calories=row["total_calories"],
            active_calories=row["active_calories"],
            bmr_calories=row["bmr_calories"],
            highly_active_seconds=row["highly_active_seconds"],
            active_seconds=row["active_seconds"],
            sedentary_seconds=row["sedentary_seconds"],
            floors_ascended=row["floors_ascended"],
            floors_descended=row["floors_descended"],
            raw_json=row["raw_json"],
        )

    # ==================== Sleep ====================

    def upsert_sleep(self, sleep: SleepDaily) -> None:
        """Insert or update sleep data."""
        with self.db.transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO sleep_daily (
                    date, sleep_start, sleep_end, total_sleep_seconds,
                    deep_sleep_seconds, light_sleep_seconds, rem_sleep_seconds,
                    awake_seconds, sleep_score, sleep_quality,
                    avg_sleep_stress, avg_respiration, avg_spo2, avg_hrv,
                    raw_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(date) DO UPDATE SET
                    total_sleep_seconds = excluded.total_sleep_seconds,
                    sleep_score = excluded.sleep_score,
                    raw_json = excluded.raw_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    sleep.date,
                    sleep.sleep_start,
                    sleep.sleep_end,
                    sleep.total_sleep_seconds,
                    sleep.deep_sleep_seconds,
                    sleep.light_sleep_seconds,
                    sleep.rem_sleep_seconds,
                    sleep.awake_seconds,
                    sleep.sleep_score,
                    sleep.sleep_quality,
                    sleep.avg_sleep_stress,
                    sleep.avg_respiration,
                    sleep.avg_spo2,
                    sleep.avg_hrv,
                    sleep.raw_json,
                )
            )

    def get_sleep(self, date: str) -> Optional[SleepDaily]:
        """Get sleep data for a date."""
        cursor = self.db.connection.cursor()
        cursor.execute("SELECT * FROM sleep_daily WHERE date = ?", (date,))
        row = cursor.fetchone()
        if row is None:
            return None
        return SleepDaily(
            date=row["date"],
            sleep_start=row["sleep_start"],
            sleep_end=row["sleep_end"],
            total_sleep_seconds=row["total_sleep_seconds"],
            deep_sleep_seconds=row["deep_sleep_seconds"],
            light_sleep_seconds=row["light_sleep_seconds"],
            rem_sleep_seconds=row["rem_sleep_seconds"],
            awake_seconds=row["awake_seconds"],
            sleep_score=row["sleep_score"],
            sleep_quality=row["sleep_quality"],
            avg_sleep_stress=row["avg_sleep_stress"],
            avg_respiration=row["avg_respiration"],
            avg_spo2=row["avg_spo2"],
            avg_hrv=row["avg_hrv"],
            raw_json=row["raw_json"],
        )

    # ==================== Stress ====================

    def upsert_stress(self, stress: StressDaily) -> None:
        """Insert or update stress data."""
        with self.db.transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO stress_daily (
                    date, overall_stress_level, rest_stress_duration,
                    low_stress_duration, medium_stress_duration, high_stress_duration,
                    max_stress_level, avg_stress_level, raw_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(date) DO UPDATE SET
                    overall_stress_level = excluded.overall_stress_level,
                    avg_stress_level = excluded.avg_stress_level,
                    raw_json = excluded.raw_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    stress.date,
                    stress.overall_stress_level,
                    stress.rest_stress_duration,
                    stress.low_stress_duration,
                    stress.medium_stress_duration,
                    stress.high_stress_duration,
                    stress.max_stress_level,
                    stress.avg_stress_level,
                    stress.raw_json,
                )
            )

    # ==================== Heart Rate ====================

    def upsert_heart_rate(self, hr: HeartRateDaily) -> None:
        """Insert or update heart rate data."""
        with self.db.transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO heart_rate_daily (
                    date, resting_hr, max_hr, min_hr, raw_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(date) DO UPDATE SET
                    resting_hr = excluded.resting_hr,
                    max_hr = excluded.max_hr,
                    min_hr = excluded.min_hr,
                    raw_json = excluded.raw_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (hr.date, hr.resting_hr, hr.max_hr, hr.min_hr, hr.raw_json)
            )

    # ==================== HRV ====================

    def upsert_hrv(self, hrv: HRVDaily) -> None:
        """Insert or update HRV data."""
        with self.db.transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO hrv_daily (
                    date, hrv_value, hrv_status, baseline_low, baseline_high,
                    baseline_avg, weekly_avg, last_night_avg, raw_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(date) DO UPDATE SET
                    hrv_value = excluded.hrv_value,
                    hrv_status = excluded.hrv_status,
                    raw_json = excluded.raw_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    hrv.date,
                    hrv.hrv_value,
                    hrv.hrv_status,
                    hrv.baseline_low,
                    hrv.baseline_high,
                    hrv.baseline_avg,
                    hrv.weekly_avg,
                    hrv.last_night_avg,
                    hrv.raw_json,
                )
            )

    # ==================== Body Battery ====================

    def upsert_body_battery(self, bb: BodyBatteryDaily) -> None:
        """Insert or update body battery data."""
        with self.db.transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO body_battery_daily (
                    date, charged, drained, start_level, end_level,
                    min_level, max_level, raw_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(date) DO UPDATE SET
                    start_level = excluded.start_level,
                    end_level = excluded.end_level,
                    min_level = excluded.min_level,
                    max_level = excluded.max_level,
                    raw_json = excluded.raw_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    bb.date,
                    bb.charged,
                    bb.drained,
                    bb.start_level,
                    bb.end_level,
                    bb.min_level,
                    bb.max_level,
                    bb.raw_json,
                )
            )

    # ==================== Training Readiness ====================

    def upsert_training_readiness(self, tr: TrainingReadiness) -> None:
        """Insert or update training readiness data."""
        with self.db.transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO training_readiness (
                    date, score, level, sleep_score, recovery_score, hrv_score,
                    stress_history_score, training_load_balance_score,
                    feedback_phrase, raw_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(date) DO UPDATE SET
                    score = excluded.score,
                    level = excluded.level,
                    raw_json = excluded.raw_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    tr.date,
                    tr.score,
                    tr.level,
                    tr.sleep_score,
                    tr.recovery_score,
                    tr.hrv_score,
                    tr.stress_history_score,
                    tr.training_load_balance_score,
                    tr.feedback_phrase,
                    tr.raw_json,
                )
            )

    # ==================== Chat Messages ====================

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """Estimate token count for text (rough heuristic: chars / 4)."""
        return len(text) // 4

    def add_chat_message(
        self,
        role: str,
        content: str,
        message_type: str = "chat",
    ) -> ChatMessage:
        """Add a message to chat history.

        Args:
            role: 'user', 'assistant', or 'system'
            content: Message content
            message_type: 'chat' or 'analysis'

        Returns:
            The created ChatMessage with id and created_at populated
        """
        token_estimate = self.estimate_tokens(content)
        with self.db.transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO chat_messages (role, content, message_type, token_estimate)
                VALUES (?, ?, ?, ?)
                """,
                (role, content, message_type, token_estimate)
            )
            message_id = cursor.lastrowid

        # Fetch the created message to get created_at
        cursor = self.db.connection.cursor()
        cursor.execute(
            "SELECT * FROM chat_messages WHERE id = ?",
            (message_id,)
        )
        row = cursor.fetchone()
        return self._row_to_chat_message(row)

    def get_chat_history(self, limit: int = 100) -> list[ChatMessage]:
        """Get recent chat messages.

        Args:
            limit: Maximum number of messages to return

        Returns:
            List of ChatMessage ordered by created_at ascending (oldest first)
        """
        cursor = self.db.connection.cursor()
        cursor.execute(
            """
            SELECT * FROM chat_messages
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,)
        )
        rows = cursor.fetchall()
        # Return in chronological order (oldest first)
        return [self._row_to_chat_message(row) for row in reversed(rows)]

    def get_messages_since(self, timestamp: str) -> list[ChatMessage]:
        """Get chat messages since a given timestamp.

        Args:
            timestamp: ISO format timestamp string

        Returns:
            List of ChatMessage ordered by created_at ascending
        """
        cursor = self.db.connection.cursor()
        cursor.execute(
            """
            SELECT * FROM chat_messages
            WHERE created_at > ?
            ORDER BY created_at ASC
            """,
            (timestamp,)
        )
        return [self._row_to_chat_message(row) for row in cursor.fetchall()]

    def clear_chat_history(self) -> int:
        """Clear all chat messages.

        Returns:
            Number of messages deleted
        """
        cursor = self.db.connection.cursor()
        cursor.execute("SELECT COUNT(*) FROM chat_messages")
        count = cursor.fetchone()[0]

        with self.db.transaction() as cursor:
            cursor.execute("DELETE FROM chat_messages")

        return count

    def get_chat_token_total(self) -> int:
        """Get total estimated tokens in chat history."""
        cursor = self.db.connection.cursor()
        cursor.execute(
            "SELECT COALESCE(SUM(token_estimate), 0) FROM chat_messages"
        )
        return cursor.fetchone()[0]

    def _row_to_chat_message(self, row) -> ChatMessage:
        """Convert database row to ChatMessage model."""
        return ChatMessage(
            id=row["id"],
            role=row["role"],
            content=row["content"],
            message_type=row["message_type"],
            token_estimate=row["token_estimate"],
            created_at=row["created_at"],
        )

    # ==================== HEVY Workouts ====================

    def get_hevy_workout_ids(self, since_date: Optional[str] = None) -> set[str]:
        """Get set of HEVY workout IDs for deduplication.

        Args:
            since_date: Optional date filter (ISO format)

        Returns:
            Set of workout IDs
        """
        cursor = self.db.connection.cursor()
        if since_date:
            cursor.execute(
                "SELECT id FROM hevy_workouts WHERE start_time >= ?",
                (since_date,)
            )
        else:
            cursor.execute("SELECT id FROM hevy_workouts")
        return {row[0] for row in cursor.fetchall()}

    def upsert_hevy_workout(self, workout: HevyWorkout) -> None:
        """Insert or update a HEVY workout with all exercises and sets.

        Args:
            workout: HevyWorkout model with exercises and sets
        """
        with self.db.transaction() as cursor:
            # Insert/update workout
            cursor.execute(
                """
                INSERT INTO hevy_workouts (
                    id, title, description, start_time, end_time,
                    duration_seconds, volume_kg, set_count, rep_count,
                    exercise_count, raw_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(id) DO UPDATE SET
                    title = excluded.title,
                    description = excluded.description,
                    volume_kg = excluded.volume_kg,
                    set_count = excluded.set_count,
                    rep_count = excluded.rep_count,
                    raw_json = excluded.raw_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    workout.id,
                    workout.title,
                    workout.description,
                    workout.start_time,
                    workout.end_time,
                    workout.duration_seconds,
                    workout.total_volume_kg,
                    workout.total_sets,
                    workout.total_reps,
                    workout.exercise_count,
                    workout.raw_json,
                )
            )

            # Delete existing exercises and sets (for upsert)
            cursor.execute(
                """
                DELETE FROM hevy_sets WHERE exercise_id IN (
                    SELECT id FROM hevy_exercises WHERE workout_id = ?
                )
                """,
                (workout.id,)
            )
            cursor.execute(
                "DELETE FROM hevy_exercises WHERE workout_id = ?",
                (workout.id,)
            )

            # Insert exercises and sets
            for exercise in workout.exercises:
                # Look up muscle group from template if not set
                muscle_group = exercise.muscle_group
                if not muscle_group and exercise.exercise_template_id:
                    cursor.execute(
                        "SELECT muscle_group FROM hevy_exercise_templates WHERE id = ?",
                        (exercise.exercise_template_id,)
                    )
                    row = cursor.fetchone()
                    if row:
                        muscle_group = row[0]

                cursor.execute(
                    """
                    INSERT INTO hevy_exercises (
                        workout_id, exercise_template_id, exercise_name,
                        exercise_type, muscle_group, superset_id,
                        exercise_order, notes
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        workout.id,
                        exercise.exercise_template_id,
                        exercise.exercise_name,
                        exercise.exercise_type,
                        muscle_group,
                        exercise.superset_id,
                        exercise.exercise_order,
                        exercise.notes,
                    )
                )
                exercise_id = cursor.lastrowid

                for set_data in exercise.sets:
                    cursor.execute(
                        """
                        INSERT INTO hevy_sets (
                            exercise_id, set_index, set_type, weight_kg,
                            reps, distance_meters, duration_seconds, rpe, is_pr
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            exercise_id,
                            set_data.set_index,
                            set_data.set_type,
                            set_data.weight_kg,
                            set_data.reps,
                            set_data.distance_meters,
                            set_data.duration_seconds,
                            set_data.rpe,
                            1 if set_data.is_pr else 0,
                        )
                    )

    def get_hevy_workouts(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict]:
        """Get HEVY workouts with optional date filtering.

        Args:
            start_date: Start date filter (ISO format)
            end_date: End date filter (ISO format)
            limit: Maximum number of workouts to return

        Returns:
            List of workout dicts with summary info
        """
        query = "SELECT * FROM hevy_workouts WHERE 1=1"
        params: list = []

        if start_date:
            query += " AND start_time >= ?"
            params.append(start_date)
        if end_date:
            query += " AND start_time <= ?"
            params.append(end_date)

        query += " ORDER BY start_time DESC LIMIT ?"
        params.append(limit)

        cursor = self.db.connection.cursor()
        cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]

    def get_hevy_volume_by_muscle_group(
        self,
        days: int = 7,
    ) -> dict[str, dict]:
        """Get training volume breakdown by muscle group.

        Args:
            days: Number of days to aggregate

        Returns:
            Dict with muscle group as key, containing volume_kg, sets, reps
        """
        from datetime import date, timedelta
        start_date = (date.today() - timedelta(days=days)).isoformat()

        cursor = self.db.connection.cursor()
        cursor.execute(
            """
            SELECT
                e.muscle_group,
                COALESCE(SUM(s.weight_kg * s.reps), 0) as volume_kg,
                COUNT(CASE WHEN s.set_type != 'warmup' THEN 1 END) as sets,
                COALESCE(SUM(s.reps), 0) as reps
            FROM hevy_exercises e
            JOIN hevy_workouts w ON e.workout_id = w.id
            JOIN hevy_sets s ON s.exercise_id = e.id
            WHERE w.start_time >= ?
            GROUP BY e.muscle_group
            ORDER BY volume_kg DESC
            """,
            (start_date,)
        )

        result = {}
        for row in cursor.fetchall():
            group = row["muscle_group"] or "other"
            result[group] = {
                "volume_kg": row["volume_kg"] or 0,
                "sets": row["sets"] or 0,
                "reps": row["reps"] or 0,
            }

        return result

    def get_hevy_exercise_progression(
        self,
        exercise_name: str,
        days: int = 90,
    ) -> dict:
        """Track progression for a specific exercise over time.

        Args:
            exercise_name: Name of the exercise to track
            days: Number of days to analyze

        Returns:
            Dict with progression data including max weights and estimated 1RM
        """
        from datetime import date, timedelta
        start_date = (date.today() - timedelta(days=days)).isoformat()

        cursor = self.db.connection.cursor()
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
            return {
                "exercise": exercise_name,
                "sessions": [],
                "current_1rm": None,
                "progression_pct": None,
            }

        current_1rm = sessions[0]["est_1rm"] if sessions else None

        # Calculate progression if we have enough data
        progression_pct = None
        if len(sessions) >= 2:
            older_sessions = sessions[len(sessions)//2:]
            if older_sessions:
                older_1rms = [s["est_1rm"] for s in older_sessions if s["est_1rm"]]
                if older_1rms and current_1rm:
                    older_avg = sum(older_1rms) / len(older_1rms)
                    if older_avg > 0:
                        progression_pct = round(((current_1rm - older_avg) / older_avg) * 100, 1)

        return {
            "exercise": exercise_name,
            "sessions": sessions[:10],  # Last 10 sessions
            "current_1rm": current_1rm,
            "progression_pct": progression_pct,
        }

    def get_hevy_workout_count(self, days: int = 7) -> int:
        """Count HEVY workouts in the last N days.

        Args:
            days: Number of days to count

        Returns:
            Number of workouts
        """
        from datetime import date, timedelta
        start_date = (date.today() - timedelta(days=days)).isoformat()

        cursor = self.db.connection.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM hevy_workouts WHERE start_time >= ?",
            (start_date,)
        )
        return cursor.fetchone()[0]

    def upsert_hevy_exercise_template(self, template: HevyExerciseTemplate) -> None:
        """Insert or update an exercise template.

        Args:
            template: HevyExerciseTemplate model
        """
        with self.db.transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO hevy_exercise_templates (
                    id, title, muscle_group, equipment, is_custom
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title = excluded.title,
                    muscle_group = excluded.muscle_group,
                    equipment = excluded.equipment,
                    is_custom = excluded.is_custom
                """,
                (
                    template.id,
                    template.title,
                    template.muscle_group,
                    template.equipment,
                    1 if template.is_custom else 0,
                )
            )

    def get_hevy_workout_details(self, days: int = 7) -> list[dict]:
        """Get detailed HEVY workout data including exercises and sets.

        Args:
            days: Number of days to look back

        Returns:
            List of workout dicts with exercise details:
            [{
                "date": "2026-01-31",
                "title": "Afternoon workout",
                "duration_minutes": 59,
                "total_volume_lbs": 23950,
                "exercises": [{
                    "name": "Bench Press",
                    "muscle_group": "chest",
                    "sets": "135×10, 145×8, 155×6"
                }, ...]
            }]
        """
        from datetime import date, timedelta
        start_date = (date.today() - timedelta(days=days)).isoformat()

        cursor = self.db.connection.cursor()

        # Check if HEVY tables exist
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='hevy_workouts'"
        )
        if not cursor.fetchone():
            return []

        # Get workouts
        cursor.execute(
            """
            SELECT id, title, start_time, duration_seconds, volume_kg
            FROM hevy_workouts
            WHERE start_time >= ?
            ORDER BY start_time DESC
            """,
            (start_date,)
        )
        workouts = []
        kg_to_lbs = 2.20462

        def utc_to_local(utc_str: str) -> tuple[str, str]:
            """Convert UTC timestamp to local date and time.

            Args:
                utc_str: UTC timestamp like '2026-02-11T20:26:51+00:00'

            Returns:
                Tuple of (date_str, time_str) in local time
            """
            from datetime import datetime, timezone
            try:
                # Parse ISO format with timezone
                if '+' in utc_str or utc_str.endswith('Z'):
                    utc_str = utc_str.replace('Z', '+00:00')
                    dt = datetime.fromisoformat(utc_str)
                else:
                    # Assume UTC if no timezone
                    dt = datetime.fromisoformat(utc_str).replace(tzinfo=timezone.utc)
                # Convert to local time
                local_dt = dt.astimezone()
                return local_dt.strftime("%Y-%m-%d"), local_dt.strftime("%H:%M")
            except (ValueError, TypeError):
                return utc_str[:10] if utc_str else None, None

        for workout_row in cursor.fetchall():
            workout_id = workout_row["id"]
            raw_time = workout_row["start_time"]
            workout_date, workout_time = utc_to_local(raw_time) if raw_time else (None, None)
            duration_seconds = workout_row["duration_seconds"] or 0
            volume_kg = workout_row["volume_kg"] or 0

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

                # Get sets for this exercise (non-warmup only for compact display)
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
                        continue  # Skip warmup sets
                    weight_lbs = round((s["weight_kg"] or 0) * kg_to_lbs)
                    reps = s["reps"] or 0
                    if weight_lbs > 0 and reps > 0:
                        set_strings.append(f"{weight_lbs}×{reps}")
                    elif reps > 0:
                        # Bodyweight exercise
                        set_strings.append(f"BW×{reps}")

                if set_strings:
                    exercises.append({
                        "name": exercise_row["exercise_name"],
                        "muscle_group": exercise_row["muscle_group"] or "other",
                        "sets": ", ".join(set_strings),
                    })

            workouts.append({
                "date": workout_date,
                "time": workout_time,
                "title": workout_row["title"] or "Workout",
                "duration_minutes": round(duration_seconds / 60) if duration_seconds else None,
                "total_volume_lbs": round(volume_kg * kg_to_lbs),
                "exercises": exercises,
            })

        return workouts

    # ------------------------------------------------------------------
    # Personal Records
    # ------------------------------------------------------------------

    def upsert_personal_record(
        self,
        category: str,
        metric_name: str,
        value: float,
        date_set: str,
        activity_id: str | None = None,
        workout_id: str | None = None,
        exercise_name: str | None = None,
    ) -> dict | None:
        """Insert or update a personal record if the new value beats the old one.

        Args:
            category: 'cardio' or 'strength'
            metric_name: e.g. 'fastest_5k', 'heaviest_bench_press'
            value: The record value (lower is better for time-based, higher for load)
            date_set: ISO date string
            activity_id: FK to activities table (cardio PRs)
            workout_id: FK to hevy_workouts (strength PRs)
            exercise_name: For strength PRs

        Returns:
            Dict with PR details if new record was set, None otherwise.
        """
        cursor = self.db.connection.cursor()

        # Check for existing record
        cursor.execute(
            """
            SELECT value FROM personal_records
            WHERE category = ? AND metric_name = ?
                AND COALESCE(exercise_name, '') = COALESCE(?, '')
            """,
            (category, metric_name, exercise_name),
        )
        existing = cursor.fetchone()

        # Determine if this beats the existing record
        # For time-based metrics (fastest_*), lower is better
        # For everything else (longest_*, highest_*, heaviest_*), higher is better
        is_time_metric = metric_name.startswith("fastest_")
        if existing:
            old_val = existing["value"]
            if is_time_metric:
                is_new_pr = value < old_val
            else:
                is_new_pr = value > old_val
            if not is_new_pr:
                return None
        else:
            old_val = None

        cursor.execute(
            """
            INSERT INTO personal_records
                (category, metric_name, value, previous_value,
                 activity_id, workout_id, exercise_name, date_set)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(category, metric_name, exercise_name)
            DO UPDATE SET
                previous_value = personal_records.value,
                value = excluded.value,
                activity_id = excluded.activity_id,
                workout_id = excluded.workout_id,
                date_set = excluded.date_set,
                created_at = CURRENT_TIMESTAMP
            """,
            (category, metric_name, value, old_val,
             activity_id, workout_id, exercise_name, date_set),
        )
        self.db.connection.commit()

        return {
            "category": category,
            "metric_name": metric_name,
            "value": value,
            "previous_value": old_val,
            "exercise_name": exercise_name,
            "date_set": date_set,
        }

    def get_personal_records(self, category: str | None = None) -> list[dict]:
        """Get all personal records, optionally filtered by category.

        Args:
            category: 'cardio', 'strength', or None for all

        Returns:
            List of PR dicts.
        """
        cursor = self.db.connection.cursor()

        # Check table exists (might be pre-migration)
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='personal_records'"
        )
        if not cursor.fetchone():
            return []

        if category:
            cursor.execute(
                "SELECT * FROM personal_records WHERE category = ? ORDER BY date_set DESC",
                (category,),
            )
        else:
            cursor.execute(
                "SELECT * FROM personal_records ORDER BY date_set DESC"
            )

        return [dict(row) for row in cursor.fetchall()]

    def get_recent_prs(self, days: int = 7) -> list[dict]:
        """Get personal records set in the last N days.

        Args:
            days: Number of days to look back

        Returns:
            List of recent PR dicts.
        """
        cursor = self.db.connection.cursor()

        # Check table exists
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='personal_records'"
        )
        if not cursor.fetchone():
            return []

        start = (date.today() - timedelta(days=days)).isoformat()
        cursor.execute(
            """
            SELECT * FROM personal_records
            WHERE date_set >= ?
            ORDER BY date_set DESC
            """,
            (start,),
        )
        return [dict(row) for row in cursor.fetchall()]
