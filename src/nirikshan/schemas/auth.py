from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from nirikshan.domain.enums import Role


class LoginIn(BaseModel):
    # lenient on purpose: authenticate against whatever the account email is
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=1, max_length=200)


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshIn(BaseModel):
    refresh_token: str


class UserOut(BaseModel):
    id: str
    email: str
    full_name: str
    role: Role
    is_active: bool
    last_login_at: datetime | None


class UserCreateIn(BaseModel):
    email: EmailStr
    full_name: str = ""
    password: str = Field(min_length=8, max_length=200)
    role: Role = Role.VIEWER


class UserUpdateIn(BaseModel):
    full_name: str | None = None
    role: Role | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=200)
