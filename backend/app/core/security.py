# Password hashing, JWT handling, and encryption helpers.
from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta

from cryptography.fernet import Fernet
from jose import jwt
from passlib.hash import pbkdf2_sha256

from app.core.config import settings

def hash_password(password: str) -> str:
    return pbkdf2_sha256.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    try:
        return pbkdf2_sha256.verify(password, hashed_password)
    except (TypeError, ValueError):
        return False


def create_access_token(subject: str) -> str:
    expires_at = datetime.now(UTC) + timedelta(hours=settings.jwt_expire_hours)
    payload = {"sub": subject, "exp": expires_at}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, str]:
    return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])


def _fernet() -> Fernet:
    key = settings.encryption_key.encode("utf-8")
    padded = base64.urlsafe_b64encode(key.ljust(32, b"0")[:32])
    return Fernet(padded)


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_secret(value: str) -> str:
    return _fernet().decrypt(value.encode("utf-8")).decode("utf-8")
