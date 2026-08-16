from openai import APIConnectionError, APIStatusError, APITimeoutError, RateLimitError


class RetryableError(Exception):
    """Wrapper that marks an error as safe to retry."""

    def __init__(self, original: Exception, reason: str):
        self.original = original
        self.reason = reason
        super().__init__(f"Retryable: {reason} ({original})")


class NonRetryableError(Exception):
    """Wrapper that marks an error as not safe to retry."""

    def __init__(self, original: Exception, reason: str):
        self.original = original
        self.reason = reason
        super().__init__(f"Non-retryable: {reason} ({original})")


def is_retryable(error: Exception) -> bool:
    if isinstance(error, APITimeoutError):
        return True
    if isinstance(error, RateLimitError):
        return True
    if isinstance(error, APIConnectionError):
        return True
    if isinstance(error, APIStatusError):
        return error.status_code >= 500
    return False


def classify(error: Exception) -> RetryableError | NonRetryableError:
    if is_retryable(error):
        return RetryableError(error, _retryable_reason(error))
    return NonRetryableError(error, _non_retryable_reason(error))


def _retryable_reason(error: Exception) -> str:
    if isinstance(error, APITimeoutError):
        return "request timed out"
    if isinstance(error, RateLimitError):
        return "rate limited"
    if isinstance(error, APIConnectionError):
        return "connection error"
    if isinstance(error, APIStatusError):
        return f"server error (HTTP {error.status_code})"
    return "unknown retryable error"


def _non_retryable_reason(error: Exception) -> str:
    if isinstance(error, APIStatusError):
        return f"client error (HTTP {error.status_code})"
    return f"non-retryable error: {type(error).__name__}"
