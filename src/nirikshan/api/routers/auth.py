from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from nirikshan.api.deps import client_ip, current_user, get_db, rate_limit, require_role
from nirikshan.core.errors import NotFoundError
from nirikshan.domain.enums import Role
from nirikshan.models import User
from nirikshan.schemas.auth import (
    LoginIn,
    RefreshIn,
    TokenPair,
    UserCreateIn,
    UserOut,
    UserUpdateIn,
)
from nirikshan.schemas.common import OkResponse
from nirikshan.security import audit, users
from nirikshan.security.passwords import hash_password
from nirikshan.security.tokens import create_access_token, create_refresh_token, decode_token

router = APIRouter(tags=["auth"])


def _tokens(user: User) -> TokenPair:
    access, ttl = create_access_token(user_id=user.id, email=user.email, role=user.role)
    return TokenPair(access_token=access, refresh_token=create_refresh_token(user_id=user.id), expires_in=ttl)


@router.post("/auth/login", response_model=TokenPair, dependencies=[Depends(rate_limit("default"))])
def login(payload: LoginIn, request: Request, db: Session = Depends(get_db)) -> TokenPair:
    try:
        user = users.authenticate(db, email=payload.email, password=payload.password)
    except Exception:
        audit.record(db, actor=payload.email, action="login", resource_type="user",
                     result="failure", ip=client_ip(request))
        raise
    audit.record(db, actor=user.email, actor_role=user.role, action="login", resource_type="user",
                 resource_id=user.id, ip=client_ip(request))
    return _tokens(user)


@router.post("/auth/refresh", response_model=TokenPair)
def refresh(payload: RefreshIn, db: Session = Depends(get_db)) -> TokenPair:
    claims = decode_token(payload.refresh_token, expected_type="refresh")
    user = users.get_user(db, claims["sub"])
    return _tokens(user)


@router.post("/auth/logout", response_model=OkResponse)
def logout(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)) -> OkResponse:
    # Stateless JWT: logout is client-side token disposal. We record the intent.
    audit.record(db, actor=user.email, actor_role=user.role, action="logout",
                 resource_type="user", resource_id=user.id, ip=client_ip(request))
    return OkResponse(detail="logged out")


@router.get("/auth/me", response_model=UserOut)
def me(user: User = Depends(current_user)) -> UserOut:
    return UserOut.model_validate(user, from_attributes=True)


# ---- user administration (ADMIN only) ----
@router.get("/users", response_model=list[UserOut], dependencies=[Depends(require_role(Role.ADMIN))])
def list_users(db: Session = Depends(get_db)) -> list[UserOut]:
    return [UserOut.model_validate(u, from_attributes=True) for u in db.scalars(select(User).order_by(User.email))]


@router.post("/users", response_model=UserOut, status_code=201, dependencies=[Depends(require_role(Role.ADMIN))])
def create_user(payload: UserCreateIn, request: Request, db: Session = Depends(get_db),
                actor: User = Depends(require_role(Role.ADMIN))) -> UserOut:
    u = users.create_user(db, email=payload.email, password=payload.password,
                          full_name=payload.full_name, role=payload.role)
    audit.record(db, actor=actor.email, actor_role=actor.role, action="user.create",
                 resource_type="user", resource_id=u.id, after={"email": u.email, "role": u.role},
                 ip=client_ip(request))
    return UserOut.model_validate(u, from_attributes=True)


@router.patch("/users/{user_id}", response_model=UserOut, dependencies=[Depends(require_role(Role.ADMIN))])
def update_user(user_id: str, payload: UserUpdateIn, request: Request, db: Session = Depends(get_db),
                actor: User = Depends(require_role(Role.ADMIN))) -> UserOut:
    u = db.get(User, user_id)
    if u is None:
        raise NotFoundError("user not found")
    before = {"role": u.role, "is_active": u.is_active, "full_name": u.full_name}
    if payload.full_name is not None:
        u.full_name = payload.full_name
    if payload.role is not None:
        u.role = payload.role.value
    if payload.is_active is not None:
        u.is_active = payload.is_active
    if payload.password:
        u.password_hash = hash_password(payload.password)
    db.add(u)
    audit.record(db, actor=actor.email, actor_role=actor.role, action="user.update",
                 resource_type="user", resource_id=u.id, before=before,
                 after={"role": u.role, "is_active": u.is_active}, ip=client_ip(request))
    return UserOut.model_validate(u, from_attributes=True)
