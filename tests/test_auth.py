"""Defines "done" for auth.py + the /auth and /me routes (v2 task 4.1).

Real SQLite in a temp folder and real scrypt (~25 ms a hash), driven the way the UI will:
sign up with an Instagram link, keep the token, send it as a Bearer header.
"""

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from backend import auth

PASSWORD = "correct horse battery"


@pytest.fixture
def env(isolated, monkeypatch):
    monkeypatch.setattr(auth, "settings", isolated, raising=False)
    return isolated


@pytest.fixture
def client(env):
    from backend.main import app

    return TestClient(app)


def signup(client, email="Cook@Example.com", password=PASSWORD, instagram_url="https://www.instagram.com/eylems_kitchen/"):
    return client.post("/auth/signup", json={"email": email, "password": password, "instagram_url": instagram_url})


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def raw_db(env):
    return (env.data_dir / "app.db").read_bytes()


# ---------------------------------------------------------------- sign up


def test_signup_returns_a_session_and_the_public_user(client):
    r = signup(client)
    assert r.status_code == 201
    body = r.json()
    assert set(body) == {"token", "user"} and len(body["token"]) >= 40
    user = body["user"]
    assert user["email"] == "cook@example.com"  # stored lowercase
    assert user["ig_handle"] == "eylems_kitchen" and user["profile_url"] == "https://www.instagram.com/eylems_kitchen/"
    assert user["latest_report_id"] is None
    assert not {"password", "pw_hash", "pw_salt"} & set(user)


@pytest.mark.parametrize("instagram_url, handle", [("@eylems_kitchen", "eylems_kitchen"), ("instagram.com/pov__gil", "pov__gil")])
def test_signup_takes_a_handle_or_a_link(client, instagram_url, handle):
    assert signup(client, instagram_url=instagram_url).json()["user"]["ig_handle"] == handle


def test_duplicate_email_is_409_whatever_the_case(client):
    assert signup(client).status_code == 201
    r = signup(client, email="  COOK@example.COM ")
    assert r.status_code == 409 and "already exists" in r.json()["detail"]


@pytest.mark.parametrize(
    "fields, message",
    [
        ({"email": "not-an-email"}, "valid email"),
        ({"email": ""}, "valid email"),
        ({"password": "short"}, "at least 8"),
        ({"password": "x" * 300}, "at least 8"),
        ({"instagram_url": "https://www.tiktok.com/@someone"}, "Instagram profile"),
        ({"instagram_url": ""}, "Instagram profile"),
    ],
)
def test_signup_rejects_bad_fields_with_the_reason(client, fields, message):
    r = signup(client, **fields)
    assert r.status_code == 400 and message in r.json()["detail"]


def test_signup_needs_every_field(client):
    assert client.post("/auth/signup", json={"email": "a@b.co"}).status_code == 422


# ---------------------------------------------------------------- log in / out


def test_login_with_the_right_password(client):
    signup(client)
    r = client.post("/auth/login", json={"email": "COOK@example.com", "password": PASSWORD})
    assert r.status_code == 200 and r.json()["user"]["ig_handle"] == "eylems_kitchen"


def test_wrong_password_and_unknown_email_look_the_same(client):
    signup(client)
    wrong = client.post("/auth/login", json={"email": "cook@example.com", "password": "nope nope nope"})
    unknown = client.post("/auth/login", json={"email": "nobody@example.com", "password": PASSWORD})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json() == {"detail": auth.WRONG_LOGIN}


def test_each_login_is_its_own_session(client):
    first = signup(client).json()["token"]
    second = client.post("/auth/login", json={"email": "cook@example.com", "password": PASSWORD}).json()["token"]
    assert first != second
    assert client.get("/me", headers=bearer(first)).status_code == 200
    assert client.get("/me", headers=bearer(second)).status_code == 200


def test_logout_ends_only_that_session(client):
    first = signup(client).json()["token"]
    second = client.post("/auth/login", json={"email": "cook@example.com", "password": PASSWORD}).json()["token"]
    assert client.post("/auth/logout", headers=bearer(first)).status_code == 204
    assert client.get("/me", headers=bearer(first)).status_code == 401
    assert client.get("/me", headers=bearer(second)).status_code == 200


def test_logout_needs_a_session(client):
    assert client.post("/auth/logout").status_code == 401


# ---------------------------------------------------------------- /me and tokens


def test_me_with_a_token(client):
    token = signup(client).json()["token"]
    r = client.get("/me", headers=bearer(token))
    assert r.status_code == 200 and r.json()["email"] == "cook@example.com"


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": ""}, {"Authorization": "Bearer"}, {"Authorization": "Bearer not-a-real-token"},
     {"Authorization": "Basic Y29vazpwYXNz"}],
)
def test_me_without_a_valid_token_is_401(client, headers):
    signup(client)
    r = client.get("/me", headers=headers)
    assert r.status_code == 401 and r.json()["detail"] == "Log in to continue."
    assert r.headers["www-authenticate"] == "Bearer"


def test_a_basic_header_is_not_mistaken_for_a_token(client):
    token = signup(client).json()["token"]
    assert client.get("/me", headers={"Authorization": f"Basic {token}"}).status_code == 401


def test_expired_session_is_401(client, env):
    token = signup(client).json()["token"]
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    with sqlite3.connect(env.data_dir / "app.db") as db:
        db.execute("UPDATE sessions SET expires_at = ?", (past,))
    assert client.get("/me", headers=bearer(token)).status_code == 401


def test_sessions_last_seven_days(client, env):
    signup(client)
    with sqlite3.connect(env.data_dir / "app.db") as db:
        (expires,) = db.execute("SELECT expires_at FROM sessions").fetchone()
    left = datetime.fromisoformat(expires) - datetime.now(timezone.utc)
    assert timedelta(days=6, hours=23) < left <= timedelta(days=7)


# ---------------------------------------------------------------- what's stored


def test_database_never_holds_the_password_or_the_token(client, env):
    token = signup(client).json()["token"]
    data = raw_db(env)
    assert PASSWORD.encode() not in data and token.encode() not in data
    with sqlite3.connect(env.data_dir / "app.db") as db:
        pw_hash, salt = db.execute("SELECT pw_hash, pw_salt FROM users").fetchone()
    assert len(bytes.fromhex(salt)) == 16 and pw_hash == auth.hash_password(PASSWORD, bytes.fromhex(salt))


def test_same_password_different_salt_different_hash():
    assert auth.hash_password(PASSWORD, b"a" * 16) != auth.hash_password(PASSWORD, b"b" * 16)


def test_set_latest_report_shows_on_me(client, env):
    body = signup(client).json()
    auth.set_latest_report(body["user"]["id"], "abcdefabcdef")
    assert client.get("/me", headers=bearer(body["token"])).json()["latest_report_id"] == "abcdefabcdef"
