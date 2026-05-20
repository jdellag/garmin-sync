"""Rate limiting for Garmin API calls."""

import time
from collections import deque
from functools import wraps
from threading import Lock
from typing import Callable, TypeVar

T = TypeVar("T")


class RateLimiter:
    """Token bucket rate limiter for API calls.

    Enforces rate limits to avoid hitting Garmin API restrictions.
    Thread-safe implementation using locks.
    """

    def __init__(
        self,
        calls_per_minute: int = 15,
        calls_per_hour: int = 800,
    ):
        """Initialize rate limiter.

        Args:
            calls_per_minute: Maximum calls allowed per minute
            calls_per_hour: Maximum calls allowed per hour
        """
        self.calls_per_minute = calls_per_minute
        self.calls_per_hour = calls_per_hour
        self._minute_calls: deque = deque()
        self._hour_calls: deque = deque()
        self._lock = Lock()

    def _clean_old_calls(self, now: float) -> None:
        """Remove expired call timestamps."""
        minute_ago = now - 60
        hour_ago = now - 3600

        while self._minute_calls and self._minute_calls[0] < minute_ago:
            self._minute_calls.popleft()

        while self._hour_calls and self._hour_calls[0] < hour_ago:
            self._hour_calls.popleft()

    def wait_if_needed(self) -> float:
        """Block until a call is allowed under rate limits.

        Returns:
            Time spent waiting in seconds (0 if no wait needed).
        """
        total_wait = 0.0

        with self._lock:
            now = time.time()
            self._clean_old_calls(now)

            # Check minute limit
            if len(self._minute_calls) >= self.calls_per_minute:
                wait_time = 60 - (now - self._minute_calls[0])
                if wait_time > 0:
                    total_wait += wait_time
                    time.sleep(wait_time)
                    now = time.time()
                    self._clean_old_calls(now)

            # Check hour limit
            if len(self._hour_calls) >= self.calls_per_hour:
                wait_time = 3600 - (now - self._hour_calls[0])
                if wait_time > 0:
                    total_wait += wait_time
                    time.sleep(wait_time)
                    now = time.time()
                    self._clean_old_calls(now)

            # Record this call
            call_time = time.time()
            self._minute_calls.append(call_time)
            self._hour_calls.append(call_time)

        return total_wait

    def acquire(self) -> float:
        """Acquire permission to make an API call.

        Alias for wait_if_needed() for more intuitive API.

        Returns:
            Time spent waiting in seconds.
        """
        return self.wait_if_needed()

    def get_status(self) -> dict:
        """Get current rate limiter status.

        Returns:
            Dict with current call counts and limits.
        """
        with self._lock:
            now = time.time()
            self._clean_old_calls(now)

            return {
                "calls_last_minute": len(self._minute_calls),
                "calls_last_hour": len(self._hour_calls),
                "minute_limit": self.calls_per_minute,
                "hour_limit": self.calls_per_hour,
                "minute_remaining": self.calls_per_minute - len(self._minute_calls),
                "hour_remaining": self.calls_per_hour - len(self._hour_calls),
            }

    def reset(self) -> None:
        """Reset all call tracking (useful for testing)."""
        with self._lock:
            self._minute_calls.clear()
            self._hour_calls.clear()

    def __call__(self, func: Callable[..., T]) -> Callable[..., T]:
        """Decorator for rate-limited functions.

        Usage:
            rate_limiter = RateLimiter()

            @rate_limiter
            def fetch_data():
                ...
        """
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            self.wait_if_needed()
            return func(*args, **kwargs)
        return wrapper


def retry_with_backoff(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential: bool = True,
    exceptions: tuple = (Exception,),
):
    """Decorator for retry logic with exponential backoff.

    Args:
        max_retries: Maximum number of retry attempts
        base_delay: Initial delay between retries in seconds
        max_delay: Maximum delay between retries
        exponential: Use exponential backoff if True, constant delay if False
        exceptions: Tuple of exception types to catch and retry

    Usage:
        @retry_with_backoff(max_retries=3, exceptions=(ConnectionError,))
        def unreliable_function():
            ...
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            last_exception = None

            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e

                    if attempt < max_retries:
                        if exponential:
                            delay = min(base_delay * (2 ** attempt), max_delay)
                        else:
                            delay = base_delay
                        time.sleep(delay)

            raise last_exception

        return wrapper
    return decorator
