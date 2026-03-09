"""Retry with exponential backoff for transient API errors."""

import functools
import logging
import random
import time

import httpx

logger = logging.getLogger(__name__)

# HTTP status codes that warrant a retry (transient server / rate-limit errors).
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503})

# Network-level exceptions that indicate transient connectivity issues.
RETRYABLE_EXCEPTIONS = (
    httpx.ConnectError,
    httpx.TimeoutException,
    httpx.RemoteProtocolError,
)


def retry_with_backoff(
    func=None,
    *,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    jitter: bool = True,
    _sleep=None,
):
    """Decorator: retry on transient HTTP/network errors with exponential backoff.

    Retries on:
      - httpx.HTTPStatusError with status in RETRYABLE_STATUS_CODES (429, 500-503)
      - httpx.ConnectError, httpx.TimeoutException, httpx.RemoteProtocolError

    Does NOT retry on:
      - Client errors (400, 401, 403, 404, etc.)
      - Non-HTTP exceptions (ValueError, RuntimeError, etc.)

    Schedule (default): immediate → 1s → 2s → 4s then raise.
    """

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            sleep_fn = _sleep if _sleep is not None else time.sleep
            last_exception = None
            for attempt in range(max_retries + 1):
                try:
                    return fn(*args, **kwargs)
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code not in RETRYABLE_STATUS_CODES:
                        raise
                    last_exception = exc
                except RETRYABLE_EXCEPTIONS as exc:
                    last_exception = exc

                if attempt < max_retries:
                    delay = min(base_delay * (2 ** attempt), max_delay)
                    if jitter:
                        delay *= random.uniform(0.5, 1.5)
                    logger.warning(
                        "Retry %d/%d for %s after %.1fs: %s",
                        attempt + 1,
                        max_retries,
                        fn.__name__,
                        delay,
                        last_exception,
                    )
                    sleep_fn(delay)

            raise last_exception

        return wrapper

    # Support both @retry_with_backoff and @retry_with_backoff()
    if func is not None:
        return decorator(func)
    return decorator
