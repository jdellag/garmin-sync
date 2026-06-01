"""HEVY API client."""

import logging
import sys
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)


class HevyAPIError(Exception):
    """Error from HEVY API."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class HevyClient:
    """HEVY API client wrapper.

    API Documentation: https://api.hevyapp.com/docs/
    Requires HEVY Pro subscription and API key from https://hevy.com/settings?developer
    """

    BASE_URL = "https://api.hevyapp.com/v1"

    def __init__(self, api_key: str):
        """Initialize the HEVY client.

        Args:
            api_key: HEVY API key from developer settings
        """
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({
            "api-key": api_key,
            "Accept": "application/json",
        })
        self._last_request_time: float = 0
        self._min_request_interval: float = 0.5  # Rate limiting

    def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[dict] = None,
        max_retries: int = 3,
    ) -> dict:
        """Make an API request with retry logic.

        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint path
            params: Query parameters
            max_retries: Maximum number of retries on failure

        Returns:
            JSON response as dict

        Raises:
            HevyAPIError: On API errors
        """
        url = f"{self.BASE_URL}{endpoint}"

        # Rate limiting
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_request_interval:
            time.sleep(self._min_request_interval - elapsed)

        for attempt in range(max_retries):
            try:
                self._last_request_time = time.time()
                # (connect, read) timeout so a stalled connection can't hang a
                # sync (incl. the scheduled job) indefinitely.
                response = self.session.request(
                    method, url, params=params, timeout=(5, 30)
                )

                if response.status_code == 429:
                    # Rate limited - wait and retry. Retry-After may be an int
                    # (seconds) or an HTTP-date; int() on a date would crash, so
                    # parse defensively and cap the wait.
                    raw_retry = response.headers.get("Retry-After", "5")
                    try:
                        retry_after = int(raw_retry)
                    except (TypeError, ValueError):
                        retry_after = 5
                    time.sleep(min(max(retry_after, 0), 60))
                    continue

                if response.status_code == 401:
                    raise HevyAPIError("Invalid API key", status_code=401)

                if response.status_code == 403:
                    raise HevyAPIError(
                        "Access denied - HEVY Pro subscription required",
                        status_code=403
                    )

                if response.status_code >= 400:
                    # Full response may contain tokens or sensitive data;
                    # log to stderr only, raise a sanitised message.
                    print(
                        f"HEVY API error {response.status_code}: {response.text}",
                        file=sys.stderr,
                    )
                    raise HevyAPIError(
                        f"API error: HTTP {response.status_code}",
                        status_code=response.status_code
                    )

                return response.json()

            except requests.RequestException as e:
                if attempt == max_retries - 1:
                    raise HevyAPIError(f"Request failed: {e}")
                time.sleep(2 ** attempt)  # Exponential backoff

        raise HevyAPIError("Max retries exceeded")

    def get_workouts(
        self,
        page: int = 1,
        page_size: int = 10,
    ) -> dict:
        """Get paginated list of workouts.

        Args:
            page: Page number (1-indexed)
            page_size: Number of workouts per page (max 10)

        Returns:
            Dict with 'workouts' list and pagination info
        """
        params = {
            "page": page,
            "pageSize": min(page_size, 10),  # API max is 10
        }
        return self._request("GET", "/workouts", params=params)

    def get_workout(self, workout_id: str) -> dict:
        """Get a single workout with full details.

        Args:
            workout_id: HEVY workout ID

        Returns:
            Workout data dict
        """
        return self._request("GET", f"/workouts/{workout_id}")

    def get_workout_count(self) -> dict:
        """Get workout count statistics.

        Returns:
            Dict with 'workout_count' key
        """
        return self._request("GET", "/workouts/count")

    def get_exercise_templates(
        self,
        page: int = 1,
        page_size: int = 10,
    ) -> dict:
        """Get paginated exercise template library.

        Args:
            page: Page number (1-indexed)
            page_size: Number of templates per page (max 10)

        Returns:
            Dict with 'exercise_templates' list and pagination info
        """
        params = {
            "page": page,
            "pageSize": min(page_size, 10),
        }
        return self._request("GET", "/exercise_templates", params=params)

    def get_all_workouts(
        self,
        since_date: Optional[str] = None,
        max_pages: int = 100,
    ) -> list[dict]:
        """Fetch all workouts with pagination.

        Args:
            since_date: Only return workouts after this ISO date string
            max_pages: Maximum number of pages to fetch

        Returns:
            List of all workout dicts
        """
        all_workouts = []
        page = 1

        while page <= max_pages:
            response = self.get_workouts(page=page, page_size=10)
            workouts = response.get("workouts", [])

            if not workouts:
                break

            for workout in workouts:
                # Filter by date if specified
                if since_date:
                    workout_date = (workout.get("start_time") or "")[:10]
                    # Only stop on a genuinely older, *dated* workout. A missing
                    # start_time must not truncate the whole sync (and `None`
                    # must not crash the slice).
                    if workout_date and workout_date < since_date:
                        # Workouts are returned newest first, so we can stop
                        return all_workouts

                all_workouts.append(workout)

            # Check if there are more pages. If page_count is absent, fall back
            # to "a full page implies there may be more" instead of stopping.
            page_count = response.get("page_count")
            if page_count is not None:
                if page >= page_count:
                    break
            elif len(workouts) < 10:  # short page ⇒ last page
                break

            page += 1

        if page > max_pages:
            logger.warning(
                "HEVY workout pagination hit max_pages=%d; results may be "
                "truncated (older workouts not fetched)", max_pages,
            )
        return all_workouts

    def get_all_exercise_templates(self, max_pages: int = 100) -> list[dict]:
        """Fetch all exercise templates with pagination.

        Args:
            max_pages: Maximum number of pages to fetch

        Returns:
            List of all exercise template dicts
        """
        all_templates = []
        page = 1

        while page <= max_pages:
            response = self.get_exercise_templates(page=page, page_size=10)
            templates = response.get("exercise_templates", [])

            if not templates:
                break

            all_templates.extend(templates)

            # Check if there are more pages. Absent page_count ⇒ a full page
            # implies more (don't stop early and silently drop templates).
            page_count = response.get("page_count")
            if page_count is not None:
                if page >= page_count:
                    break
            elif len(templates) < 10:
                break

            page += 1

        if page > max_pages:
            logger.warning(
                "HEVY template pagination hit max_pages=%d; results may be "
                "truncated", max_pages,
            )
        return all_templates
