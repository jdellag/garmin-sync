"""Tests for rate limiter."""

import time
from unittest.mock import patch

import pytest

from garmin_sync.api.rate_limiter import RateLimiter, retry_with_backoff


class TestRateLimiter:
    """Test RateLimiter class."""

    def test_default_limits(self):
        """Test default rate limits."""
        limiter = RateLimiter()
        assert limiter.calls_per_minute == 15
        assert limiter.calls_per_hour == 800

    def test_custom_limits(self):
        """Test custom rate limits."""
        limiter = RateLimiter(calls_per_minute=10, calls_per_hour=50)
        assert limiter.calls_per_minute == 10
        assert limiter.calls_per_hour == 50

    def test_no_wait_under_limit(self):
        """Test that no wait occurs when under limits."""
        limiter = RateLimiter(calls_per_minute=10)

        # First call should not wait
        wait_time = limiter.acquire()
        assert wait_time == 0.0

    def test_calls_tracked(self):
        """Test that calls are tracked correctly."""
        limiter = RateLimiter(calls_per_minute=10)

        # Make 5 calls
        for _ in range(5):
            limiter.acquire()

        status = limiter.get_status()
        assert status["calls_last_minute"] == 5
        assert status["minute_remaining"] == 5

    def test_status(self):
        """Test get_status returns correct info."""
        limiter = RateLimiter(calls_per_minute=15, calls_per_hour=100)

        status = limiter.get_status()
        assert status["minute_limit"] == 15
        assert status["hour_limit"] == 100
        assert status["calls_last_minute"] == 0
        assert status["minute_remaining"] == 15

    def test_reset(self):
        """Test reset clears call tracking."""
        limiter = RateLimiter(calls_per_minute=10)

        # Make some calls
        for _ in range(5):
            limiter.acquire()

        assert limiter.get_status()["calls_last_minute"] == 5

        # Reset
        limiter.reset()

        assert limiter.get_status()["calls_last_minute"] == 0

    def test_decorator_usage(self):
        """Test using rate limiter as a decorator."""
        limiter = RateLimiter(calls_per_minute=10)
        call_count = 0

        @limiter
        def test_func():
            nonlocal call_count
            call_count += 1
            return "result"

        result = test_func()
        assert result == "result"
        assert call_count == 1
        assert limiter.get_status()["calls_last_minute"] == 1

    @patch("garmin_sync.api.rate_limiter.time.sleep")
    @patch("garmin_sync.api.rate_limiter.time.time")
    def test_minute_limit_wait(self, mock_time, mock_sleep):
        """Test waiting when minute limit is reached."""
        # Set up time mock - start at time 100
        current_time = [100.0]

        def get_time():
            return current_time[0]

        def do_sleep(seconds):
            current_time[0] += seconds

        mock_time.side_effect = get_time
        mock_sleep.side_effect = do_sleep

        limiter = RateLimiter(calls_per_minute=2, calls_per_hour=100)

        # First two calls should not wait
        limiter.acquire()
        current_time[0] += 1  # 1 second later
        limiter.acquire()

        # Third call should wait
        current_time[0] += 1  # Another second later
        limiter.acquire()

        # Should have slept to wait for minute limit
        assert mock_sleep.called

    def test_old_calls_cleaned(self):
        """Test that old calls are cleaned up."""
        limiter = RateLimiter(calls_per_minute=5)

        # Make calls
        for _ in range(3):
            limiter.acquire()

        # Simulate time passing by manipulating internal state
        # Move all calls to 61 seconds ago
        old_time = time.time() - 61
        limiter._minute_calls.clear()
        limiter._hour_calls.clear()
        for _ in range(3):
            limiter._minute_calls.append(old_time)
            limiter._hour_calls.append(old_time)

        # Get status should clean old calls
        status = limiter.get_status()
        assert status["calls_last_minute"] == 0


class TestRetryWithBackoff:
    """Test retry_with_backoff decorator."""

    def test_no_retry_on_success(self):
        """Test that successful calls don't retry."""
        call_count = 0

        @retry_with_backoff(max_retries=3)
        def success_func():
            nonlocal call_count
            call_count += 1
            return "success"

        result = success_func()
        assert result == "success"
        assert call_count == 1

    def test_retry_on_failure(self):
        """Test that failures trigger retries."""
        call_count = 0

        @retry_with_backoff(max_retries=3, base_delay=0.01, exceptions=(ValueError,))
        def failing_func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("Error")
            return "success"

        result = failing_func()
        assert result == "success"
        assert call_count == 3

    def test_max_retries_exceeded(self):
        """Test that max retries raises exception."""
        call_count = 0

        @retry_with_backoff(max_retries=2, base_delay=0.01, exceptions=(ValueError,))
        def always_fails():
            nonlocal call_count
            call_count += 1
            raise ValueError("Always fails")

        with pytest.raises(ValueError) as exc_info:
            always_fails()

        assert "Always fails" in str(exc_info.value)
        assert call_count == 3  # Initial + 2 retries

    def test_specific_exceptions(self):
        """Test that only specified exceptions are caught."""
        @retry_with_backoff(max_retries=3, base_delay=0.01, exceptions=(ValueError,))
        def raises_type_error():
            raise TypeError("Wrong type")

        # TypeError should not be caught
        with pytest.raises(TypeError):
            raises_type_error()

    @patch("garmin_sync.api.rate_limiter.time.sleep")
    def test_exponential_backoff(self, mock_sleep):
        """Test exponential backoff delays."""
        call_count = 0

        @retry_with_backoff(max_retries=3, base_delay=1.0, exponential=True, exceptions=(ValueError,))
        def failing_func():
            nonlocal call_count
            call_count += 1
            raise ValueError("Error")

        with pytest.raises(ValueError):
            failing_func()

        # Should have slept with exponential delays: 1, 2, 4 seconds
        assert mock_sleep.call_count == 3
        delays = [call[0][0] for call in mock_sleep.call_args_list]
        assert delays == [1.0, 2.0, 4.0]

    @patch("garmin_sync.api.rate_limiter.time.sleep")
    def test_constant_backoff(self, mock_sleep):
        """Test constant backoff delays."""
        call_count = 0

        @retry_with_backoff(max_retries=2, base_delay=1.0, exponential=False, exceptions=(ValueError,))
        def failing_func():
            nonlocal call_count
            call_count += 1
            raise ValueError("Error")

        with pytest.raises(ValueError):
            failing_func()

        # Should have slept with constant delays: 1, 1 seconds
        assert mock_sleep.call_count == 2
        delays = [call[0][0] for call in mock_sleep.call_args_list]
        assert delays == [1.0, 1.0]

    @patch("garmin_sync.api.rate_limiter.time.sleep")
    def test_max_delay_cap(self, mock_sleep):
        """Test that delays are capped at max_delay."""
        @retry_with_backoff(
            max_retries=5, base_delay=10.0, max_delay=25.0,
            exponential=True, exceptions=(ValueError,)
        )
        def failing_func():
            raise ValueError("Error")

        with pytest.raises(ValueError):
            failing_func()

        # Delays should be: 10, 20, 25 (capped), 25 (capped), 25 (capped)
        delays = [call[0][0] for call in mock_sleep.call_args_list]
        assert delays == [10.0, 20.0, 25.0, 25.0, 25.0]
