"""Structured exceptions for BridgeCare AI providers."""


class AIProviderError(Exception):
    """Base exception for AI provider errors without exposing sensitive credentials or PHI."""

    def __init__(
        self,
        error_type: str,
        message: str,
        provider: str = "unknown",
        retryable: bool = False,
    ):
        super().__init__(message)
        self.error_type = error_type
        self.message = message
        self.provider = provider
        self.retryable = retryable


class ProviderConfigurationError(AIProviderError):
    """Raised when provider selection or required credentials/configuration are invalid."""

    def __init__(self, message: str, provider: str = "unknown"):
        super().__init__(
            error_type="PROVIDER_CONFIGURATION_ERROR",
            message=message,
            provider=provider,
            retryable=False,
        )


class ProviderAPIError(AIProviderError):
    """Raised when the upstream AI provider API returns an error or rate limit."""

    def __init__(
        self,
        message: str,
        provider: str = "gemini",
        status_code: int | None = None,
        retryable: bool = False,
    ):
        error_type = "PROVIDER_RATE_LIMIT" if status_code == 429 else "PROVIDER_API_ERROR"
        super().__init__(
            error_type=error_type,
            message=message,
            provider=provider,
            retryable=retryable,
        )
        self.status_code = status_code


class ProviderTimeoutError(AIProviderError):
    """Raised when an AI provider request exceeds its configured timeout."""

    def __init__(self, message: str, provider: str = "gemini"):
        super().__init__(
            error_type="PROVIDER_TIMEOUT",
            message=message,
            provider=provider,
            retryable=True,
        )


class ProviderResponseError(AIProviderError):
    """Raised when the AI provider returns malformed JSON, missing fields, or invalid schema data."""

    def __init__(self, message: str, provider: str = "gemini"):
        super().__init__(
            error_type="PROVIDER_RESPONSE_ERROR",
            message=message,
            provider=provider,
            retryable=False,
        )


class UnverifiedRecordError(AIProviderError, ValueError):
    """Raised when unverified, pending_review, or rejected records are passed to summary generation."""

    def __init__(self, message: str, provider: str = "gemini"):
        AIProviderError.__init__(
            self,
            error_type="UNVERIFIED_RECORD_ERROR",
            message=message,
            provider=provider,
            retryable=False,
        )
