import httpx
import pytest

from openai import APIConnectionError, APIStatusError, APITimeoutError, RateLimitError

from src.errors import classify, is_retryable, NonRetryableError, RetryableError


def _make_status_error(status_code: int) -> APIStatusError:
    mock_response = httpx.Response(status_code=status_code, request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"))
    return APIStatusError(
        message=f"Error {status_code}",
        response=mock_response,
        body=None,
    )


def _make_rate_limit_error() -> RateLimitError:
    mock_response = httpx.Response(status_code=429, request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"))
    return RateLimitError(
        message="Rate limited",
        response=mock_response,
        body=None,
    )


class TestIsRetryable:
    def test_timeout_is_retryable(self):
        err = APITimeoutError(request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"))
        assert is_retryable(err) is True

    def test_rate_limit_is_retryable(self):
        assert is_retryable(_make_rate_limit_error()) is True

    def test_connection_error_is_retryable(self):
        err = APIConnectionError(request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"))
        assert is_retryable(err) is True

    def test_server_error_500_is_retryable(self):
        assert is_retryable(_make_status_error(500)) is True

    def test_server_error_503_is_retryable(self):
        assert is_retryable(_make_status_error(503)) is True

    def test_client_error_400_is_not_retryable(self):
        assert is_retryable(_make_status_error(400)) is False

    def test_client_error_401_is_not_retryable(self):
        assert is_retryable(_make_status_error(401)) is False

    def test_client_error_404_is_not_retryable(self):
        assert is_retryable(_make_status_error(404)) is False

    def test_generic_exception_is_not_retryable(self):
        assert is_retryable(ValueError("bad")) is False


class TestClassify:
    def test_classifies_timeout_as_retryable(self):
        err = APITimeoutError(request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"))
        result = classify(err)
        assert isinstance(result, RetryableError)
        assert "timed out" in result.reason

    def test_classifies_400_as_non_retryable(self):
        result = classify(_make_status_error(400))
        assert isinstance(result, NonRetryableError)
        assert "client error" in result.reason

    def test_classifies_rate_limit_as_retryable(self):
        result = classify(_make_rate_limit_error())
        assert isinstance(result, RetryableError)
        assert "rate limited" in result.reason
