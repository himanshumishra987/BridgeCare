from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import EmailStr, Field, field_validator

from app.models.enums import SexAtBirth, UserRole
from app.schemas.common import ORMModel, StrictModel

PASSWORD_MIN_LENGTH = 10
PASSWORD_MAX_LENGTH = 128


class RegisterRequest(StrictModel):
    """Public self-registration. The role is always ``patient``.

    There is deliberately no ``role`` field: clinician and admin accounts are
    provisioned by an administrator, never self-assigned.
    """

    email: EmailStr
    password: str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)
    full_name: str = Field(min_length=1, max_length=200)
    date_of_birth: date | None = None
    sex_at_birth: SexAtBirth = SexAtBirth.UNKNOWN
    primary_language: str = Field(default="en", min_length=2, max_length=16)

    @field_validator("password")
    @classmethod
    def _password_strength(cls, value: str) -> str:
        if value.strip() != value:
            raise ValueError("Password must not begin or end with whitespace.")
        if value.lower() in {"password12", "1234567890", "bridgecare"}:
            raise ValueError("This password is too common.")
        if len(set(value)) < 4:
            raise ValueError("Password must use at least four distinct characters.")
        return value


class LoginRequest(StrictModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=PASSWORD_MAX_LENGTH)


class RefreshRequest(StrictModel):
    refresh_token: str = Field(min_length=16, max_length=4096)


class LogoutRequest(StrictModel):
    refresh_token: str = Field(min_length=16, max_length=4096)


class TokenPair(StrictModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class PasswordChangeRequest(StrictModel):
    current_password: str = Field(min_length=1, max_length=PASSWORD_MAX_LENGTH)
    new_password: str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)

    @field_validator("new_password")
    @classmethod
    def _password_strength(cls, value: str) -> str:
        if len(set(value)) < 4:
            raise ValueError("Password must use at least four distinct characters.")
        return value


class UserOut(ORMModel):
    id: uuid.UUID
    email: EmailStr
    full_name: str
    role: UserRole
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None = None


class MeOut(StrictModel):
    user: UserOut
    patient_profile_id: uuid.UUID | None = None
    #: Saved language preference, restored by the client on session reload.
    primary_language: str | None = None
