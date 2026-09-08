import pytest

from nirikshan.core.errors import AuthError
from nirikshan.security.passwords import hash_password, verify_password
from nirikshan.security.tokens import (
    create_access_token,
    create_refresh_token,
    decode_token,
)

pytestmark = pytest.mark.unit


def test_password_hash_roundtrip():
    h = hash_password("s3cret-passw0rd")
    assert h != "s3cret-passw0rd"
    assert verify_password("s3cret-passw0rd", h)
    assert not verify_password("wrong", h)


def test_access_token_roundtrip(settings):
    tok, ttl = create_access_token(user_id="u1", email="a@b.dev", role="ADMIN")
    claims = decode_token(tok, expected_type="access")
    assert claims["sub"] == "u1" and claims["role"] == "ADMIN"
    assert ttl > 0


def test_wrong_token_type_rejected(settings):
    rt = create_refresh_token(user_id="u1")
    with pytest.raises(AuthError):
        decode_token(rt, expected_type="access")


def test_tampered_token_rejected(settings):
    tok, _ = create_access_token(user_id="u1", email="a@b.dev", role="VIEWER")
    with pytest.raises(AuthError):
        decode_token(tok + "x", expected_type="access")


def test_audit_scrubs_secrets(db):
    from nirikshan.security.audit import record

    row = record(db, actor="a@b.dev", action="test", after={"password": "hunter2", "ok": 1})
    assert row.after["password"] == "***"
    assert row.after["ok"] == 1
