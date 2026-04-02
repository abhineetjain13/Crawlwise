# Tests for password hashing helpers.
from __future__ import annotations

from app.core.security import hash_password, verify_password


def test_hash_password_uses_non_plaintext_hash():
    hashed = hash_password("password123")
    assert hashed != "password123"
    assert hashed.startswith("$pbkdf2-sha256$")


def test_verify_password_accepts_valid_password():
    hashed = hash_password("password123")
    assert verify_password("password123", hashed) is True
    assert verify_password("wrong-password", hashed) is False
