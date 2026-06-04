"""Garmin Connect API client wrapper."""

import logging
from datetime import date, datetime, timedelta
from typing import Any, Optional

from garminconnect import Garmin

from garmin_sync.api.rate_limiter import RateLimiter, retry_with_backoff
from garmin_sync.auth.garmin_auth import GarminAuthManager, get_auth_manager
from garmin_sync.config import get_settings

logger = logging.getLogger(__name__)


class GarminAPIError(Exception):
    """Error from Garmin API."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class GarminClient:
    """Rate-limited wrapper around Garmin Connect API.

    Provides methods to fetch activities and health metrics
    with automatic rate limiting and retry logic.
    """

    def __init__(
        self,
        auth_manager: Optional[GarminAuthManager] = None,
        rate_limiter: Optional[RateLimiter] = None,
    ):
        """Initialize Garmin client.

        Args:
            auth_manager: Authentication manager (uses default if None)
            rate_limiter: Rate limiter (creates default if None)
        """
        settings = get_settings()
        self._auth = auth_manager or get_auth_manager(settings.token_dir)
        self._rate_limiter = rate_limiter or RateLimiter(
            calls_per_minute=settings.rate_limit_calls_per_minute,
        )

    @property
    def _client(self) -> Garmin:
        """Get authenticated Garmin client."""
        return self._auth.ensure_authenticated()

    def _api_call(self, method_name: str, *args, **kwargs) -> Any:
        """Make a rate-limited API call with retry logic.

        Args:
            method_name: Name of method on Garmin client to call
            *args, **kwargs: Arguments to pass to the method

        Returns:
            Response from API call
        """
        @retry_with_backoff(
            max_retries=3,
            base_delay=1.0,
            exceptions=(Exception,),
        )
        def call():
            # Acquire a token per attempt so retries are throttled too —
            # otherwise a retry storm (e.g. against a 429) bypasses the limiter.
            self._rate_limiter.acquire()
            method = getattr(self._client, method_name)
            return method(*args, **kwargs)

        try:
            return call()
        except Exception as e:
            raise GarminAPIError(f"API call {method_name} failed: {e}") from e

    # ==================== Activities ====================

    def get_activities(
        self,
        start: int = 0,
        limit: int = 20,
    ) -> list[dict]:
        """Get list of activities.

        Args:
            start: Start index for pagination
            limit: Number of activities to fetch

        Returns:
            List of activity dictionaries
        """
        return self._api_call("get_activities", start, limit) or []

    def get_activities_by_date(
        self,
        start_date: date,
        end_date: date,
    ) -> list[dict]:
        """Get activities within a date range.

        Args:
            start_date: Start date (inclusive)
            end_date: End date (inclusive)

        Returns:
            List of activity dictionaries
        """
        start_str = start_date.isoformat()
        end_str = end_date.isoformat()
        return self._api_call("get_activities_by_date", start_str, end_str) or []

    def get_activity(self, activity_id: str) -> dict:
        """Get detailed activity data.

        Args:
            activity_id: Garmin activity ID

        Returns:
            Activity details dictionary
        """
        return self._api_call("get_activity", activity_id)

    def download_activity_fit(self, activity_id: str) -> bytes:
        """Download FIT file for an activity.

        garminconnect's `download_activity(..., ORIGINAL)` returns a zip
        archive containing the .fit file; we extract and return the raw FIT
        bytes so callers can hand them straight to fitdecode.
        """
        import io
        import zipfile

        zip_bytes = self._api_call(
            "download_activity",
            activity_id,
            Garmin.ActivityDownloadFormat.ORIGINAL,
        )
        if not zip_bytes:
            raise GarminAPIError(f"Empty download for activity {activity_id}")

        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            fit_names = [n for n in zf.namelist() if n.lower().endswith(".fit")]
            if not fit_names:
                raise GarminAPIError(
                    f"No .fit member in download for activity {activity_id}; "
                    f"got {zf.namelist()}"
                )
            return zf.read(fit_names[0])

    # ==================== Daily Summary ====================

    def get_stats(self, day: date) -> dict:
        """Get daily stats (steps, calories, etc.).

        Args:
            day: Date to get stats for

        Returns:
            Daily stats dictionary
        """
        return self._api_call("get_stats", day.isoformat()) or {}

    def get_user_summary(self, day: date) -> dict:
        """Get user daily summary.

        Args:
            day: Date to get summary for

        Returns:
            User summary dictionary
        """
        return self._api_call("get_user_summary", day.isoformat()) or {}

    # ==================== Sleep ====================

    def get_sleep_data(self, day: date) -> dict:
        """Get sleep data for a specific date.

        Args:
            day: Date to get sleep data for

        Returns:
            Sleep data dictionary
        """
        return self._api_call("get_sleep_data", day.isoformat()) or {}

    # ==================== Heart Rate ====================

    def get_heart_rates(self, day: date) -> dict:
        """Get heart rate data for a specific date.

        Args:
            day: Date to get heart rate data for

        Returns:
            Heart rate data dictionary
        """
        return self._api_call("get_heart_rates", day.isoformat()) or {}

    def get_resting_heart_rate(self, day: date) -> Optional[int]:
        """Get resting heart rate for a date.

        Args:
            day: Date to get resting HR for

        Returns:
            Resting heart rate or None
        """
        hr_data = self.get_heart_rates(day)
        return hr_data.get("restingHeartRate")

    # ==================== Stress ====================

    def get_stress_data(self, day: date) -> dict:
        """Get stress data for a specific date.

        Args:
            day: Date to get stress data for

        Returns:
            Stress data dictionary
        """
        return self._api_call("get_stress_data", day.isoformat()) or {}

    # ==================== HRV ====================

    def get_hrv_data(self, day: date) -> dict:
        """Get HRV (heart rate variability) data.

        Args:
            day: Date to get HRV data for

        Returns:
            HRV data dictionary
        """
        return self._api_call("get_hrv_data", day.isoformat()) or {}

    # ==================== Body Battery ====================

    def get_body_battery(self, day: date) -> list:
        """Get Body Battery data for a specific date.

        Args:
            day: Date to get Body Battery data for

        Returns:
            List of Body Battery readings
        """
        start_str = day.isoformat()
        end_str = (day + timedelta(days=1)).isoformat()
        result = self._api_call("get_body_battery", start_str, end_str)
        return result if isinstance(result, list) else []

    # ==================== Training ====================

    def get_training_readiness(self, day: date) -> dict:
        """Get training readiness data.

        Args:
            day: Date to get training readiness for

        Returns:
            Training readiness dictionary
        """
        return self._api_call("get_training_readiness", day.isoformat()) or {}

    def get_training_status(self, day: date) -> dict:
        """Get training status data.

        Args:
            day: Date to get training status for

        Returns:
            Training status dictionary
        """
        return self._api_call("get_training_status", day.isoformat()) or {}

    # ==================== Batch Methods ====================

    def get_daily_steps_batch(self, start_date: date, end_date: date) -> list[dict]:
        """Fetch step data for a date range in one call.

        Args:
            start_date: Start date (inclusive)
            end_date: End date (inclusive)

        Returns:
            List of daily step data dictionaries
        """
        # _api_call already acquires a rate-limiter token; don't double-count.
        return self._api_call("get_daily_steps", start_date.isoformat(), end_date.isoformat()) or []

    def get_body_battery_batch(self, start_date: date, end_date: date) -> list[dict]:
        """Fetch Body Battery data for a date range in one call.

        Args:
            start_date: Start date (inclusive)
            end_date: End date (inclusive)

        Returns:
            List of Body Battery readings
        """
        return self._api_call("get_body_battery", start_date.isoformat(), end_date.isoformat()) or []

    def get_daily_sleep_batch(self, end_date: date, days: int = 30) -> list[dict]:
        """Fetch sleep scores for multiple days via per-day calls.

        Args:
            end_date: End date (inclusive)
            days: Number of days to fetch

        Returns:
            List of daily sleep score dictionaries
        """
        results = []
        for i in range(days):
            day = end_date - timedelta(days=i)
            try:
                data = self._api_call("get_sleep_data", day.isoformat())
                if data:
                    cal_date = data.get("dailySleepDTO", {}).get("calendarDate")
                    score = data.get("sleepScores", {}).get("overall", {}).get("value")
                    if cal_date:
                        results.append({"calendarDate": cal_date, "sleepScore": score})
            except Exception:
                logger.debug("Sleep fetch failed for %s", day, exc_info=True)
        return results

    def get_daily_stress_batch(self, end_date: date, days: int = 30) -> list[dict]:
        """Fetch stress data for multiple days via per-day calls.

        Args:
            end_date: End date (inclusive)
            days: Number of days to fetch

        Returns:
            List of daily stress dictionaries
        """
        results = []
        for i in range(days):
            day = end_date - timedelta(days=i)
            try:
                data = self._api_call("get_stress_data", day.isoformat())
                if data:
                    avg = data.get("overallStressLevel")
                    results.append({"calendarDate": day.isoformat(), "avgStress": avg})
            except Exception:
                logger.debug("Stress fetch failed for %s", day, exc_info=True)
        return results

    def get_daily_hrv_batch(self, end_date: date, days: int = 30) -> list[dict]:
        """Fetch HRV data for multiple days via per-day calls.

        Args:
            end_date: End date (inclusive)
            days: Number of days to fetch

        Returns:
            List of daily HRV dictionaries
        """
        results = []
        for i in range(days):
            day = end_date - timedelta(days=i)
            try:
                data = self._api_call("get_hrv_data", day.isoformat())
                if data:
                    weekly = data.get("weeklyAvg")
                    results.append({"calendarDate": day.isoformat(), "hrvValue": weekly})
            except Exception:
                logger.debug("HRV fetch failed for %s", day, exc_info=True)
        return results

    # ==================== Respiration & SpO2 ====================

    def get_respiration_data(self, day: date) -> dict:
        """Get all-day respiration data for a specific date.

        Args:
            day: Date to get respiration data for

        Returns:
            Respiration data dictionary
        """
        return self._api_call("get_respiration_data", day.isoformat()) or {}

    def get_spo2_data(self, day: date) -> dict:
        """Get all-day SpO2 data for a specific date.

        Args:
            day: Date to get SpO2 data for

        Returns:
            SpO2 data dictionary
        """
        return self._api_call("get_spo2_data", day.isoformat()) or {}

    # ==================== Utility ====================

    def get_rate_limit_status(self) -> dict:
        """Get current rate limiter status."""
        return self._rate_limiter.get_status()


# Convenience function
def get_garmin_client(
    auth_manager: Optional[GarminAuthManager] = None,
) -> GarminClient:
    """Get a configured Garmin client instance."""
    return GarminClient(auth_manager=auth_manager)
