from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from uuid import uuid4

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from kavach_saathi.config import Settings, get_settings
from kavach_saathi.db.base import get_session
from kavach_saathi.db.models import RefreshToken, SellerProfile, User

Role = Literal["buyer", "seller", "admin", "delivery_boy"]


class AuthError(HTTPException):
    def __init__(self, detail: str, status_code: int = status.HTTP_401_UNAUTHORIZED):
        super().__init__(status_code=status_code, detail=detail, headers={"WWW-Authenticate": "Bearer"})


def hash_password(raw: str) -> str:
    return bcrypt.hashpw(raw.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(raw: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(raw.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:10].upper()}"


def _encode_token(*, user_id: str, role: str, token_type: str, expires_delta: timedelta, settings: Settings) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": user_id,
        "role": role,
        "type": token_type,
        "iat": now,
        "exp": now + expires_delta,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(user: User, settings: Settings) -> str:
    return _encode_token(
        user_id=user.id,
        role=user.role,
        token_type="access",
        expires_delta=timedelta(minutes=settings.jwt_access_token_minutes),
        settings=settings,
    )


def create_refresh_token(user: User, session: Session, settings: Settings) -> str:
    raw = secrets.token_urlsafe(48)
    token_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    expires_at = datetime.now(UTC) + timedelta(days=settings.jwt_refresh_token_days)
    session.add(RefreshToken(user_id=user.id, token_hash=token_hash, expires_at=expires_at))
    session.flush()
    return raw


def decode_token(token: str, settings: Settings, *, expected_type: str = "access") -> dict:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.ExpiredSignatureError as exc:
        raise AuthError("Token has expired") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthError("Invalid token") from exc
    if payload.get("type") != expected_type:
        raise AuthError("Wrong token type")
    return payload


def rotate_refresh_token(raw_token: str, session: Session, settings: Settings) -> tuple[User, str, str]:
    """Verify + revoke the presented refresh token and issue a fresh access/refresh pair."""
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    record = (
        session.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash, RefreshToken.revoked.is_(False))
        )
        .scalars()
        .first()
    )
    if not record or record.expires_at < datetime.now(UTC):
        raise AuthError("Refresh token is invalid or expired")
    user = session.get(User, record.user_id)
    if not user:
        raise AuthError("User no longer exists")
    record.revoked = True
    session.flush()
    access = create_access_token(user, settings)
    refresh = create_refresh_token(user, session, settings)
    return user, access, refresh


def signup_user(
    *,
    role: Role,
    name: str,
    password: str,
    preferred_language: str,
    session: Session,
    email: str | None = None,
    phone: str | None = None,
    business_name: str | None = None,
) -> User:
    if not email and not phone:
        raise HTTPException(status_code=400, detail="email or phone is required")
    existing = None
    if email:
        existing = session.execute(select(User).where(User.email == email)).scalars().first()
    if not existing and phone:
        existing = session.execute(select(User).where(User.phone == phone)).scalars().first()
    if existing:
        raise HTTPException(status_code=409, detail="An account with this email or phone already exists")

    prefix = {"buyer": "B", "seller": "S", "admin": "A", "delivery_boy": "D"}[role]
    user = User(
        id=_new_id(prefix),
        role=role,
        name=name,
        email=email,
        phone=phone,
        password_hash=hash_password(password),
        preferred_language=preferred_language,
    )
    session.add(user)
    session.flush()

    if role == "seller":
        session.add(
            SellerProfile(
                user_id=user.id,
                business_name=business_name or name,
                digilocker_kyc_status="not_started",
            )
        )
        session.flush()
    return user


def authenticate_user(*, identifier: str, password: str, session: Session) -> User:
    user = (
        session.execute(select(User).where((User.email == identifier) | (User.phone == identifier))).scalars().first()
    )
    if not user or not verify_password(password, user.password_hash):
        raise AuthError("Invalid credentials")
    return user


def _extract_bearer_token(request: Request) -> str:
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        raise AuthError("Missing bearer token")
    return header.removeprefix("Bearer ").strip()


def get_current_user(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    session: Annotated[Session, Depends(get_session)],
) -> User:
    token = _extract_bearer_token(request)
    payload = decode_token(token, settings, expected_type="access")
    user = session.get(User, payload["sub"])
    if not user:
        raise AuthError("User no longer exists")
    return user


def require_role(*roles: Role):
    def _dependency(user: Annotated[User, Depends(get_current_user)]) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
        return user

    return _dependency
