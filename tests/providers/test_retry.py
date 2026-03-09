"""Tests for retry_with_backoff decorator."""

from unittest.mock import MagicMock

import httpx
import pytest

from infraverse.providers.retry import (
    RETRYABLE_STATUS_CODES,
    retry_with_backoff,
)


def _make_http_error(status_code: int) -> httpx.HTTPStatusError:
    """Create an httpx.HTTPStatusError with the given status code."""
    request = httpx.Request("GET", "https://example.com")
    response = httpx.Response(status_code, request=request)
    return httpx.HTTPStatusError(
        f"HTTP {status_code}", request=request, response=response
    )


class TestRetryOnTransientHTTPErrors:
    """Retry on 429, 500, 502, 503 status codes."""

    @pytest.mark.parametrize("status_code", sorted(RETRYABLE_STATUS_CODES))
    def test_retries_on_retryable_status_then_succeeds(self, status_code):
        mock_sleep = MagicMock()
        inner = MagicMock(side_effect=[_make_http_error(status_code), "ok"])

        @retry_with_backoff(max_retries=3, _sleep=mock_sleep)
        def fn():
            return inner()

        assert fn() == "ok"
        assert inner.call_count == 2
        assert mock_sleep.call_count == 1

    @pytest.mark.parametrize("status_code", sorted(RETRYABLE_STATUS_CODES))
    def test_gives_up_after_max_retries(self, status_code):
        mock_sleep = MagicMock()
        error = _make_http_error(status_code)
        inner = MagicMock(side_effect=error)

        @retry_with_backoff(max_retries=3, _sleep=mock_sleep)
        def fn():
            return inner()

        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            fn()
        assert exc_info.value.response.status_code == status_code
        assert inner.call_count == 4  # 1 initial + 3 retries
        assert mock_sleep.call_count == 3


class TestNoRetryOnClientErrors:
    """Client errors (400, 401, 403, 404) should NOT be retried."""

    @pytest.mark.parametrize("status_code", [400, 401, 403, 404])
    def test_no_retry_on_client_error(self, status_code):
        mock_sleep = MagicMock()
        inner = MagicMock(side_effect=_make_http_error(status_code))

        @retry_with_backoff(max_retries=3, _sleep=mock_sleep)
        def fn():
            return inner()

        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            fn()
        assert exc_info.value.response.status_code == status_code
        assert inner.call_count == 1  # No retries
        mock_sleep.assert_not_called()


class TestRetryOnNetworkErrors:
    """Retry on transient network exceptions."""

    @pytest.mark.parametrize(
        "exc_class",
        [httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout],
    )
    def test_retries_on_network_error_then_succeeds(self, exc_class):
        mock_sleep = MagicMock()
        request = httpx.Request("GET", "https://example.com")
        inner = MagicMock(side_effect=[exc_class("oops", request=request), "ok"])

        @retry_with_backoff(max_retries=3, _sleep=mock_sleep)
        def fn():
            return inner()

        assert fn() == "ok"
        assert inner.call_count == 2

    def test_retries_on_remote_protocol_error(self):
        mock_sleep = MagicMock()
        inner = MagicMock(side_effect=[httpx.RemoteProtocolError("reset"), "ok"])

        @retry_with_backoff(max_retries=3, _sleep=mock_sleep)
        def fn():
            return inner()

        assert fn() == "ok"
        assert inner.call_count == 2

    def test_gives_up_on_persistent_network_error(self):
        mock_sleep = MagicMock()
        request = httpx.Request("GET", "https://example.com")
        error = httpx.ConnectError("refused", request=request)
        inner = MagicMock(side_effect=error)

        @retry_with_backoff(max_retries=2, _sleep=mock_sleep)
        def fn():
            return inner()

        with pytest.raises(httpx.ConnectError):
            fn()
        assert inner.call_count == 3  # 1 initial + 2 retries


class TestNoRetryOnNonHTTPExceptions:
    """Non-HTTP exceptions (ValueError, RuntimeError, etc.) should NOT be retried."""

    @pytest.mark.parametrize("exc_class", [ValueError, RuntimeError, KeyError])
    def test_no_retry_on_non_http_exception(self, exc_class):
        mock_sleep = MagicMock()
        inner = MagicMock(side_effect=exc_class("bad"))

        @retry_with_backoff(max_retries=3, _sleep=mock_sleep)
        def fn():
            return inner()

        with pytest.raises(exc_class):
            fn()
        assert inner.call_count == 1
        mock_sleep.assert_not_called()


class TestBackoffTiming:
    """Verify exponential backoff with jitter."""

    def test_exponential_backoff_delays(self):
        mock_sleep = MagicMock()
        error = _make_http_error(500)
        inner = MagicMock(side_effect=error)

        @retry_with_backoff(max_retries=3, base_delay=1.0, jitter=False, _sleep=mock_sleep)
        def fn():
            return inner()

        with pytest.raises(httpx.HTTPStatusError):
            fn()

        # Without jitter: delays are exactly 1s, 2s, 4s
        assert mock_sleep.call_count == 3
        delays = [c.args[0] for c in mock_sleep.call_args_list]
        assert delays == [1.0, 2.0, 4.0]

    def test_max_delay_cap(self):
        mock_sleep = MagicMock()
        error = _make_http_error(500)
        inner = MagicMock(side_effect=error)

        @retry_with_backoff(
            max_retries=5, base_delay=10.0, max_delay=30.0, jitter=False, _sleep=mock_sleep
        )
        def fn():
            return inner()

        with pytest.raises(httpx.HTTPStatusError):
            fn()

        delays = [c.args[0] for c in mock_sleep.call_args_list]
        # base=10: 10, 20, 30(capped), 30(capped), 30(capped)
        assert delays == [10.0, 20.0, 30.0, 30.0, 30.0]

    def test_jitter_varies_delay(self):
        mock_sleep = MagicMock()
        error = _make_http_error(500)
        inner = MagicMock(side_effect=error)

        @retry_with_backoff(max_retries=3, base_delay=1.0, jitter=True, _sleep=mock_sleep)
        def fn():
            return inner()

        with pytest.raises(httpx.HTTPStatusError):
            fn()

        delays = [c.args[0] for c in mock_sleep.call_args_list]
        # With jitter, delays should be in range [base*0.5, base*1.5] * 2^attempt
        assert len(delays) == 3
        assert 0.5 <= delays[0] <= 1.5   # 1.0 * [0.5, 1.5]
        assert 1.0 <= delays[1] <= 3.0   # 2.0 * [0.5, 1.5]
        assert 2.0 <= delays[2] <= 6.0   # 4.0 * [0.5, 1.5]


class TestDecoratorUsage:
    """Test decorator can be used with and without parentheses."""

    def test_bare_decorator(self):

        @retry_with_backoff
        def fn():
            return "hello"

        assert fn() == "hello"

    def test_decorator_with_args(self):
        mock_sleep = MagicMock()

        @retry_with_backoff(max_retries=1, _sleep=mock_sleep)
        def fn():
            return "world"

        assert fn() == "world"

    def test_decorator_preserves_function_name(self):

        @retry_with_backoff
        def my_function():
            pass

        assert my_function.__name__ == "my_function"

    def test_works_on_methods(self):
        mock_sleep = MagicMock()

        class MyClass:
            @retry_with_backoff(max_retries=1, _sleep=mock_sleep)
            def method(self, x):
                return x * 2

        obj = MyClass()
        assert obj.method(5) == 10


class TestMixedFailureSequence:
    """Test recovery after transient failures."""

    def test_500_then_success(self):
        mock_sleep = MagicMock()
        inner = MagicMock(
            side_effect=[_make_http_error(500), _make_http_error(502), "result"]
        )

        @retry_with_backoff(max_retries=3, _sleep=mock_sleep)
        def fn():
            return inner()

        assert fn() == "result"
        assert inner.call_count == 3
        assert mock_sleep.call_count == 2

    def test_network_error_then_http_error_then_success(self):
        mock_sleep = MagicMock()
        request = httpx.Request("GET", "https://example.com")
        inner = MagicMock(
            side_effect=[
                httpx.ConnectError("refused", request=request),
                _make_http_error(503),
                "ok",
            ]
        )

        @retry_with_backoff(max_retries=3, _sleep=mock_sleep)
        def fn():
            return inner()

        assert fn() == "ok"
        assert inner.call_count == 3

    def test_immediate_success_no_sleep(self):
        mock_sleep = MagicMock()
        inner = MagicMock(return_value="fast")

        @retry_with_backoff(max_retries=3, _sleep=mock_sleep)
        def fn():
            return inner()

        assert fn() == "fast"
        assert inner.call_count == 1
        mock_sleep.assert_not_called()
