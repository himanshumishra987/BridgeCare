"""Shared API dependencies: bearer authentication and role checks."""

from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import (
    AuthenticationError,
    PermissionDeniedError,
    ServiceUnavailableError,
)
from app.core.security import ACCESS_TOKEN_TYPE, TokenError, decode_token
from app.db.session import get_db
from app.models.enums import UserRole
from app.models.user import User

bearer_scheme = HTTPBearer(auto_error=False, description="BridgeCare access token (JWT).")

DbSession = Annotated[Session, Depends(get_db)]


def get_current_user(
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
) -> User:
    if credentials is None or not credentials.credentials:
        raise AuthenticationError("A bearer access token is required.")
    try:
        decoded = decode_token(
            credentials.credentials,
            secret_key=get_settings().secret_key,
            expected_type=ACCESS_TOKEN_TYPE,
        )
    except TokenError as exc:
        raise AuthenticationError("The access token is invalid or has expired.") from exc

    user = db.get(User, decoded.subject)
    if user is None or not user.is_active:
        raise AuthenticationError("This account is not available.")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: UserRole):
    allowed = set(roles)

    def dependency(user: CurrentUser) -> User:
        if UserRole(str(user.role)) not in allowed:
            raise PermissionDeniedError("This account cannot perform that action.")
        return user

    return dependency


def require_ai_service(request: Request) -> None:
    """Authenticate the internal AI engine with a shared service key.

    If ``BRIDGECARE_AI_SERVICE_KEY`` is unset the endpoints are disabled rather
    than open, so a misconfigured deployment fails closed.
    """
    settings = get_settings()
    if not settings.ai_service_key:
        raise ServiceUnavailableError(
            "The AI engine integration is not configured on this deployment."
        )
    provided = request.headers.get("x-ai-service-key", "")
    if not provided or not secrets.compare_digest(provided, settings.ai_service_key):
        raise AuthenticationError("A valid AI service key is required.")
