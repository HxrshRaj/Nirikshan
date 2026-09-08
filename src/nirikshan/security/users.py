"""User lookup / creation and the login flow."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from nirikshan.core.clock import utcnow
from nirikshan.core.config import get_settings
from nirikshan.core.errors import AuthError, ConflictError, NotFoundError
from nirikshan.core.logging import get_logger
from nirikshan.domain.enums import Role
from nirikshan.models import User
from nirikshan.security.passwords import hash_password, verify_password

log = get_logger("security.users")


def get_user(db: Session, user_id: str) -> User:
    u = db.get(User, user_id)
    if u is None:
        raise NotFoundError("user not found")
    return u


def get_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == email.lower().strip()))


def create_user(
    db: Session, *, email: str, password: str, full_name: str = "", role: Role = Role.VIEWER
) -> User:
    email = email.lower().strip()
    if get_by_email(db, email):
        raise ConflictError(f"user {email} already exists")
    u = User(
        email=email,
        full_name=full_name,
        password_hash=hash_password(password),
        role=role.value,
    )
    db.add(u)
    db.flush()
    log.info("user.created", email=email, role=role.value)
    return u


def authenticate(db: Session, *, email: str, password: str) -> User:
    u = get_by_email(db, email)
    if u is None or not u.is_active or not verify_password(password, u.password_hash):
        raise AuthError("invalid email or password")
    u.last_login_at = utcnow()
    db.add(u)
    db.flush()
    return u


def ensure_bootstrap_admin(db: Session) -> User | None:
    s = get_settings()
    if not s.bootstrap_admin_email or not s.bootstrap_admin_password:
        return None
    existing = get_by_email(db, s.bootstrap_admin_email)
    if existing:
        return existing
    if db.scalar(select(User).limit(1)):
        return None  # users already exist; don't auto-create
    return create_user(
        db,
        email=s.bootstrap_admin_email,
        password=s.bootstrap_admin_password,
        full_name="Bootstrap Admin",
        role=Role.ADMIN,
    )


def seed_demo_users(db: Session) -> list[User]:
    """Idempotently create one user per role for demos (password = <role>12345)."""
    out = []
    for role in Role:
        email = f"{role.value.lower()}@nirikshan.dev"
        if not get_by_email(db, email):
            out.append(
                create_user(
                    db, email=email, password=f"{role.value.lower()}12345",
                    full_name=f"Demo {role.value.title()}", role=role,
                )
            )
    return out
