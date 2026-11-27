"""Uniform application errors and API error envelope.

Every error response has the shape::

    {"error": {"code": "...", "message": "...", "details": [...]}}

Details never contain request input values (which may be medical data) and
never contain secrets.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class AppError(Exception):
    """Base class for expected application errors."""

    status_code: int = 400
    code: str = "bad_request"
    message: str = "The request could not be processed."

    def __init__(
        self,
        message: str | None = None,
        *,
        details: list[dict[str, Any]] | None = None,
        code: str | None = None,
        status_code: int | None = None,
    ) -> None:
        self.message = message or self.message
        self.details = details or []
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code
        super().__init__(self.message)

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details:
            payload["details"] = self.details
        return payload


class AuthenticationError(AppError):
    status_code = 401
    code = "not_authenticated"
    message = "Authentication is required."


class PermissionDeniedError(AppError):
    status_code = 403
    code = "permission_denied"
    message = "You do not have permission to perform this action."


class NotFoundError(AppError):
    """Used both for missing resources and for resources the caller may not see.

    Returning the same response for both cases prevents resource enumeration
    and therefore cross-patient identifier leakage (IDOR).
    """

    status_code = 404
    code = "not_found"
    message = "The requested resource was not found."


class ConflictError(AppError):
    status_code = 409
    code = "conflict"
    message = "The request conflicts with the current state of the resource."


class ValidationAppError(AppError):
    status_code = 422
    code = "validation_error"
    message = "The submitted data is not valid."


class UnsupportedMediaError(AppError):
    status_code = 415
    code = "unsupported_media_type"
    message = "This file type is not supported."


class PayloadTooLargeError(AppError):
    status_code = 413
    code = "payload_too_large"
    message = "The uploaded file exceeds the permitted size."


class RateLimitedError(AppError):
    status_code = 429
    code = "rate_limited"
    message = "Too many attempts. Try again later."


class ServiceUnavailableError(AppError):
    status_code = 503
    code = "service_unavailable"
    message = "A required service is not configured."


class MalwareDetectedError(AppError):
    """A scan returned a positive verdict; the file is quarantined."""

    status_code = 422
    code = "malware_detected"
    message = "This file failed malware scanning and was quarantined."


class ScanRequiredError(AppError):
    """Processing was requested before a clean scan verdict existed."""

    status_code = 409
    code = "document_not_scanned"
    message = "This document must pass a malware scan before it can be processed."


class VerificationUnavailableError(AppError):
    """The insurer verification provider could not be reached."""

    status_code = 503
    code = "verification_unavailable"
    message = "Insurer verification is currently unavailable for this policy."


def _error_response(status_code: int, payload: dict[str, Any]) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error": payload})


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error_handler(_: Request, exc: AppError) -> JSONResponse:
        return _error_response(exc.status_code, exc.to_payload())

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Deliberately excludes `exc.errors()[i]["input"]`: request values can be PHI.
        details = [
            {
                "location": ".".join(str(part) for part in error.get("loc", ())),
                "type": error.get("type", "invalid"),
                "message": error.get("msg", "Invalid value."),
            }
            for error in exc.errors()
        ]
        return _error_response(
            422,
            {
                "code": "validation_error",
                "message": "The submitted data is not valid.",
                "details": details,
            },
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {
            401: "not_authenticated",
            403: "permission_denied",
            404: "not_found",
            405: "method_not_allowed",
            429: "rate_limited",
        }.get(exc.status_code, "http_error")
        message = exc.detail if isinstance(exc.detail, str) else "Request failed."
        return _error_response(exc.status_code, {"code": code, "message": message})
