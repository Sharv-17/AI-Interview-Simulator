"""PostgreSQL account tests and migration test (opt-in).

Set TEST_DATABASE_URL to a PostgreSQL database that may be written to; otherwise
everything here is skipped with a clear reason. Like test_postgres_store.py, every
test works inside a throw-away schema that the module creates and drops, so the
`public` schema of the target database (Neon included) is never read or modified.

The migration test runs `alembic upgrade head` and `alembic downgrade` against that
schema, which is as close to a disposable database as a shared server allows.
"""

import os
import uuid
from datetime import timedelta
from pathlib import Path
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import NullPool

from app.db.models import Base
from app.db.postgres_auth_store import PostgresAuthStore, _normalize_url
from app.db.postgres_store import PostgresInterviewStore
from app.main import app
from app.services.auth_errors import EmailAlreadyRegistered
from app.services.auth_service import AuthService, set_auth_service
from app.services.auth_store import MemoryAuthStore
from app.services.interview_engine import utcnow
from app.services.interview_service import InterviewService, set_interview_service

BACKEND_DIR = Path(__file__).resolve().parents[1]
TEST_URL = (os.environ.get("TEST_DATABASE_URL") or "").strip()
pytestmark = pytest.mark.skipif(
    not TEST_URL, reason="TEST_DATABASE_URL is not set (PostgreSQL integration tests are opt-in)"
)

SCHEMA = f"test_auth_{uuid.uuid4().hex[:12]}"
PASSWORD = "correct horse battery staple"
TOPIC = "Databases"


def scoped_url(schema: str, base_url: str = None) -> str:
    url = _normalize_url(base_url or TEST_URL)
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}options={quote('-csearch_path=' + schema, safe='')}"


def _create_schema(name: str) -> None:
    admin = create_engine(_normalize_url(TEST_URL), poolclass=NullPool)
    try:
        with admin.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{name}"'))
    finally:
        admin.dispose()


def _drop_schema(name: str) -> None:
    admin = create_engine(_normalize_url(TEST_URL), poolclass=NullPool)
    try:
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{name}" CASCADE'))
    finally:
        admin.dispose()


@pytest.fixture()
def schema():
    name = f"{SCHEMA}_{uuid.uuid4().hex[:8]}"
    _create_schema(name)
    try:
        yield name
    finally:
        _drop_schema(name)


@pytest.fixture()
def engine(schema):
    scoped = create_engine(scoped_url(schema), poolclass=NullPool)
    try:
        Base.metadata.create_all(scoped)
        yield scoped
    finally:
        scoped.dispose()


@pytest.fixture()
def store(engine):
    return PostgresAuthStore(engine)


def _email() -> str:
    return f"user-{uuid.uuid4().hex[:12]}@example.com"


def _register(store: PostgresAuthStore, email: str = None):
    email = email or _email()
    return store.create_user(
        user_id=str(uuid.uuid4()),
        email=email,
        password_hash="not-a-real-hash-for-store-tests",
        candidate_id=str(uuid.uuid4()),
        created_at=utcnow(),
    )


# ------------------------------------------------------------------------ accounts


def test_user_roundtrip_and_candidate_link(store, engine):
    email = _email()
    user = _register(store, email)

    loaded = store.get_user_by_email(email)
    assert loaded is not None
    assert loaded.user_id == user.user_id
    assert loaded.candidate_id == user.candidate_id
    assert loaded.is_active is True
    assert loaded.is_email_verified is False, "registration must not claim verification"

    # The candidate row really exists, is owned by the account, and has no display name.
    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT candidate_id, user_id, display_name FROM candidates WHERE user_id = :uid"),
            {"uid": user.user_id},
        ).one()
    assert row.candidate_id == user.candidate_id
    assert row.display_name is None

    assert store.owner_of_candidate(user.candidate_id) == user.user_id
    assert store.owner_of_candidate(str(uuid.uuid4())) is None


def test_display_name_lands_on_the_one_linked_candidate(store, engine):
    user = store.create_user(
        user_id=str(uuid.uuid4()),
        email=_email(),
        password_hash="not-a-real-hash-for-store-tests",
        candidate_id=str(uuid.uuid4()),
        created_at=utcnow(),
        display_name="Ada Lovelace",
    )

    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT display_name, user_id FROM candidates WHERE candidate_id = :cid"),
            {"cid": user.candidate_id},
        ).one()
        total = connection.execute(text("SELECT count(*) FROM candidates")).scalar_one()

    assert row.display_name == "Ada Lovelace"
    assert row.user_id == user.user_id
    assert total == 1, "registration must not create a second candidate"


def test_duplicate_email_is_rejected_by_the_database(store, engine):
    email = _email()
    _register(store, email)

    with pytest.raises(EmailAlreadyRegistered):
        _register(store, email)

    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM users")).scalar_one() == 1
        # The failed registration must not have left a candidate behind.
        assert connection.execute(text("SELECT count(*) FROM candidates")).scalar_one() == 1


def test_one_account_cannot_own_two_candidates(store, engine):
    first = _register(store)
    second = _register(store)

    # The UNIQUE constraint is what makes "one account, one candidate" a guarantee.
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO candidates (candidate_id, display_name, external_id, user_id, created_at) "
                    "VALUES (:cid, NULL, NULL, :uid, now())"
                ),
                {"cid": str(uuid.uuid4()), "uid": first.user_id},
            )

    assert store.get_user(second.user_id).candidate_id == second.candidate_id


def test_guest_candidates_may_stay_unlinked(engine, store):
    with engine.begin() as connection:
        for _ in range(3):
            connection.execute(
                text(
                    "INSERT INTO candidates (candidate_id, display_name, external_id, user_id, created_at) "
                    "VALUES (:cid, 'Guest', NULL, NULL, now())"
                ),
                {"cid": str(uuid.uuid4())},
            )
        guests = connection.execute(
            text("SELECT count(*) FROM candidates WHERE user_id IS NULL")
        ).scalar_one()
    assert guests == 3


# ------------------------------------------------------------------------ sessions


def test_session_lifecycle(store):
    user = _register(store)
    now = utcnow()
    session = store.create_session(
        user_id=user.user_id,
        token_hash=uuid.uuid4().hex + uuid.uuid4().hex,
        created_at=now,
        expires_at=now + timedelta(hours=1),
    )

    loaded = store.get_session(session.token_hash)
    assert loaded is not None
    assert loaded.user_id == user.user_id
    assert loaded.revoked_at is None

    store.touch_session(session.session_id, now + timedelta(minutes=5))
    assert store.get_session(session.token_hash).last_used_at is not None

    assert store.revoke_session(session.session_id, now + timedelta(minutes=6)) is True
    assert store.revoke_session(session.session_id, now + timedelta(minutes=7)) is False
    assert store.get_session(session.token_hash).revoked_at is not None


def test_revoke_all_sessions_only_affects_one_account(store):
    first = _register(store)
    second = _register(store)
    now = utcnow()

    def new_session(user):
        return store.create_session(
            user_id=user.user_id,
            token_hash=uuid.uuid4().hex + uuid.uuid4().hex,
            created_at=now,
            expires_at=now + timedelta(hours=1),
        )

    first_sessions = [new_session(first), new_session(first)]
    other = new_session(second)

    assert store.revoke_all_sessions(first.user_id, now) == 2
    assert all(store.get_session(s.session_id and s.token_hash).revoked_at for s in first_sessions)
    assert store.get_session(other.token_hash).revoked_at is None


def test_expired_session_is_refused_by_the_service(store):
    service = AuthService(store, None, session_ttl_seconds=60)
    email = _email()
    service.register(email, PASSWORD)
    result = service.login(email, PASSWORD)

    assert service.authenticate(result.token) is not None
    later = AuthService(store, None, clock=lambda: result.expires_at + timedelta(seconds=1))
    assert later.authenticate(result.token) is None


# -------------------------------------------------------------------- API and owner


@pytest.fixture()
def postgres_app(engine):
    interviews = InterviewService(PostgresInterviewStore(engine))
    auth = AuthService(PostgresAuthStore(engine), interviews)
    set_interview_service(interviews)
    set_auth_service(auth)
    interviews.store.startup()
    try:
        yield interviews, auth
    finally:
        set_auth_service(None)
        set_interview_service(None)


def _register_and_login(client: TestClient, email: str) -> None:
    assert client.post(
        "/api/v1/auth/register", json={"email": email, "password": PASSWORD}
    ).status_code == 201
    assert client.post(
        "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    ).status_code == 200


def test_full_account_lifecycle_against_postgres(postgres_app):
    with TestClient(app) as client:
        email = _email()
        _register_and_login(client, email)

        me = client.get("/api/v1/auth/me")
        assert me.status_code == 200
        candidate_id = me.json()["candidate_id"]

        candidate = client.get("/api/v1/candidates/me").json()
        assert candidate["candidate_id"] == candidate_id

        created = client.post(
            "/interview/start",
            json={"topic": TOPIC, "difficulty": "easy", "question_count": 1, "candidate_id": candidate_id},
        )
        assert created.status_code == 201
        interview_id = created.json()["interview_id"]

        assert client.get("/api/v1/interviews/me").json()[0]["interview_id"] == interview_id
        assert client.get(f"/interview/{interview_id}/report").status_code == 200

        assert client.post("/api/v1/auth/logout").status_code == 204
        assert client.get("/api/v1/auth/me").status_code == 401
        # After logout the interview belongs to an account and needs that account.
        assert client.get(f"/interview/{interview_id}").status_code == 401


def test_postgres_ownership_isolation(postgres_app):
    with TestClient(app) as owner, TestClient(app) as intruder:
        owner_email = _email()
        _register_and_login(owner, owner_email)
        candidate_id = owner.get("/api/v1/candidates/me").json()["candidate_id"]
        interview_id = owner.post(
            "/interview/start",
            json={"topic": TOPIC, "difficulty": "easy", "question_count": 1, "candidate_id": candidate_id},
        ).json()["interview_id"]

        _register_and_login(intruder, _email())
        assert intruder.get(f"/interview/{interview_id}").status_code == 404
        assert intruder.get(f"/interview/{interview_id}/report").status_code == 404
        assert intruder.post(
            "/interview/start",
            json={"topic": TOPIC, "difficulty": "easy", "question_count": 1, "candidate_id": candidate_id},
        ).status_code == 404


def test_guest_interviews_survive_alongside_accounts(postgres_app):
    with TestClient(app) as guest:
        created = guest.post(
            "/interview/start", json={"topic": TOPIC, "difficulty": "easy", "question_count": 1}
        )
        assert created.status_code == 201
        interview_id = created.json()["interview_id"]

        assert guest.get(f"/interview/{interview_id}").status_code == 200
        assert guest.get(f"/interview/{interview_id}/report").status_code == 200
        assert guest.get("/api/v1/auth/me").status_code == 401


# ------------------------------------------------------------------------ migration


def test_migration_adds_auth_without_touching_guest_data(schema, monkeypatch):
    """Upgrade 0002 -> 0003 -> downgrade, inside a throw-away schema.

    A guest candidate inserted before 0003 must survive with user_id NULL, and the
    downgrade must remove only the new tables and the new column.
    """
    from alembic import command
    from alembic.config import Config

    monkeypatch.setenv("DATABASE_URL", scoped_url(schema))
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))

    command.upgrade(config, "0002")

    guest_id = str(uuid.uuid4())
    interview_id = str(uuid.uuid4())
    scoped = create_engine(scoped_url(schema), poolclass=NullPool)

    def candidate_display_name():
        # Deliberately does not select user_id: that column exists only after 0003.
        with scoped.connect() as connection:
            return connection.execute(
                text("SELECT display_name FROM candidates WHERE candidate_id = :cid"),
                {"cid": guest_id},
            ).scalar_one()

    def candidate_user_id():
        with scoped.connect() as connection:
            return connection.execute(
                text("SELECT user_id FROM candidates WHERE candidate_id = :cid"),
                {"cid": guest_id},
            ).scalar_one()

    def interview_count():
        with scoped.connect() as connection:
            return connection.execute(
                text("SELECT count(*) FROM interview_sessions WHERE interview_id = :iid"),
                {"iid": interview_id},
            ).scalar_one()

    try:
        # Pre-auth data: one guest candidate and one interview that references it.
        with scoped.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO candidates (candidate_id, display_name, external_id, created_at) "
                    "VALUES (:cid, 'Pre-auth guest', NULL, now())"
                ),
                {"cid": guest_id},
            )
            connection.execute(
                text(
                    "INSERT INTO interview_sessions (interview_id, candidate_id, topic, difficulty, "
                    "question_count, current_question, status, current_question_id, question_started_at, "
                    "question_time_limit_seconds, question_grace_seconds, created_at, completed_at) "
                    "VALUES (:iid, :cid, 'Databases', 'easy', 3, 1, 'active', NULL, NULL, NULL, 15, now(), NULL)"
                ),
                {"iid": interview_id, "cid": guest_id},
            )

        command.upgrade(config, "head")

        with scoped.connect() as connection:
            assert connection.execute(text("SELECT to_regclass('users') IS NOT NULL")).scalar_one()
            assert connection.execute(
                text("SELECT to_regclass('auth_sessions') IS NOT NULL")
            ).scalar_one()
        assert candidate_display_name() == "Pre-auth guest"
        assert candidate_user_id() is None, "existing guest candidates must stay unlinked"
        assert interview_count() == 1, "existing interview records must be untouched"

        command.downgrade(config, "0002")

        with scoped.connect() as connection:
            assert connection.execute(text("SELECT to_regclass('users') IS NULL")).scalar_one()
        assert candidate_display_name() == "Pre-auth guest"
        assert interview_count() == 1

        # Re-upgrade: the migration is repeatable on a database it has already seen.
        command.upgrade(config, "head")
        with scoped.connect() as connection:
            assert connection.execute(text("SELECT to_regclass('users') IS NOT NULL")).scalar_one()
        assert candidate_user_id() is None
        assert candidate_display_name() == "Pre-auth guest"
        assert interview_count() == 1
    finally:
        scoped.dispose()
