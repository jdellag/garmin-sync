"""Tests for Garmin API client."""

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from garmin_sync.api.client import GarminAPIError, GarminClient, get_garmin_client
from garmin_sync.api.rate_limiter import RateLimiter


class TestGarminClient:
    """Test GarminClient class."""

    @pytest.fixture
    def mock_auth(self):
        """Create mock auth manager."""
        auth = MagicMock()
        auth.ensure_authenticated.return_value = MagicMock()
        return auth

    @pytest.fixture
    def client(self, mock_auth):
        """Create GarminClient with mocked dependencies."""
        limiter = RateLimiter(calls_per_minute=100)
        return GarminClient(auth_manager=mock_auth, rate_limiter=limiter)

    def test_client_creation(self, mock_auth):
        """Test creating a GarminClient."""
        client = GarminClient(auth_manager=mock_auth)
        assert client._auth == mock_auth

    def test_rate_limiter_created(self, mock_auth):
        """Test that rate limiter is created if not provided."""
        client = GarminClient(auth_manager=mock_auth)
        assert client._rate_limiter is not None
        assert isinstance(client._rate_limiter, RateLimiter)

    def test_get_activities(self, client, mock_auth):
        """Test getting activities."""
        mock_garmin = mock_auth.ensure_authenticated.return_value
        mock_garmin.get_activities.return_value = [
            {"activityId": "1", "activityName": "Run"},
            {"activityId": "2", "activityName": "Bike"},
        ]

        activities = client.get_activities(start=0, limit=10)

        assert len(activities) == 2
        mock_garmin.get_activities.assert_called_once_with(0, 10)

    def test_get_activities_by_date(self, client, mock_auth):
        """Test getting activities by date range."""
        mock_garmin = mock_auth.ensure_authenticated.return_value
        mock_garmin.get_activities_by_date.return_value = [
            {"activityId": "1", "startTimeGMT": "2024-01-15T07:00:00"},
        ]

        activities = client.get_activities_by_date(
            start_date=date(2024, 1, 10),
            end_date=date(2024, 1, 15),
        )

        assert len(activities) == 1
        mock_garmin.get_activities_by_date.assert_called_once_with(
            "2024-01-10", "2024-01-15"
        )

    def test_get_activity(self, client, mock_auth):
        """Test getting single activity."""
        mock_garmin = mock_auth.ensure_authenticated.return_value
        mock_garmin.get_activity.return_value = {
            "activityId": "12345",
            "activityName": "Morning Run",
        }

        activity = client.get_activity("12345")

        assert activity["activityId"] == "12345"
        mock_garmin.get_activity.assert_called_once_with("12345")

    def test_download_activity_fit_extracts_from_zip(self, client, mock_auth):
        """download_activity_fit must call download_activity with the ORIGINAL
        enum (not the string 'fit') and return the unzipped FIT bytes."""
        import io
        import zipfile
        from garminconnect import Garmin

        # Build a fake zip containing one .fit member with known bytes
        fit_payload = b"\x0e\x10\xc0R.FIT\x00\x00fake-fit-body"
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("12345.fit", fit_payload)
        zip_bytes = buf.getvalue()

        mock_garmin = mock_auth.ensure_authenticated.return_value
        mock_garmin.download_activity.return_value = zip_bytes

        result = client.download_activity_fit("12345")

        assert result == fit_payload
        mock_garmin.download_activity.assert_called_once_with(
            "12345", Garmin.ActivityDownloadFormat.ORIGINAL
        )

    def test_download_activity_fit_raises_when_zip_has_no_fit(self, client, mock_auth):
        """If the downloaded zip has no .fit member, raise rather than
        silently returning empty."""
        import io
        import zipfile

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("readme.txt", b"not a fit file")
        zip_bytes = buf.getvalue()

        mock_garmin = mock_auth.ensure_authenticated.return_value
        mock_garmin.download_activity.return_value = zip_bytes

        with pytest.raises(GarminAPIError):
            client.download_activity_fit("12345")

    def test_get_stats(self, client, mock_auth):
        """Test getting daily stats."""
        mock_garmin = mock_auth.ensure_authenticated.return_value
        mock_garmin.get_stats.return_value = {
            "totalSteps": 10000,
            "totalKilocalories": 2500,
        }

        stats = client.get_stats(date(2024, 1, 15))

        assert stats["totalSteps"] == 10000
        mock_garmin.get_stats.assert_called_once_with("2024-01-15")

    def test_get_sleep_data(self, client, mock_auth):
        """Test getting sleep data."""
        mock_garmin = mock_auth.ensure_authenticated.return_value
        mock_garmin.get_sleep_data.return_value = {
            "dailySleepDTO": {"sleepTimeSeconds": 28800},
        }

        sleep = client.get_sleep_data(date(2024, 1, 15))

        assert sleep["dailySleepDTO"]["sleepTimeSeconds"] == 28800
        mock_garmin.get_sleep_data.assert_called_once_with("2024-01-15")

    def test_get_heart_rates(self, client, mock_auth):
        """Test getting heart rate data."""
        mock_garmin = mock_auth.ensure_authenticated.return_value
        mock_garmin.get_heart_rates.return_value = {
            "restingHeartRate": 52,
            "maxHeartRate": 180,
        }

        hr = client.get_heart_rates(date(2024, 1, 15))

        assert hr["restingHeartRate"] == 52
        mock_garmin.get_heart_rates.assert_called_once_with("2024-01-15")

    def test_get_resting_heart_rate(self, client, mock_auth):
        """Test getting resting heart rate."""
        mock_garmin = mock_auth.ensure_authenticated.return_value
        mock_garmin.get_heart_rates.return_value = {"restingHeartRate": 52}

        rhr = client.get_resting_heart_rate(date(2024, 1, 15))

        assert rhr == 52

    def test_get_stress_data(self, client, mock_auth):
        """Test getting stress data."""
        mock_garmin = mock_auth.ensure_authenticated.return_value
        mock_garmin.get_stress_data.return_value = {
            "overallStressLevel": 35,
            "avgStressLevel": 30,
        }

        stress = client.get_stress_data(date(2024, 1, 15))

        assert stress["overallStressLevel"] == 35

    def test_get_hrv_data(self, client, mock_auth):
        """Test getting HRV data."""
        mock_garmin = mock_auth.ensure_authenticated.return_value
        mock_garmin.get_hrv_data.return_value = {
            "hrvSummary": {"weeklyAvg": 45},
        }

        hrv = client.get_hrv_data(date(2024, 1, 15))

        assert hrv["hrvSummary"]["weeklyAvg"] == 45

    def test_get_body_battery(self, client, mock_auth):
        """Test getting body battery data."""
        mock_garmin = mock_auth.ensure_authenticated.return_value
        mock_garmin.get_body_battery.return_value = [
            [1705305600000, 65, 0, "charged"],
            [1705309200000, 70, 5, "charged"],
        ]

        bb = client.get_body_battery(date(2024, 1, 15))

        assert len(bb) == 2
        mock_garmin.get_body_battery.assert_called_once_with(
            "2024-01-15", "2024-01-16"
        )

    def test_get_training_readiness(self, client, mock_auth):
        """Test getting training readiness."""
        mock_garmin = mock_auth.ensure_authenticated.return_value
        mock_garmin.get_training_readiness.return_value = {
            "score": 75,
            "level": "MODERATE",
        }

        readiness = client.get_training_readiness(date(2024, 1, 15))

        assert readiness["score"] == 75

    def test_rate_limit_status(self, client):
        """Test getting rate limit status."""
        status = client.get_rate_limit_status()

        assert "calls_last_minute" in status
        assert "minute_limit" in status

    def test_api_error_handling(self, client, mock_auth):
        """Test that API errors are wrapped."""
        mock_garmin = mock_auth.ensure_authenticated.return_value
        mock_garmin.get_activities.side_effect = Exception("Network error")

        with pytest.raises(GarminAPIError) as exc_info:
            client.get_activities()

        assert "get_activities failed" in str(exc_info.value)

    def test_empty_response_handling(self, client, mock_auth):
        """Test that None responses are converted to empty collections."""
        mock_garmin = mock_auth.ensure_authenticated.return_value
        mock_garmin.get_activities.return_value = None

        activities = client.get_activities()

        assert activities == []

    def test_rate_limiter_used(self, mock_auth):
        """Test that rate limiter is called for each API request."""
        limiter = RateLimiter(calls_per_minute=100)
        client = GarminClient(auth_manager=mock_auth, rate_limiter=limiter)

        mock_garmin = mock_auth.ensure_authenticated.return_value
        mock_garmin.get_activities.return_value = []

        # Make multiple calls
        for _ in range(5):
            client.get_activities()

        status = limiter.get_status()
        assert status["calls_last_minute"] == 5


class TestGetGarminClient:
    """Test get_garmin_client function."""

    @patch("garmin_sync.api.client.get_auth_manager")
    @patch("garmin_sync.api.client.get_settings")
    def test_creates_client(self, mock_settings, mock_get_auth):
        """Test that get_garmin_client creates a client."""
        mock_auth = MagicMock()
        mock_get_auth.return_value = mock_auth

        client = get_garmin_client()

        assert isinstance(client, GarminClient)

    def test_with_custom_auth(self):
        """Test get_garmin_client with custom auth manager."""
        mock_auth = MagicMock()
        client = get_garmin_client(auth_manager=mock_auth)

        assert client._auth == mock_auth
