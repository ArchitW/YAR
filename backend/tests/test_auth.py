"""Tests for authentication and authorization (TKT-005)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app
from app.models.user import User

# Test DB fixture (in-memory SQLite with StaticPool)
engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db():
    session = TestSession()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db):
    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


class TestRegistrationAndLogin:
    def test_first_user_is_admin(self, client):
        resp = client.post("/auth/register", json={"email": "admin@yar.dev", "password": "securepassword"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["email"] == "admin@yar.dev"
        assert data["role"] == "admin"

    def test_second_user_is_regular_user(self, client):
        client.post("/auth/register", json={"email": "first@yar.dev", "password": "pass"})
        resp = client.post("/auth/register", json={"email": "second@yar.dev", "password": "pass"})
        assert resp.status_code == 200
        assert resp.json()["role"] == "user"

    def test_duplicate_registration_fails(self, client):
        client.post("/auth/register", json={"email": "test@yar.dev", "password": "pass"})
        resp = client.post("/auth/register", json={"email": "test@yar.dev", "password": "pass"})
        assert resp.status_code == 400
        assert resp.json()["detail"] == "email exists"

    def test_login_success(self, client):
        client.post("/auth/register", json={"email": "test@yar.dev", "password": "pass"})
        resp = client.post("/auth/login", json={"email": "test@yar.dev", "password": "pass"})
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["user"]["email"] == "test@yar.dev"

    def test_login_invalid_password(self, client):
        client.post("/auth/register", json={"email": "test@yar.dev", "password": "pass"})
        resp = client.post("/auth/login", json={"email": "test@yar.dev", "password": "wrong"})
        assert resp.status_code == 401


class TestAuthToggle:
    def test_auth_status_disabled_by_default(self, client, monkeypatch):
        monkeypatch.delenv("AUTH_ENABLED", raising=False)
        resp = client.get("/auth/status")
        assert resp.status_code == 200
        assert resp.json()["auth_enabled"] is False

    def test_auth_status_enabled_when_set(self, client, monkeypatch):
        monkeypatch.setenv("AUTH_ENABLED", "true")
        resp = client.get("/auth/status")
        assert resp.status_code == 200
        assert resp.json()["auth_enabled"] is True

    def test_me_endpoint_works_when_auth_disabled(self, client, monkeypatch):
        monkeypatch.setenv("AUTH_ENABLED", "false")
        resp = client.get("/auth/me")
        assert resp.status_code == 200
        assert resp.json()["role"] == "admin"


class TestAuthEnforced:
    @pytest.fixture(autouse=True)
    def enable_auth(self, monkeypatch):
        monkeypatch.setenv("AUTH_ENABLED", "true")
        monkeypatch.setenv("JWT_SECRET", "test-secret-key-12345678901234567890")

    def test_me_requires_token(self, client):
        resp = client.get("/auth/me")
        assert resp.status_code == 401

    def test_me_with_invalid_token(self, client):
        resp = client.get("/auth/me", headers={"Authorization": "Bearer invalid.token.value"})
        assert resp.status_code == 401

    def test_me_with_valid_token(self, client):
        client.post("/auth/register", json={"email": "test@yar.dev", "password": "pass"})
        login_resp = client.post("/auth/login", json={"email": "test@yar.dev", "password": "pass"})
        token = login_resp.json()["access_token"]

        resp = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert resp.json()["email"] == "test@yar.dev"

    def test_logout_with_valid_token(self, client):
        client.post("/auth/register", json={"email": "test@yar.dev", "password": "pass"})
        login_resp = client.post("/auth/login", json={"email": "test@yar.dev", "password": "pass"})
        token = login_resp.json()["access_token"]

        resp = client.post("/auth/logout", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert resp.json()["message"] == "successfully logged out"


class TestRoleChecks:
    @pytest.fixture(autouse=True)
    def enable_auth(self, monkeypatch):
        monkeypatch.setenv("AUTH_ENABLED", "true")
        monkeypatch.setenv("JWT_SECRET", "test-secret-key-12345678901234567890")

    def test_require_admin_allows_admin_user(self, client):
        # First registered user is admin
        client.post("/auth/register", json={"email": "admin@yar.dev", "password": "pass"})
        admin_login = client.post("/auth/login", json={"email": "admin@yar.dev", "password": "pass"})
        admin_token = admin_login.json()["access_token"]

        from app.routers.auth import require_admin
        from fastapi import Depends

        @app.get("/test-admin-only")
        def admin_only_endpoint(user=Depends(require_admin)):
            return {"ok": True, "admin": user.email}

        resp = client.get("/test-admin-only", headers={"Authorization": f"Bearer {admin_token}"})
        assert resp.status_code == 200
        assert resp.json()["admin"] == "admin@yar.dev"

    def test_require_admin_blocks_standard_user(self, client):
        client.post("/auth/register", json={"email": "admin@yar.dev", "password": "pass"})
        # Second user is standard 'user'
        client.post("/auth/register", json={"email": "user@yar.dev", "password": "pass"})
        user_login = client.post("/auth/login", json={"email": "user@yar.dev", "password": "pass"})
        user_token = user_login.json()["access_token"]

        resp = client.get("/test-admin-only", headers={"Authorization": f"Bearer {user_token}"})
        assert resp.status_code == 403
        assert resp.json()["detail"] == "admin privileges required"
