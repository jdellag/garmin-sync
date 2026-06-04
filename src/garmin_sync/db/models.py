"""Data models for Garmin data."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


def _epoch_ms_to_iso(val) -> Optional[str]:
    """Convert epoch milliseconds to an ISO 8601 UTC string, or None.

    Garmin usually returns these timestamps as epoch milliseconds, but some
    payloads/fields are already ISO strings — pass those through unchanged
    rather than discarding them (``int("2024-…")`` would raise and lose data).
    """
    if val is None:
        return None
    if isinstance(val, str):
        # Already an ISO-ish timestamp (or empty) — return as-is, not None.
        return val or None
    try:
        return datetime.fromtimestamp(int(val) / 1000, tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
    except (ValueError, TypeError, OSError, OverflowError):
        return None


@dataclass
class Activity:
    """Represents a Garmin activity (run, ride, swim, etc.)."""

    activity_id: str
    activity_name: Optional[str] = None
    activity_type: Optional[str] = None
    start_time: Optional[str] = None
    start_time_local: Optional[str] = None
    timezone: Optional[str] = None
    duration_seconds: Optional[float] = None
    moving_duration_seconds: Optional[float] = None
    distance_meters: Optional[float] = None
    average_speed_mps: Optional[float] = None
    max_speed_mps: Optional[float] = None
    average_hr: Optional[int] = None
    max_hr: Optional[int] = None
    min_hr: Optional[int] = None
    elevation_gain_meters: Optional[float] = None
    elevation_loss_meters: Optional[float] = None
    calories: Optional[int] = None
    training_effect_aerobic: Optional[float] = None
    training_effect_anaerobic: Optional[float] = None
    training_load: Optional[float] = None
    vo2_max: Optional[float] = None
    avg_cadence: Optional[float] = None
    max_cadence: Optional[float] = None
    average_power: Optional[float] = None
    max_power: Optional[float] = None
    normalized_power: Optional[float] = None
    device_name: Optional[str] = None
    has_fit_file: bool = False
    fit_file_path: Optional[str] = None
    hr_drift: Optional[float] = None  # (HR_half2 - HR_half1) / HR_half1
    raw_json: Optional[str] = None
    fit_parsed: bool = False

    @classmethod
    def from_api_response(cls, data: dict) -> "Activity":
        """Create Activity from Garmin API response."""
        return cls(
            activity_id=str(data.get("activityId", "")),
            activity_name=data.get("activityName"),
            activity_type=(data.get("activityType") or {}).get("typeKey"),
            start_time=data.get("startTimeGMT"),
            start_time_local=data.get("startTimeLocal"),
            timezone=data.get("timeZoneId"),
            duration_seconds=data.get("duration"),
            moving_duration_seconds=data.get("movingDuration"),
            distance_meters=data.get("distance"),
            average_speed_mps=data.get("averageSpeed"),
            max_speed_mps=data.get("maxSpeed"),
            average_hr=data.get("averageHR"),
            max_hr=data.get("maxHR"),
            min_hr=data.get("minHR"),
            elevation_gain_meters=data.get("elevationGain"),
            elevation_loss_meters=data.get("elevationLoss"),
            calories=data.get("calories"),
            training_effect_aerobic=data.get("aerobicTrainingEffect"),
            training_effect_anaerobic=data.get("anaerobicTrainingEffect"),
            training_load=data.get("activityTrainingLoad"),
            vo2_max=data.get("vO2MaxValue"),
            avg_cadence=data.get("averageRunningCadenceInStepsPerMinute"),
            max_cadence=data.get("maxRunningCadenceInStepsPerMinute"),
            average_power=data.get("avgPower"),
            max_power=data.get("maxPower"),
            normalized_power=data.get("normPower"),
            device_name=data.get("deviceId"),
        )


@dataclass
class DailySummary:
    """Daily summary data (steps, calories, etc.)."""

    date: str
    total_steps: Optional[int] = None
    step_goal: Optional[int] = None
    steps_distance_meters: Optional[float] = None
    total_calories: Optional[int] = None
    active_calories: Optional[int] = None
    bmr_calories: Optional[int] = None
    highly_active_seconds: Optional[int] = None
    active_seconds: Optional[int] = None
    sedentary_seconds: Optional[int] = None
    floors_ascended: Optional[int] = None
    floors_descended: Optional[int] = None
    raw_json: Optional[str] = None

    @classmethod
    def from_api_response(cls, data: dict) -> "DailySummary":
        """Create DailySummary from Garmin API response."""
        return cls(
            date=data.get("calendarDate", ""),
            total_steps=data.get("totalSteps"),
            step_goal=data.get("dailyStepGoal"),
            steps_distance_meters=data.get("totalDistanceMeters"),
            total_calories=data.get("totalKilocalories"),
            active_calories=data.get("activeKilocalories"),
            bmr_calories=data.get("bmrKilocalories"),
            highly_active_seconds=data.get("highlyActiveSeconds"),
            active_seconds=data.get("activeSeconds"),
            sedentary_seconds=data.get("sedentarySeconds"),
            floors_ascended=data.get("floorsAscended"),
            floors_descended=data.get("floorsDescended"),
        )


@dataclass
class HeartRateDaily:
    """Daily heart rate data."""

    date: str
    resting_hr: Optional[int] = None
    max_hr: Optional[int] = None
    min_hr: Optional[int] = None
    raw_json: Optional[str] = None

    @classmethod
    def from_api_response(cls, data: dict) -> "HeartRateDaily":
        """Create HeartRateDaily from Garmin API response."""
        return cls(
            date=data.get("calendarDate", ""),
            resting_hr=data.get("restingHeartRate"),
            max_hr=data.get("maxHeartRate"),
            min_hr=data.get("minHeartRate"),
        )


@dataclass
class SleepDaily:
    """Daily sleep data."""

    date: str
    sleep_start: Optional[str] = None
    sleep_end: Optional[str] = None
    total_sleep_seconds: Optional[int] = None
    deep_sleep_seconds: Optional[int] = None
    light_sleep_seconds: Optional[int] = None
    rem_sleep_seconds: Optional[int] = None
    awake_seconds: Optional[int] = None
    sleep_score: Optional[int] = None
    sleep_quality: Optional[str] = None
    avg_sleep_stress: Optional[float] = None
    avg_respiration: Optional[float] = None
    avg_spo2: Optional[float] = None
    avg_hrv: Optional[float] = None
    raw_json: Optional[str] = None

    @classmethod
    def from_api_response(cls, data: dict) -> "SleepDaily":
        """Create SleepDaily from Garmin API response."""
        # Garmin may return null for dailySleepDTO or sleepScores on
        # partial-data nights (watch removed, etc.), so coerce to {}.
        daily_sleep = data.get("dailySleepDTO") or {}
        sleep_scores = (data.get("sleepScores") or {})
        overall = sleep_scores.get("overall") or {}
        return cls(
            date=daily_sleep.get("calendarDate", ""),
            sleep_start=_epoch_ms_to_iso(daily_sleep.get("sleepStartTimestampGMT")),
            sleep_end=_epoch_ms_to_iso(daily_sleep.get("sleepEndTimestampGMT")),
            total_sleep_seconds=daily_sleep.get("sleepTimeSeconds"),
            deep_sleep_seconds=daily_sleep.get("deepSleepSeconds"),
            light_sleep_seconds=daily_sleep.get("lightSleepSeconds"),
            rem_sleep_seconds=daily_sleep.get("remSleepSeconds"),
            awake_seconds=daily_sleep.get("awakeSleepSeconds"),
            sleep_score=overall.get("value"),
            sleep_quality=overall.get("qualifierKey"),
            avg_sleep_stress=daily_sleep.get("avgSleepStress"),
            avg_respiration=daily_sleep.get("avgRespirationRate"),
            avg_spo2=daily_sleep.get("avgOxygenSaturationPercentage"),
            avg_hrv=daily_sleep.get("avgSleepingHrv"),
        )

    @classmethod
    def from_batch_response(cls, data: dict) -> "SleepDaily":
        """Create SleepDaily from Garmin API batch response."""
        return cls(
            date=data.get("calendarDate", ""),
            sleep_score=data.get("sleepScore"),
        )


@dataclass
class StressDaily:
    """Daily stress data."""

    date: str
    overall_stress_level: Optional[int] = None
    rest_stress_duration: Optional[int] = None
    low_stress_duration: Optional[int] = None
    medium_stress_duration: Optional[int] = None
    high_stress_duration: Optional[int] = None
    max_stress_level: Optional[int] = None
    avg_stress_level: Optional[int] = None
    raw_json: Optional[str] = None

    @classmethod
    def from_api_response(cls, data: dict) -> "StressDaily":
        """Create StressDaily from Garmin API response."""
        return cls(
            date=data.get("calendarDate", ""),
            overall_stress_level=data.get("overallStressLevel"),
            rest_stress_duration=data.get("restStressDuration"),
            low_stress_duration=data.get("lowStressDuration"),
            medium_stress_duration=data.get("mediumStressDuration"),
            high_stress_duration=data.get("highStressDuration"),
            max_stress_level=data.get("maxStressLevel"),
            avg_stress_level=data.get("avgStressLevel"),
        )

    @classmethod
    def from_batch_response(cls, data: dict) -> "StressDaily":
        """Create StressDaily from Garmin API batch response."""
        return cls(
            date=data.get("calendarDate", ""),
            avg_stress_level=data.get("avgStress"),
        )


@dataclass
class HRVDaily:
    """Daily HRV (heart rate variability) data."""

    date: str
    hrv_value: Optional[float] = None
    hrv_status: Optional[str] = None
    baseline_low: Optional[float] = None
    baseline_high: Optional[float] = None
    baseline_avg: Optional[float] = None
    weekly_avg: Optional[float] = None
    last_night_avg: Optional[float] = None
    raw_json: Optional[str] = None

    @classmethod
    def from_api_response(cls, data: dict) -> "HRVDaily":
        """Create HRVDaily from Garmin API response."""
        # Garmin returns {"hrvSummary": null, ...} for early dates, so the
        # default-arg form of .get() doesn't help — coerce None to {}.
        summary = data.get("hrvSummary") or {}
        baseline = summary.get("baseline") or {}
        return cls(
            date=summary.get("calendarDate", ""),
            hrv_value=summary.get("weeklyAvg"),
            hrv_status=summary.get("status"),
            baseline_low=baseline.get("lowUpper"),
            baseline_high=baseline.get("balancedLow"),
            baseline_avg=baseline.get("balancedUpper"),
            weekly_avg=summary.get("weeklyAvg"),
            last_night_avg=summary.get("lastNightAvg"),
        )

    @classmethod
    def from_batch_response(cls, data: dict) -> "HRVDaily":
        """Create HRVDaily from Garmin API batch response."""
        return cls(
            date=data.get("calendarDate", ""),
            hrv_value=data.get("hrvValue"),
        )


@dataclass
class BodyBatteryDaily:
    """Daily Body Battery data."""

    date: str
    charged: Optional[int] = None
    drained: Optional[int] = None
    start_level: Optional[int] = None
    end_level: Optional[int] = None
    min_level: Optional[int] = None
    max_level: Optional[int] = None
    raw_json: Optional[str] = None

    @classmethod
    def from_api_response(cls, date: str, data: list) -> "BodyBatteryDaily":
        """Create BodyBatteryDaily from raw values array.

        Args:
            date: The date string
            data: List of [timestamp, level] arrays
        """
        # Body battery comes as a list of [timestamp, level]
        if not data:
            return cls(date=date)

        levels = [item[1] for item in data if len(item) >= 2 and item[1] is not None]
        return cls(
            date=date,
            start_level=levels[0] if levels else None,
            end_level=levels[-1] if levels else None,
            min_level=min(levels) if levels else None,
            max_level=max(levels) if levels else None,
        )

    @classmethod
    def from_daily_response(cls, data: dict) -> "BodyBatteryDaily":
        """Create BodyBatteryDaily from daily summary dict.

        Args:
            data: Daily body battery dict with 'date', 'charged', 'drained',
                  'bodyBatteryValuesArray' fields
        """
        date_str = data.get("date", "")
        charged = data.get("charged")
        drained = data.get("drained")

        # Extract levels from bodyBatteryValuesArray
        values_array = data.get("bodyBatteryValuesArray", [])
        levels = [item[1] for item in values_array if len(item) >= 2 and item[1] is not None]

        return cls(
            date=date_str,
            charged=charged,
            drained=drained,
            start_level=levels[0] if levels else None,
            end_level=levels[-1] if levels else None,
            min_level=min(levels) if levels else None,
            max_level=max(levels) if levels else None,
        )


@dataclass
class TrainingReadiness:
    """Training readiness data."""

    date: str
    score: Optional[int] = None
    level: Optional[str] = None
    sleep_score: Optional[int] = None
    recovery_score: Optional[int] = None
    hrv_score: Optional[int] = None
    stress_history_score: Optional[int] = None
    training_load_balance_score: Optional[int] = None
    feedback_phrase: Optional[str] = None
    raw_json: Optional[str] = None

    @classmethod
    def from_api_response(cls, data: dict) -> "TrainingReadiness":
        """Create TrainingReadiness from Garmin API response."""
        return cls(
            date=data.get("calendarDate", ""),
            score=data.get("score"),
            level=data.get("level"),
            sleep_score=data.get("sleepScore"),
            recovery_score=data.get("recoveryScore"),
            hrv_score=data.get("hrvScore"),
            stress_history_score=data.get("stressHistoryScore"),
            training_load_balance_score=data.get("trainingLoadBalanceScore"),
            feedback_phrase=data.get("feedbackPhrase"),
        )


@dataclass
class SyncMetadata:
    """Tracks sync state for each data type."""

    data_type: str
    last_sync_timestamp: str
    last_sync_date: Optional[str] = None
    sync_status: str = "success"
    records_synced: int = 0
    error_message: Optional[str] = None


@dataclass
class ChatMessage:
    """A message in the AI chat conversation."""

    id: Optional[int] = None
    role: str = "user"  # 'user', 'assistant', 'system'
    content: str = ""
    message_type: str = "chat"  # 'chat' or 'analysis'
    token_estimate: Optional[int] = None
    created_at: Optional[str] = None


@dataclass
class ActivityLap:
    """Represents a single lap from FIT file parsing."""

    activity_id: str
    lap_index: int
    start_time: Optional[str] = None
    total_elapsed_time: Optional[float] = None
    total_distance: Optional[float] = None
    avg_speed: Optional[float] = None
    max_speed: Optional[float] = None
    avg_heart_rate: Optional[int] = None
    max_heart_rate: Optional[int] = None
    avg_cadence: Optional[float] = None
    avg_power: Optional[float] = None
    total_ascent: Optional[float] = None
    total_descent: Optional[float] = None
    avg_temperature: Optional[float] = None


@dataclass
class ActivitySplit:
    """Represents a pre-computed pace split (per-km)."""

    activity_id: str
    split_index: int
    split_unit: str = "km"
    distance: float = 0.0
    elapsed_time: float = 0.0
    pace_seconds_per_km: Optional[float] = None
    avg_heart_rate: Optional[int] = None
    avg_cadence: Optional[float] = None
    avg_power: Optional[float] = None
    elevation_change: Optional[float] = None


@dataclass
class RespirationDaily:
    """Daily all-day respiration data."""

    date: str
    avg_respiration: Optional[float] = None
    max_respiration: Optional[float] = None
    min_respiration: Optional[float] = None
    raw_json: Optional[str] = None

    @classmethod
    def from_api_response(cls, date_str: str, data: dict) -> "RespirationDaily":
        """Create from Garmin API response."""
        return cls(
            date=date_str,
            avg_respiration=data.get("avgWakingRespirationValue"),
            max_respiration=data.get("highestRespirationValue"),
            min_respiration=data.get("lowestRespirationValue"),
        )


@dataclass
class SpO2Daily:
    """Daily all-day SpO2 data."""

    date: str
    avg_spo2: Optional[float] = None
    min_spo2: Optional[float] = None
    max_spo2: Optional[float] = None
    raw_json: Optional[str] = None

    @classmethod
    def from_api_response(cls, date_str: str, data: dict) -> "SpO2Daily":
        """Create from Garmin API response."""
        return cls(
            date=date_str,
            avg_spo2=data.get("averageSpo2"),
            min_spo2=data.get("lowestSpo2"),
            max_spo2=data.get("latestSpo2"),
        )
