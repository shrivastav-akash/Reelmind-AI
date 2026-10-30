"""Accounts for My Studio (v2 task 4.1). Standard library only (decision D2): SQLite + scrypt.

    signup(email, password, instagram_url) -> (UserPublic, token)
    login(email, password)                 -> (UserPublic, token)
    logout(token) / user_for_token(token)
    require_user                           FastAPI dependency: Authorization: Bearer <token> -> UserPublic

Storage: data/app.db (gitignored with the rest of data/). One connection per call, so FastAPI's
thread pool never shares one.
    users(id, email UNIQUE lowercase, pw_hash, pw_salt, ig_handle, latest_report_id, created_at)
    sessions(token_hash PRIMARY KEY, user_id, expires_at)

Security rules: passwords are scrypt-hashed with a per-user salt; session tokens are random
(secrets.token_urlsafe) and only their SHA-256 is stored, so a copied database can't log anyone
in; a wrong password and an unknown email get the same message after the same work; nothing
here logs a password, hash or token. No rate limiting (hackathon scope: noted in the plan).
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import Header, HTTPException

from backend import creator_profiler
from backend.config import settings
from backend.report_models import UserPublic

SESSION_DAYS = 7
MIN_PASSWORD, MAX_PASSWORD = 8, 256
SCRYPT = {"n": 2**14, "r": 8, "p": 1, "dklen": 32}  # ~25 ms per hash on the demo laptop
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")  # a sanity check, not RFC 5322
WRONG_LOGIN = "Email or password is wrong."
_DUMMY_SALT = bytes(16)  # login with an unknown email still pays for one hash

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    pw_hash TEXT NOT NULL,
    pw_salt TEXT NOT NULL,
    ig_handle TEXT NOT NULL,
    latest_report_id TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at TEXT NOT NULL
);
"""


class AuthError(Exception):
    """A message the UI shows as is, with the HTTP status main.py answers with."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _db_path() -> Path:
    return settings.data_dir / "app.db"


def _connect() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript(SCHEMA)
    return db


def _now() -> datetime:
    return datetime.now(timezone.utc)


def hash_password(password: str, salt: bytes) -> str:
    return hashlib.scrypt(password.encode(), salt=salt, **SCRYPT).hex()


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _public(row: sqlite3.Row) -> UserPublic:
    return UserPublic(id=row["id"], email=row["email"], ig_handle=row["ig_handle"],
                      profile_url=f"https://www.instagram.com/{row['ig_handle']}/",
                      created_at=datetime.fromisoformat(row["created_at"]), latest_report_id=row["latest_report_id"])


def _new_session(db: sqlite3.Connection, user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    db.execute("DELETE FROM sessions WHERE expires_at <= ?", (_now().isoformat(),))
    db.execute("INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
               (_token_hash(token), user_id, (_now() + timedelta(days=SESSION_DAYS)).isoformat()))
    return token


def _clean_email(email: str | None) -> str:
    email = (email or "").strip().lower()
    if not EMAIL_RE.match(email) or len(email) > 254:
        raise AuthError("Enter a valid email address.")
    return email


def signup(email: str, password: str, instagram_url: str) -> tuple[UserPublic, str]:
    email = _clean_email(email)
    if not MIN_PASSWORD <= len(password or "") <= MAX_PASSWORD:
        raise AuthError(f"Use a password of at least {MIN_PASSWORD} characters.")
    try:
        handle = creator_profiler.parse_handle(instagram_url)
    except creator_profiler.HandleRejected as exc:
        raise AuthError(f"Instagram profile: {exc}") from exc
    salt = secrets.token_bytes(16)
    pw_hash = hash_password(password, salt)
    with closing(_connect()) as db, db:
        try:
            cur = db.execute("INSERT INTO users (email, pw_hash, pw_salt, ig_handle, created_at) VALUES (?, ?, ?, ?, ?)",
                             (email, pw_hash, salt.hex(), handle, _now().isoformat()))
        except sqlite3.IntegrityError as exc:
            raise AuthError("An account with this email already exists. Log in instead.", 409) from exc
        token = _new_session(db, cur.lastrowid)
        row = db.execute("SELECT * FROM users WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _public(row), token


def login(email: str, password: str) -> tuple[UserPublic, str]:
    email = (email or "").strip().lower()
    with closing(_connect()) as db, db:
        row = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        salt = bytes.fromhex(row["pw_salt"]) if row else _DUMMY_SALT
        given = hash_password(password or "", salt)  # always hash, so both failures take as long
        if row is None or not hmac.compare_digest(given, row["pw_hash"]):
            raise AuthError(WRONG_LOGIN, 401)
        token = _new_session(db, row["id"])
    return _public(row), token


def user_for_token(token: str | None) -> UserPublic | None:
    if not token:
        return None
    with closing(_connect()) as db:
        row = db.execute(
            "SELECT users.* FROM sessions JOIN users ON users.id = sessions.user_id "
            "WHERE sessions.token_hash = ? AND sessions.expires_at > ?",
            (_token_hash(token), _now().isoformat()),
        ).fetchone()
    return _public(row) if row else None


def logout(token: str) -> None:
    with closing(_connect()) as db, db:
        db.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))


def set_latest_report(user_id: int, report_id: str) -> None:
    """4.3: the user's own report, shown on My Studio."""
    with closing(_connect()) as db, db:
        db.execute("UPDATE users SET latest_report_id = ? WHERE id = ?", (report_id, user_id))


def bearer_token(authorization: str | None) -> str | None:
    scheme, _, token = (authorization or "").strip().partition(" ")
    if scheme.lower() != "bearer":
        return None
    return token.strip() or None


def require_user(authorization: str | None = Header(None)) -> UserPublic:
    """FastAPI dependency for routes that need a signed-in user."""
    user = user_for_token(bearer_token(authorization))
    if user is None:
        raise HTTPException(401, "Log in to continue.", headers={"WWW-Authenticate": "Bearer"})
    return user
