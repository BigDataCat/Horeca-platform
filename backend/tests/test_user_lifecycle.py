def login(client, email, password):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def test_change_password_rotates_token_and_invalidates_old_ones(client, tenant_a):
    response = client.post(
        "/api/auth/change-password",
        headers=tenant_a["headers"],
        json={"current_password": tenant_a["password"], "new_password": "new-password-1"},
    )
    assert response.status_code == 200, response.text
    new_headers = {"Authorization": f"Bearer {response.json()['access_token']}"}

    assert client.get("/api/auth/me", headers=tenant_a["headers"]).status_code == 401
    assert client.get("/api/auth/me", headers=new_headers).status_code == 200
    assert login(client, tenant_a["email"], tenant_a["password"]).status_code == 401
    assert login(client, tenant_a["email"], "new-password-1").status_code == 200


def test_change_password_validation(client, tenant_a):
    wrong = client.post(
        "/api/auth/change-password",
        headers=tenant_a["headers"],
        json={"current_password": "nope-nope", "new_password": "new-password-1"},
    )
    assert wrong.status_code == 400
    same = client.post(
        "/api/auth/change-password",
        headers=tenant_a["headers"],
        json={"current_password": tenant_a["password"], "new_password": tenant_a["password"]},
    )
    assert same.status_code == 400
    short = client.post(
        "/api/auth/change-password",
        headers=tenant_a["headers"],
        json={"current_password": tenant_a["password"], "new_password": "short"},
    )
    assert short.status_code == 422
    # nothing changed: the original token still works
    assert client.get("/api/auth/me", headers=tenant_a["headers"]).status_code == 200


def test_logout_invalidates_all_tokens_but_allows_new_login(client, tenant_a):
    other_device = login(client, tenant_a["email"], tenant_a["password"]).json()["access_token"]
    assert client.post("/api/auth/logout", headers=tenant_a["headers"]).status_code == 204
    assert client.get("/api/auth/me", headers=tenant_a["headers"]).status_code == 401
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {other_device}"}).status_code == 401
    assert login(client, tenant_a["email"], tenant_a["password"]).status_code == 200


def test_manager_resets_employee_password(client, tenant_a, manager_a, employee_a):
    response = client.post(
        f"/api/users/{employee_a['user']['id']}/reset-password",
        headers=manager_a["headers"],
        json={"new_password": "reset-password-1"},
    )
    assert response.status_code == 200
    assert client.get("/api/auth/me", headers=employee_a["headers"]).status_code == 401
    assert login(client, "employee-a@test.dev", "password123").status_code == 401
    assert login(client, "employee-a@test.dev", "reset-password-1").status_code == 200


def test_reset_password_rules(client, tenant_a, tenant_b, manager_a, employee_a):
    body = {"new_password": "reset-password-1"}
    owner_id = tenant_a["user"]["id"]
    assert client.post(f"/api/users/{owner_id}/reset-password", headers=manager_a["headers"], json=body).status_code == 403
    assert client.post(f"/api/users/{owner_id}/reset-password", headers=tenant_a["headers"], json=body).status_code == 400
    employee_id = employee_a["user"]["id"]
    assert client.post(f"/api/users/{employee_id}/reset-password", headers=employee_a["headers"], json=body).status_code == 403
    assert client.post(f"/api/users/{employee_id}/reset-password", headers=tenant_b["headers"], json=body).status_code == 404


def test_role_change_takes_effect_immediately(client, tenant_a, manager_a):
    assert client.post("/api/products", headers=manager_a["headers"], json={"name": "A"}).status_code == 201
    client.patch(f"/api/users/{manager_a['user']['id']}", headers=tenant_a["headers"], json={"role": "employee"})
    # the old manager token is no longer valid; a fresh login carries the lower role
    assert client.get("/api/auth/me", headers=manager_a["headers"]).status_code == 401
    token = login(client, "manager-a@test.dev", "password123").json()["access_token"]
    assert client.post("/api/products", headers={"Authorization": f"Bearer {token}"}, json={"name": "B"}).status_code == 403


def test_tokens_without_version_claim_still_work_for_version_zero(client, tenant_a):
    from datetime import datetime, timedelta, timezone

    import jwt

    from app.core.config import settings

    legacy = jwt.encode(
        {"sub": str(tenant_a["user"]["id"]), "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {legacy}"}).status_code == 200
