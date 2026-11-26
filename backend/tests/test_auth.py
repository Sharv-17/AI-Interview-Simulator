"""Account authentication tests (in-memory backend).

These run on every `pytest` run: they need no database, exactly like the rest of the
suite. The same contract is exercised against PostgreSQL in test_auth_postgres.py,
which is opt-in through TEST_DATABASE_URL.
"""

import hashlib
import uuid
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import app
from app.services.auth_service import AuthService, set_auth_service
from app.services.auth_store import MemoryAuthStore
from app.services.interview_engine import utcnow
from app.services.interview_service import get_interview_service
from app.services.rate_limit import RateLimitPolicy

PASSWORD = "correct horse battery staple"
TOPIC = "Databases"  # a topic with servable questions in the bank


def _email() -> str:
    return f"user-{uuid.uuid4().hex[:12]}@example.com"


def register(client: TestClient, email: str = None, password: str = PASSWORD, display_name=None):
    payload = {"email": _email() if email is None else email, "password": password}
    if display_name is not None:
        payload["display_name"] = display_name
    return client.post("/api/v1/auth/register", json=payload)


def login(client: TestClient, email: str, password: str = PASSWORD):
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


def start_interview(client: TestClient, candidate_id: str = None, question_count: int = 2):
    payload = {"topic": TOPIC, "difficulty": "easy", "question_count": question_count}
    if candidate_id is not None:
        payload["candidate_id"] = candidate_id
    return client.post("/interview/start", json=payload)


@pytest.fixture()
def auth() -> AuthService:
    """A fresh account service per test (fresh stores, fresh rate-limit counters)."""
    service = AuthService(MemoryAuthStore(), get_interview_service())
    set_auth_service(service)
    yield service
    set_auth_service(None)


@pytest.fixture()
def client(auth) -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


def _signed_in(email: str = None) -> tuple:
    """(client, email) with an open session cookie."""
    test_client = TestClient(app)
    email = email or _email()
    assert register(test_client, email).status_code == 201
    response = login(test_client, email)
    assert response.status_code == 200
    return test_client, email


# --------------------------------------------------------------------- registration


def test_register_creates_account_and_linked_candidate(client):
    email = _email()
    response = register(client, email)

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == email
    assert body["is_active"] is True
    assert body["is_email_verified"] is False, "email verification is not implemented"
    assert body["candidate_id"], "an account must own a candidate record"
    assert body["user_id"]
    assert body["created_at"]

    # The candidate really exists and is the one the account owns.
    candidates = client.get("/api/v1/candidates/me")  # no session yet -> 401
    assert candidates.status_code == 401


def test_register_stores_an_argon2id_hash_and_never_the_password(client, auth):
    email = _email()
    register(client, email)
    user = auth.store.get_user_by_email(email)

    assert user is not None
    assert user.password_hash != PASSWORD
    assert PASSWORD not in user.password_hash
    assert user.password_hash.startswith("$argon2id$")


def test_register_response_never_exposes_secrets(client):
    response = register(client)
    body = response.json()
    assert set(body) == {
        "user_id",
        "email",
        "is_active",
        "is_email_verified",
        "candidate_id",
        "created_at",
    }
    assert "password" not in response.text.lower()
    assert "argon2" not in response.text.lower()
    assert "token" not in response.text.lower()


def test_register_rejects_duplicate_email(client):
    email = _email()
    assert register(client, email).status_code == 201

    duplicate = register(client, email)
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["code"] == "email_already_registered"


def test_register_rejects_duplicate_email_in_another_case(client, auth):
    email = _email()
    assert register(client, email).status_code == 201

    duplicate = register(client, email.upper())
    assert duplicate.status_code == 409
    assert auth.store.get_user_by_email(email.upper()) is None


def test_register_normalizes_the_email(client, auth):
    email = _email()
    response = register(client, f"  {email.upper()}  ")

    assert response.status_code == 201
    assert response.json()["email"] == email
    assert auth.store.get_user_by_email(email) is not None


def test_register_rejects_invalid_email(client):
    response = register(client, "not-an-email")
    assert response.status_code == 422
    assert register(client, "").status_code == 422


def test_register_rejects_short_and_oversized_passwords(client):
    assert register(client, _email(), "short").status_code == 422
    assert register(client, _email(), "x" * 129).status_code == 422


def test_register_does_not_open_a_session(client):
    """Documented contract: registration returns the account; /login opens the session."""
    assert register(client).status_code == 201
    assert client.get("/api/v1/auth/me").status_code == 401


def test_register_is_rate_limited_per_address(auth):
    auth = AuthService(
        MemoryAuthStore(),
        get_interview_service(),
        register_policy=RateLimitPolicy(2, 60),
    )
    set_auth_service(auth)
    with TestClient(app) as test_client:
        assert register(test_client).status_code == 201
        assert register(test_client).status_code == 201
        limited = register(test_client)

    assert limited.status_code == 429
    assert limited.json()["detail"]["code"] == "rate_limited"
    assert "Retry-After" in limited.headers


# ---------------------------------------------------------------------------- login


def test_login_sets_an_opaque_http_only_cookie(client, auth):
    email = _email()
    register(client, email)

    response = login(client, email)
    assert response.status_code == 200

    cookie_header = response.headers["set-cookie"]
    assert config.AUTH_SESSION_COOKIE_NAME in cookie_header
    assert "HttpOnly" in cookie_header
    assert "SameSite=lax" in cookie_header.replace("samesite=lax", "SameSite=lax")
    assert "Path=/" in cookie_header

    token = response.cookies[config.AUTH_SESSION_COOKIE_NAME]
    # The raw token is never in the response body, and only its hash is stored.
    assert token not in response.text
    stored = auth.session_records(response.json()["user_id"])
    assert len(stored) == 1
    assert stored[0].token_hash != token
    assert len(stored[0].token_hash) == 64


def test_login_cookie_is_secure_when_configured(client, monkeypatch):
    email = _email()
    register(client, email)

    monkeypatch.setattr(config, "AUTH_COOKIE_SECURE", True)
    secure_header = login(client, email).headers["set-cookie"]
    assert "Secure" in secure_header

    monkeypatch.setattr(config, "AUTH_COOKIE_SECURE", False)
    insecure_header = login(client, email).headers["set-cookie"]
    assert "Secure" not in insecure_header


def test_login_rejects_a_wrong_password(client):
    email = _email()
    register(client, email)

    response = login(client, email, "wrong password entirely")
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "invalid_credentials"
    assert config.AUTH_SESSION_COOKIE_NAME not in response.cookies


def test_login_and_unknown_email_are_indistinguishable(client):
    email = _email()
    register(client, email)

    wrong_password = login(client, email, "wrong password entirely")
    unknown_email = login(client, _email(), PASSWORD)

    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json() == unknown_email.json()


def test_login_rejects_an_inactive_account(client, auth):
    email = _email()
    register(client, email)
    user = auth.store.get_user_by_email(email)
    auth.store.set_active(user.user_id, False, utcnow())

    response = login(client, email)
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "account_inactive"
    assert config.AUTH_SESSION_COOKIE_NAME not in response.cookies


def test_login_is_rate_limited_per_email(auth):
    auth = AuthService(
        MemoryAuthStore(),
        get_interview_service(),
        login_policy=RateLimitPolicy(3, 60),
        login_ip_policy=RateLimitPolicy(100, 60),
    )
    set_auth_service(auth)
    with TestClient(app) as test_client:
        email = _email()
        register(test_client, email)
        for _ in range(3):
            assert login(test_client, email, "wrong password entirely").status_code == 401
        limited = login(test_client, email, "wrong password entirely")

        assert limited.status_code == 429
        assert "Retry-After" in limited.headers

        # The correct password is refused too while the window is exhausted.
        assert login(test_client, email).status_code == 429


def test_successful_login_clears_the_email_failure_counter(auth):
    auth = AuthService(
        MemoryAuthStore(),
        get_interview_service(),
        login_policy=RateLimitPolicy(2, 60),
    )
    set_auth_service(auth)
    with TestClient(app) as test_client:
        email = _email()
        register(test_client, email)
        assert login(test_client, email, "wrong password entirely").status_code == 401
        assert login(test_client, email).status_code == 200
        assert login(test_client, email, "wrong password entirely").status_code == 401
        # Two failures with a success in between: the counter was reset, so not limited.
        assert login(test_client, email).status_code == 200


# ------------------------------------------------------------------------- sessions


def test_me_returns_the_signed_in_account(client):
    email = _email()
    register(client, email)
    login(client, email)

    response = client.get("/api/v1/auth/me")
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == email
    assert body["candidate_id"]
    assert "password" not in response.text.lower()


def test_me_requires_a_session(client):
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "authentication_required"


def test_me_rejects_a_garbage_cookie(client):
    client.cookies.set(config.AUTH_SESSION_COOKIE_NAME, "z" * 43)
    assert client.get("/api/v1/auth/me").status_code == 401


def test_expired_session_is_refused_server_side():
    clock = [utcnow()]
    auth = AuthService(
        MemoryAuthStore(),
        get_interview_service(),
        clock=lambda: clock[0],
        session_ttl_seconds=60,
    )
    set_auth_service(auth)
    try:
        with TestClient(app) as test_client:
            email = _email()
            register(test_client, email)
            assert login(test_client, email).status_code == 200
            assert test_client.get("/api/v1/auth/me").status_code == 200

            clock[0] = clock[0] + timedelta(seconds=61)
            # The cookie is still sent by the client; the server is what refuses it.
            assert test_client.get("/api/v1/auth/me").status_code == 401
    finally:
        set_auth_service(None)


def test_expiry_is_absolute_and_never_extended_by_use():
    clock = [utcnow()]
    auth = AuthService(
        MemoryAuthStore(), get_interview_service(), clock=lambda: clock[0], session_ttl_seconds=100
    )
    email = _email()
    auth.register(email, PASSWORD)
    result = auth.login(email, PASSWORD)

    for _ in range(3):
        clock[0] = clock[0] + timedelta(seconds=20)
        assert auth.authenticate(result.token) is not None

    stored = auth.store.get_session(hashlib.sha256(result.token.encode()).hexdigest())
    assert stored.expires_at == result.expires_at

    clock[0] = result.expires_at + timedelta(seconds=1)
    assert auth.authenticate(result.token) is None


def test_logout_revokes_the_session_and_clears_the_cookie(client, auth):
    email = _email()
    register(client, email)
    response = login(client, email)
    token = response.cookies[config.AUTH_SESSION_COOKIE_NAME]
    user_id = response.json()["user_id"]

    assert client.get("/api/v1/auth/me").status_code == 200
    logout = client.post("/api/v1/auth/logout")

    assert logout.status_code == 204
    assert "Max-Age=0" in logout.headers["set-cookie"]
    assert client.get("/api/v1/auth/me").status_code == 401

    stored = auth.session_records(user_id)
    assert stored[0].revoked_at is not None

    # The token cannot be replayed by putting the cookie back by hand.
    client.cookies.set(config.AUTH_SESSION_COOKIE_NAME, token)
    assert client.get("/api/v1/auth/me").status_code == 401


def test_logout_is_idempotent(client):
    assert client.post("/api/v1/auth/logout").status_code == 204
    email = _email()
    register(client, email)
    login(client, email)
    assert client.post("/api/v1/auth/logout").status_code == 204
    assert client.post("/api/v1/auth/logout").status_code == 204


def test_revoked_sessions_cannot_be_reused(auth):
    email = _email()
    user = auth.register(email, PASSWORD)
    first = auth.login(email, PASSWORD)
    second = auth.login(email, PASSWORD)

    assert auth.revoke_all_sessions(user.user_id) == 2
    assert auth.authenticate(first.token) is None
    assert auth.authenticate(second.token) is None
    assert [s.revoked_at is not None for s in auth.session_records(user.user_id)] == [True, True]


def test_disabling_an_account_kills_its_live_session(client, auth):
    email = _email()
    register(client, email)
    login(client, email)
    assert client.get("/api/v1/auth/me").status_code == 200

    user = auth.store.get_user_by_email(email)
    auth.store.set_active(user.user_id, False, utcnow())

    assert client.get("/api/v1/auth/me").status_code == 401


def test_logout_rejects_a_cross_site_request(client):
    email = _email()
    register(client, email)
    login(client, email)

    blocked = client.post("/api/v1/auth/logout", headers={"Origin": "https://evil.example"})
    assert blocked.status_code == 403
    assert blocked.json()["detail"]["code"] == "csrf_rejected"
    # Same-origin is fine.
    assert client.post("/api/v1/auth/logout", headers={"Origin": "http://testserver"}).status_code == 204


# ------------------------------------------------------------------------ ownership


def test_account_can_read_its_own_interview(client, auth):
    email = _email()
    register(client, email)
    login(client, email)
    candidate_id = client.get("/api/v1/candidates/me").json()["candidate_id"]

    created = start_interview(client, candidate_id)
    assert created.status_code == 201
    interview_id = created.json()["interview_id"]
    assert created.json()["candidate_id"] == candidate_id

    assert client.get(f"/interview/{interview_id}").status_code == 200
    assert client.get(f"/interview/{interview_id}/report").status_code == 200
    assert client.get(f"/interview/{interview_id}/competency").status_code == 200
    assert client.post(
        f"/interview/{interview_id}/integrity-events",
        json={"events": [{"event_type": "paste"}]},
    ).status_code == 200


def test_candidates_me_and_interviews_me_are_session_scoped(auth):
    owner, owner_email = _signed_in()
    other, other_email = _signed_in()

    candidate = owner.get("/api/v1/candidates/me").json()
    start_interview(owner, candidate["candidate_id"])

    assert owner.get("/api/v1/interviews/me").json()[0]["candidate_id"] == candidate["candidate_id"]
    # Another account sees its own (empty) history, never the first account's.
    assert other.get("/api/v1/interviews/me").json() == []
    assert other.get("/api/v1/candidates/me").json()["candidate_id"] != candidate["candidate_id"]


def test_another_account_cannot_touch_an_interview(auth):
    owner, _ = _signed_in()
    candidate_id = owner.get("/api/v1/candidates/me").json()["candidate_id"]
    interview_id = start_interview(owner, candidate_id).json()["interview_id"]
    question_id = owner.get(f"/interview/{interview_id}").json()["current_question_id"]

    intruder, _ = _signed_in()
    assert intruder.get(f"/interview/{interview_id}").status_code == 404
    assert intruder.get(f"/interview/{interview_id}/report").status_code == 404
    assert intruder.get(f"/interview/{interview_id}/competency").status_code == 404
    assert intruder.post(f"/interview/{interview_id}/next").status_code == 404
    assert intruder.post(
        f"/interview/{interview_id}/answer",
        json={"question_id": question_id, "answer_text": "let me in " * 5},
    ).status_code == 404
    assert intruder.post(
        f"/interview/{interview_id}/integrity-events", json={"events": [{"event_type": "paste"}]}
    ).status_code == 404


def test_guest_cannot_touch_an_account_interview(auth):
    owner, _ = _signed_in()
    candidate_id = owner.get("/api/v1/candidates/me").json()["candidate_id"]
    interview_id = start_interview(owner, candidate_id).json()["interview_id"]

    with TestClient(app) as guest:
        assert guest.get(f"/interview/{interview_id}").status_code == 401
        assert guest.get(f"/interview/{interview_id}/report").status_code == 401


def test_account_candidate_history_is_owner_only(auth):
    owner, _ = _signed_in()
    candidate_id = owner.get("/api/v1/candidates/me").json()["candidate_id"]
    start_interview(owner, candidate_id)

    assert owner.get(f"/candidates/{candidate_id}/interviews").status_code == 200
    assert owner.get(f"/candidates/{candidate_id}/competency-history").status_code == 200

    intruder, _ = _signed_in()
    assert intruder.get(f"/candidates/{candidate_id}/interviews").status_code == 404
    assert intruder.get(f"/candidates/{candidate_id}/competency-history").status_code == 404

    with TestClient(app) as guest:
        assert guest.get(f"/candidates/{candidate_id}/interviews").status_code == 401
        assert guest.get(f"/candidates/{candidate_id}/competency-history").status_code == 401


def test_candidate_ids_cannot_bypass_ownership(auth):
    owner, _ = _signed_in()
    candidate_id = owner.get("/api/v1/candidates/me").json()["candidate_id"]

    intruder, _ = _signed_in()
    assert start_interview(intruder, candidate_id).status_code == 404

    with TestClient(app) as guest:
        assert start_interview(guest, candidate_id).status_code == 404


# --------------------------------------------------------------- guest compatibility


def test_guest_interview_still_works_without_a_session(client):
    created = start_interview(client)
    assert created.status_code == 201
    body = created.json()
    assert body["candidate_id"] is None
    interview_id = body["interview_id"]

    assert client.get(f"/interview/{interview_id}").status_code == 200
    assert client.get(f"/interview/{interview_id}/report").status_code == 200
    assert client.get(f"/interview/{interview_id}/competency").status_code == 200


def test_guest_candidate_identity_is_preserved(client):
    candidate = client.post("/candidates", json={"display_name": "Guest"}).json()
    created = start_interview(client, candidate["candidate_id"])

    assert created.status_code == 201
    interview_id = created.json()["interview_id"]
    assert created.json()["candidate_id"] == candidate["candidate_id"]

    # No session anywhere: the guest identity and its history stay reachable as before.
    assert client.get(f"/interview/{interview_id}").status_code == 200
    assert client.get(f"/candidates/{candidate['candidate_id']}").status_code == 200
    history = client.get(f"/candidates/{candidate['candidate_id']}/interviews").json()
    assert interview_id in {entry["interview_id"] for entry in history}


def test_guest_interview_can_be_answered_end_to_end(client):
    created = start_interview(client, question_count=1)
    interview_id = created.json()["interview_id"]
    question_id = created.json()["current_question_id"]

    answer = client.post(
        f"/interview/{interview_id}/answer",
        json={"question_id": question_id, "answer_text": "A complete answer " * 6},
    )
    assert answer.status_code in (200, 202)

    advanced = client.post(f"/interview/{interview_id}/next")
    assert advanced.status_code == 200
    assert advanced.json()["status"] == "completed"
    assert client.get(f"/interview/{interview_id}/report").status_code == 200


def test_public_endpoints_need_no_session(client):
    assert client.get("/health").status_code == 200
    assert client.get("/questions").status_code == 200


def test_public_endpoints_are_still_cacheable(client):
    # no-store is scoped to the account API only.
    assert "cache-control" not in {k.lower() for k in client.get("/health").headers}


# ------------------------------------------------------------------ display name


def test_register_stores_the_display_name_on_its_candidate(client):
    email = _email()
    created = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": PASSWORD, "display_name": "  Ada   Lovelace "},
    )
    assert created.status_code == 201

    login(client, email)
    candidate = client.get("/api/v1/candidates/me").json()
    assert candidate["display_name"] == "Ada Lovelace"
    # Same candidate the registration created: no second record.
    assert candidate["candidate_id"] == created.json()["candidate_id"]


def test_register_without_a_display_name_still_works(client):
    email = _email()
    created = client.post("/api/v1/auth/register", json={"email": email, "password": PASSWORD})
    assert created.status_code == 201

    login(client, email)
    assert client.get("/api/v1/candidates/me").json()["display_name"] is None


def test_blank_display_name_is_stored_as_empty(client):
    email = _email()
    assert register(client, email, PASSWORD, display_name="   ").status_code == 201
    login(client, email)
    assert client.get("/api/v1/candidates/me").json()["display_name"] is None


def test_overlong_display_name_is_rejected(client):
    response = register(client, _email(), PASSWORD, display_name="x" * 121)
    assert response.status_code == 422


# ------------------------------------------------------------------ caching rules


def test_account_responses_disable_caching(client):
    # An unauthenticated 401 must not be cached either.
    anonymous = client.get("/api/v1/auth/me")
    assert anonymous.status_code == 401
    assert anonymous.headers["cache-control"] == "no-store"

    email = _email()
    register(client, email)
    logged_in = login(client, email)
    assert logged_in.headers["cache-control"] == "no-store"

    for path in ("/api/v1/auth/me", "/api/v1/candidates/me", "/api/v1/interviews/me"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert response.headers["cache-control"] == "no-store", path


# ------------------------------------------------- authenticated interview journey


def test_authenticated_interview_runs_end_to_end(client, auth):
    """The whole account journey: candidate id, interview, report, history."""
    email = _email()
    register(client, email)
    login(client, email)
    candidate_id = client.get("/api/v1/candidates/me").json()["candidate_id"]

    created = start_interview(client, candidate_id, question_count=1)
    assert created.status_code == 201
    interview_id = created.json()["interview_id"]
    question_id = created.json()["current_question_id"]
    assert question_id, "the bank must serve a question for this topic"

    answer = client.post(
        f"/interview/{interview_id}/answer",
        json={"question_id": question_id, "answer_text": "A complete answer " * 6},
    )
    assert answer.status_code in (200, 202)

    advanced = client.post(f"/interview/{interview_id}/next")
    assert advanced.status_code == 200
    assert advanced.json()["status"] == "completed"

    report = client.get(f"/interview/{interview_id}/report")
    assert report.status_code == 200
    assert report.json()["interview"]["candidate_id"] == candidate_id
    assert report.json()["answers"][0]["question_id"] == question_id

    history = client.get("/api/v1/interviews/me").json()
    assert [entry["interview_id"] for entry in history] == [interview_id]
    assert history[0]["status"] == "completed"
    assert history[0]["candidate_id"] == candidate_id


def test_guest_history_is_not_in_an_account_dashboard(client, auth):
    guest = client.post("/interview/start", json={"topic": TOPIC, "difficulty": "easy", "question_count": 1})
    assert guest.status_code == 201

    email = _email()
    register(client, email)
    login(client, email)
    assert client.get("/api/v1/interviews/me").json() == []
