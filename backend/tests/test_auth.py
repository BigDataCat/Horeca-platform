from datetime import datetime, timedelta, timezone

import jwt

from app.core.config import settings


def test_bootstrap_creates_owner_and_token(client):
    response = client.post(
        "/api/auth/bootstrap",
        json={
            "company_name": "Acme",
            "email": "Owner@Acme.dev",
            "first_name": "O",
            "last_name": "W",
            "password": "password123",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["user"]["role"] == "owner"
    assert body["user"]["email"] == "owner@acme.dev"
    assert "password" not in str(body)


def test_bootstrap_duplicate_email_conflicts(client, tenant_a):
    response = client.post(
        "/api/auth/bootstrap",
        json={
            "company_name": "Other",
            "email": tenant_a["email"].upper(),
            "first_name": "O",
            "last_name": "W",
            "password": "password123",
        },
    )
    assert response.status_code == 409


def test_login_success_and_me(client, tenant_a):
    login = client.post(
        "/api/auth/login",
        json={"email": tenant_a["email"], "password": tenant_a["password"]},
    )
    assert login.status_code == 200
    me = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    )
    assert me.status_code == 200
    assert me.json()["email"] == tenant_a["email"]


def test_login_wrong_password(client, tenant_a):
    response = client.post(
        "/api/auth/login", json={"email": tenant_a["email"], "password": "wrong-password"}
    )
    assert response.status_code == 401


def test_login_unknown_user(client):
    response = client.post(
        "/api/auth/login", json={"email": "nobody@test.dev", "password": "password123"}
    )
    assert response.status_code == 401


def test_missing_token_rejected(client):
    assert client.get("/api/auth/me").status_code == 401


def test_garbage_token_rejected(client):
    response = client.get("/api/auth/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert response.status_code == 401


def test_token_signed_with_wrong_key_rejected(client, tenant_a):
    forged = jwt.encode(
        {
            "sub": str(tenant_a["user"]["id"]),
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        "x" * 40,
        algorithm=settings.jwt_algorithm,
    )
    response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {forged}"})
    assert response.status_code == 401


def test_expired_token_rejected(client, tenant_a):
    expired = jwt.encode(
        {
            "sub": str(tenant_a["user"]["id"]),
            "exp": datetime.now(timezone.utc) - timedelta(minutes=1),
        },
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {expired}"})
    assert response.status_code == 401


def test_token_without_subject_rejected(client):
    token = jwt.encode(
        {"exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


def test_deactivated_user_cannot_use_existing_token_or_login(client, tenant_a, manager_a):
    response = client.delete(f"/api/users/{manager_a['user']['id']}", headers=tenant_a["headers"])
    assert response.status_code == 200
    assert client.get("/api/auth/me", headers=manager_a["headers"]).status_code == 401
    login = client.post(
        "/api/auth/login", json={"email": "manager-a@test.dev", "password": "password123"}
    )
    assert login.status_code == 403


def test_register_refused_for_company_with_users(client, tenant_a):
    response = client.post(
        "/api/auth/register",
        json={
            "company_id": tenant_a["company_id"],
            "email": "intruder@test.dev",
            "first_name": "I",
            "last_name": "N",
            "password": "password123",
        },
    )
    assert response.status_code == 403


def test_health(client):
    assert client.get("/health").json() == {"status": "ok", "database": "ok"}
