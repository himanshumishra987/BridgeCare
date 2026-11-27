"""Authentication endpoints.

Security properties implemented here:
* scrypt password hashing with per-user salts;
* short-lived access tokens plus rotating, server-revocable refresh tokens;
* account lockout after repeated failed logins;
* identical error text for unknown email and wrong password, with a dummy hash
  verification so response timing does not reveal whether an account exists;
* password change revokes every outstanding session.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from functools import lru_cache

from fastapi import APIRouter, Request, status
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from app.api.deps import CurrentUser, DbSession
from app.core.config import get_settings
from app.core.errors import AuthenticationError, ConflictError, RateLimitedError
from app.core.security import (
    REFRESH_TOKEN_TYPE,
    TokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    hash_token,
    verify_password,
)
from app.models.enums import AuditOutcome, UserRole
from app.models.patient import PatientProfile
from app.models.user import AuthSession, User
from app.schemas.auth import (
    LoginRequest,
    LogoutRequest,
    MeOut,
    PasswordChangeRequest,
    RefreshRequest,
    RegisterRequest,
    TokenPair,
    UserOut,
)
from app.schemas.common import OkResponse
from app.services.audit import record_audit

router = APIRouter(prefix="/auth", tags=["Authentication"])

MAX_FAILED_ATTEMPTS = 8
LOCKOUT_DURATION = timedelta(minutes=15)
INVALID_CREDENTIALS = "Invalid email or password."


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


@lru_cache(maxsize=1)
def _dummy_password_hash() -> str:
    """Used to keep unknown-account logins as slow as real ones."""
    return hash_password(secrets.token_urlsafe(32))


def _session_metadata(request: Request) -> tuple[str | None, str | None]:
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    return (
        ip_address[:45] if ip_address else None,
        user_agent[:255] if user_agent else None,
    )


def _issue_token_pair(db, user: User, request: Request) -> TokenPair:
    settings = get_settings()
    access = create_access_token(
        user_id=user.id,
        role=str(user.role),
        secret_key=settings.secret_key,
        ttl=settings.access_token_ttl,
    )
    refresh = create_refresh_token(
        user_id=user.id,
        role=str(user.role),
        secret_key=settings.secret_key,
        ttl=settings.refresh_token_ttl,
    )
    ip_address, user_agent = _session_metadata(request)
    db.add(
        AuthSession(
            user_id=user.id,
            refresh_token_hash=hash_token(refresh.token),
            expires_at=refresh.expires_at,
            ip_address=ip_address,
            user_agent=user_agent,
        )
    )
    db.flush()
    return TokenPair(
        access_token=access.token,
        refresh_token=refresh.token,
        expires_in=int(settings.access_token_ttl.total_seconds()),
    )


@router.post(
    "/register",
    response_model=TokenPair,
    status_code=status.HTTP_201_CREATED,
    summary="Create a patient account and its health profile",
)
def register(payload: RegisterRequest, request: Request, db: DbSession) -> TokenPair:
    email = str(payload.email).strip().lower()
    if db.scalar(select(User.id).where(User.email == email)) is not None:
        raise ConflictError("An account with this email already exists.")

    user = User(
        email=email,
        password_hash=hash_password(payload.password),
        full_name=payload.full_name.strip(),
        role=UserRole.PATIENT,
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError as exc:  # concurrent registration race
        db.rollback()
        raise ConflictError("An account with this email already exists.") from exc

    db.add(
        PatientProfile(
            user_id=user.id,
            display_name=user.full_name,
            date_of_birth=payload.date_of_birth,
            sex_at_birth=payload.sex_at_birth,
            primary_language=payload.primary_language,
        )
    )
    db.flush()
    record_audit(
        db,
        action="auth.registered",
        actor_user_id=user.id,
        actor_role=str(user.role),
        resource_type="user",
        resource_id=str(user.id),
        request=request,
    )
    return _issue_token_pair(db, user, request)


@router.post("/login", response_model=TokenPair, summary="Exchange credentials for tokens")
def login(payload: LoginRequest, request: Request, db: DbSession) -> TokenPair:
    email = str(payload.email).strip().lower()
    user = db.scalar(select(User).where(User.email == email))

    if user is None:
        verify_password(payload.password, _dummy_password_hash())
        record_audit(
            db,
            action="auth.login",
            outcome=AuditOutcome.DENIED,
            request=request,
            context={"reason": "unknown_account"},
        )
        raise AuthenticationError(INVALID_CREDENTIALS)

    if not user.is_active:
        record_audit(
            db,
            action="auth.login",
            actor_user_id=user.id,
            patient_id=None,
            outcome=AuditOutcome.DENIED,
            request=request,
            context={"reason": "inactive_account"},
        )
        raise AuthenticationError(INVALID_CREDENTIALS)

    locked_until = _aware(user.locked_until)
    if locked_until is not None and locked_until > _now():
        record_audit(
            db,
            action="auth.login",
            actor_user_id=user.id,
            outcome=AuditOutcome.DENIED,
            request=request,
            context={"reason": "locked_out"},
        )
        raise RateLimitedError("Too many failed attempts. Try again later.")

    if not verify_password(payload.password, user.password_hash):
        user.failed_login_attempts += 1
        if user.failed_login_attempts >= MAX_FAILED_ATTEMPTS:
            user.locked_until = _now() + LOCKOUT_DURATION
            user.failed_login_attempts = 0
        db.flush()
        record_audit(
            db,
            action="auth.login",
            actor_user_id=user.id,
            outcome=AuditOutcome.DENIED,
            request=request,
            context={"reason": "bad_password"},
        )
        raise AuthenticationError(INVALID_CREDENTIALS)

    user.failed_login_attempts = 0
    user.locked_until = None
    user.last_login_at = _now()
    db.flush()
    record_audit(
        db,
        action="auth.login",
        actor_user_id=user.id,
        actor_role=str(user.role),
        resource_type="user",
        resource_id=str(user.id),
        request=request,
    )
    return _issue_token_pair(db, user, request)


@router.post("/refresh", response_model=TokenPair, summary="Rotate a refresh token")
def refresh(payload: RefreshRequest, request: Request, db: DbSession) -> TokenPair:
    settings = get_settings()
    try:
        decoded = decode_token(
            payload.refresh_token,
            secret_key=settings.secret_key,
            expected_type=REFRESH_TOKEN_TYPE,
        )
    except TokenError as exc:
        raise AuthenticationError("Session expired. Sign in again.") from exc

    session = db.scalar(
        select(AuthSession).where(
            AuthSession.refresh_token_hash == hash_token(payload.refresh_token)
        )
    )
    now = _now()
    if session is None or session.revoked_at is not None:
        raise AuthenticationError("Session expired. Sign in again.")
    if _aware(session.expires_at) <= now:
        raise AuthenticationError("Session expired. Sign in again.")

    user = db.get(User, decoded.subject)
    if user is None or not user.is_active:
        raise AuthenticationError("This account is not available.")

    # Rotation: the presented refresh token can never be used twice.
    session.revoked_at = now
    db.flush()
    return _issue_token_pair(db, user, request)


@router.post("/logout", response_model=OkResponse, summary="Revoke a refresh token")
def logout(payload: LogoutRequest, request: Request, db: DbSession) -> OkResponse:
    session = db.scalar(
        select(AuthSession).where(
            AuthSession.refresh_token_hash == hash_token(payload.refresh_token)
        )
    )
    if session is not None and session.revoked_at is None:
        session.revoked_at = _now()
        db.flush()
        record_audit(
            db,
            action="auth.logout",
            actor_user_id=session.user_id,
            resource_type="auth_session",
            resource_id=str(session.id),
            request=request,
        )
    return OkResponse()


@router.get("/me", response_model=MeOut, summary="Current account and profile")
def me(user: CurrentUser, db: DbSession) -> MeOut:
    profile = db.execute(
        select(PatientProfile.id, PatientProfile.primary_language).where(
            PatientProfile.user_id == user.id
        )
    ).first()
    return MeOut(
        user=UserOut.model_validate(user),
        patient_profile_id=profile.id if profile is not None else None,
        primary_language=profile.primary_language if profile is not None else None,
    )


@router.post(
    "/password",
    response_model=OkResponse,
    summary="Change password and revoke all sessions",
)
def change_password(
    payload: PasswordChangeRequest, request: Request, user: CurrentUser, db: DbSession
) -> OkResponse:
    if not verify_password(payload.current_password, user.password_hash):
        record_audit(
            db,
            action="auth.password_change",
            actor_user_id=user.id,
            outcome=AuditOutcome.DENIED,
            request=request,
        )
        raise AuthenticationError("The current password is incorrect.")
    if payload.current_password == payload.new_password:
        raise ConflictError("The new password must differ from the current password.")

    user.password_hash = hash_password(payload.new_password)
    user.failed_login_attempts = 0
    user.locked_until = None
    db.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=_now())
    )
    db.flush()
    record_audit(
        db,
        action="auth.password_changed",
        actor_user_id=user.id,
        actor_role=str(user.role),
        resource_type="user",
        resource_id=str(user.id),
        request=request,
    )
    return OkResponse()

