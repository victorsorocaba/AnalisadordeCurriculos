"""Password accounts and opaque sessions for PostgreSQL-backed profiles."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from backend.storage import PROFILE_KEY, _connect, _database_url

router = APIRouter(prefix="/api/account", tags=["account"])
EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
SESSION_DAYS = 30


class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=10, max_length=128)


def _normal_email(value: str) -> str:
    email = value.lower()
    if not EMAIL.fullmatch(email):
        raise HTTPException(422, "Informe um e-mail válido.")
    return email


def _password_hash(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"scrypt$16384$8$1${salt.hex()}${digest.hex()}"


def _verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt, expected = encoded.split("$")
        if algorithm != "scrypt" or (int(n), int(r), int(p)) != (2**14, 8, 1):
            return False
        actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p))
        return hmac.compare_digest(actual, bytes.fromhex(expected))
    except (ValueError, TypeError):
        return False


def _create_session(conn, account_id) -> str:
    token = secrets.token_urlsafe(32)
    conn.execute(
        "INSERT INTO user_sessions (token_hash, account_id, expires_at) VALUES (%s, %s, %s)",
        (hashlib.sha256(token.encode()).hexdigest(), account_id,
         datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)),
    )
    return token


def session_owner(token: str | None) -> str:
    if not token or len(token) > 200:
        raise HTTPException(401, "Entre na sua conta para acessar este perfil.")
    with _connect() as conn:
        row = conn.execute(
            "SELECT a.owner_hash FROM user_sessions s JOIN user_accounts a ON a.id = s.account_id "
            "WHERE s.token_hash = %s AND s.expires_at > now()",
            (hashlib.sha256(token.encode()).hexdigest(),),
        ).fetchone()
    if not row:
        raise HTTPException(401, "Sua sessão expirou. Entre novamente.")
    return row[0].strip()


@router.post("/register", status_code=201)
def register(credentials: Credentials, x_profile_key: str | None = Header(default=None)) -> dict:
    if not _database_url():
        raise HTTPException(503, "Configure o PostgreSQL para criar uma conta.")
    if not x_profile_key or not PROFILE_KEY.fullmatch(x_profile_key):
        raise HTTPException(401, "Chave local do perfil ausente.")
    email = _normal_email(credentials.email)
    old_owner = hashlib.sha256(x_profile_key.encode("ascii")).hexdigest()
    account_id = uuid4()
    new_owner = hashlib.sha256(f"account:{account_id}".encode()).hexdigest()
    try:
        with _connect() as conn:
            conn.execute(
                "INSERT INTO user_accounts (id, email, password_hash, owner_hash) VALUES (%s, %s, %s, %s)",
                (account_id, email, _password_hash(credentials.password), new_owner),
            )
            for table in ("saved_versions", "roadmap_progress", "roadmap_topic_progress", "job_applications"):
                conn.execute(f"UPDATE {table} SET owner_hash = %s WHERE owner_hash = %s", (new_owner, old_owner))
            token = _create_session(conn, account_id)
    except Exception as exc:
        from psycopg.errors import UniqueViolation
        if isinstance(exc, UniqueViolation):
            raise HTTPException(409, "Já existe uma conta com este e-mail.") from exc
        raise
    return {"email": email, "sessionToken": token}


@router.post("/login")
def login(credentials: Credentials) -> dict:
    email = _normal_email(credentials.email)
    with _connect() as conn:
        row = conn.execute("SELECT id, password_hash FROM user_accounts WHERE email = %s", (email,)).fetchone()
        if not row or not _verify_password(credentials.password, row[1]):
            raise HTTPException(401, "E-mail ou senha inválidos.")
        token = _create_session(conn, row[0])
    return {"email": email, "sessionToken": token}


@router.get("/me")
def me(x_session_token: str | None = Header(default=None)) -> dict:
    owner = session_owner(x_session_token)
    with _connect() as conn:
        row = conn.execute("SELECT email FROM user_accounts WHERE owner_hash = %s", (owner,)).fetchone()
    return {"email": row[0]}


@router.post("/logout", status_code=204)
def logout(x_session_token: str | None = Header(default=None)) -> None:
    if x_session_token:
        with _connect() as conn:
            conn.execute("DELETE FROM user_sessions WHERE token_hash = %s", (hashlib.sha256(x_session_token.encode()).hexdigest(),))
