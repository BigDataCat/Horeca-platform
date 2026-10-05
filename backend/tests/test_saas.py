import pytest

from app.core import metrics
from app.core.config import settings
from app.core.database import SessionLocal
from app.models.company import Company
from tests.conftest import bootstrap, create_integration, create_location


def set_plan(company_id, plan):
    with SessionLocal() as db:
        db.get(Company, company_id).plan = plan
        db.commit()


@pytest.fixture()
def admin_key(monkeypatch):
    monkeypatch.setattr(settings, "admin_api_key", "admin-secret")
    return {"X-Admin-Key": "admin-secret"}


def test_subscription_reports_plan_limits_and_usage(client, tenant_a):
    create_location(client, tenant_a)
    body = client.get("/api/subscription", headers=tenant_a["headers"]).json()
    assert body["plan"] == "business"
    assert body["limits"] == {"locations": 10, "users": 50, "integrations": 20}
    assert body["usage"]["locations"] == 1 and body["usage"]["users"] == 1


def test_trial_limits_are_enforced_with_402(client, tenant_a, manager_a):
    set_plan(tenant_a["company_id"], "trial")  # 1 location, 3 users, 1 integration
    location = create_location(client, tenant_a)
    blocked = client.post("/api/locations", headers=tenant_a["headers"], json={"company_id": tenant_a["company_id"], "name": "Second"})
    assert blocked.status_code == 402
    assert "trial plan" in blocked.json()["detail"]

    create_integration(client, tenant_a, location)
    second = client.post("/api/integrations/pos", headers=tenant_a["headers"], json={"location_id": location["id"], "provider": "demo", "name": "x"})
    assert second.status_code == 402

    body = lambda email: {"company_id": tenant_a["company_id"], "email": email, "first_name": "A", "last_name": "B", "password": "password123"}
    assert client.post("/api/users", headers=tenant_a["headers"], json=body("u3@test.dev")).status_code == 201  # 3rd user
    assert client.post("/api/users", headers=tenant_a["headers"], json=body("u4@test.dev")).status_code == 402


def test_deactivating_frees_capacity_and_reactivating_is_limited(client, tenant_a):
    set_plan(tenant_a["company_id"], "trial")
    location = create_location(client, tenant_a)
    client.delete(f"/api/locations/{location['id']}", headers=tenant_a["headers"])
    replacement = create_location(client, tenant_a, "Replacement")
    assert client.patch(f"/api/locations/{location['id']}", headers=tenant_a["headers"], json={"active": True}).status_code == 402
    assert replacement["id"] != location["id"]


def test_unlimited_plan_has_no_limits(client, tenant_a):
    set_plan(tenant_a["company_id"], "unlimited")
    for index in range(12):
        create_location(client, tenant_a, f"L{index}")
    assert client.get("/api/subscription", headers=tenant_a["headers"]).json()["limits"]["locations"] is None


def test_new_companies_get_the_configured_default_plan(client, monkeypatch):
    monkeypatch.setattr(settings, "default_plan", "trial")
    tenant = bootstrap(client, "Fresh", "fresh@test.dev")
    assert client.get("/api/subscription", headers=tenant["headers"]).json()["plan"] == "trial"
    monkeypatch.setattr(settings, "default_plan", "nonsense")
    other = bootstrap(client, "Fresh2", "fresh2@test.dev")
    assert client.get("/api/subscription", headers=other["headers"]).json()["plan"] == "trial"


# ---- authorization gaps fixed alongside
def test_employee_cannot_manage_locations_or_company(client, tenant_a, employee_a):
    location = create_location(client, tenant_a)
    assert client.post("/api/locations", headers=employee_a["headers"], json={"company_id": tenant_a["company_id"], "name": "x"}).status_code == 403
    assert client.patch(f"/api/locations/{location['id']}", headers=employee_a["headers"], json={"name": "x"}).status_code == 403
    assert client.delete(f"/api/locations/{location['id']}", headers=employee_a["headers"]).status_code == 403
    assert client.patch(f"/api/companies/{tenant_a['company_id']}", headers=employee_a["headers"], json={"name": "Hijacked"}).status_code == 403


def test_only_owner_can_edit_company(client, tenant_a, manager_a):
    url = f"/api/companies/{tenant_a['company_id']}"
    assert client.patch(url, headers=manager_a["headers"], json={"name": "Nope"}).status_code == 403
    assert client.patch(url, headers=tenant_a["headers"], json={"name": "Renamed"}).json()["name"] == "Renamed"
    assert client.post("/api/locations", headers=manager_a["headers"], json={"company_id": tenant_a["company_id"], "name": "By manager"}).status_code == 201


# ---- admin
def test_admin_endpoints_are_hidden_without_a_configured_key(client):
    assert client.get("/api/admin/companies").status_code == 404


def test_admin_key_required_and_lists_companies(client, tenant_a, tenant_b, admin_key):
    assert client.get("/api/admin/companies").status_code == 401
    assert client.get("/api/admin/companies", headers={"X-Admin-Key": "wrong"}).status_code == 401
    response = client.get("/api/admin/companies", headers=admin_key)
    assert response.status_code == 200
    assert {c["name"] for c in response.json()} == {"Tenant A", "Tenant B"}
    assert response.headers["X-Total-Count"] == "2"
    assert [c["name"] for c in client.get("/api/admin/companies", headers=admin_key, params={"q": "tenant b"}).json()] == ["Tenant B"]
    assert client.get("/api/admin/companies", headers=tenant_a["headers"]).status_code == 401  # a tenant JWT is not an admin key


def test_admin_changes_plan_and_deactivates_company(client, tenant_a, admin_key):
    url = f"/api/admin/companies/{tenant_a['company_id']}"
    assert client.patch(url, headers=admin_key, json={"plan": "bogus"}).status_code == 400
    assert client.patch(url, headers=admin_key, json={"plan": "starter"}).json()["plan"] == "starter"
    assert client.get("/api/subscription", headers=tenant_a["headers"]).json()["limits"]["locations"] == 3

    assert client.patch(url, headers=admin_key, json={"active": False}).json()["active"] is False
    assert client.get("/api/auth/me", headers=tenant_a["headers"]).status_code == 401
    login = client.post("/api/auth/login", json={"email": tenant_a["email"], "password": tenant_a["password"]})
    assert login.status_code == 403
    assert client.patch(url, headers=admin_key, json={"active": True}).json()["active"] is True
    assert client.get("/api/auth/me", headers=tenant_a["headers"]).status_code == 200
    assert client.patch("/api/admin/companies/999999", headers=admin_key, json={"plan": "trial"}).status_code == 404


# ---- metrics
def test_metrics_exposes_request_counters(client, tenant_a):
    metrics.reset()
    client.get("/health")
    client.get("/api/products", headers=tenant_a["headers"])
    client.get("/api/products", headers=tenant_a["headers"])
    text = client.get("/metrics").text
    assert "horeca_up 1" in text
    assert 'horeca_http_requests_total{method="GET",route="/api/products",status="200"} 2' in text
    assert 'horeca_http_request_duration_seconds_count{method="GET",route="/health"} 1' in text


def test_metrics_token_protection(client, monkeypatch):
    monkeypatch.setattr(settings, "metrics_token", "scrape-me")
    assert client.get("/metrics").status_code == 401
    assert client.get("/metrics", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/metrics", headers={"Authorization": "Bearer scrape-me"}).status_code == 200


def test_metrics_labels_use_parameter_names_not_values(client, tenant_a):
    metrics.reset()
    client.get(f"/api/locations/{create_location(client, tenant_a)['id']}", headers=tenant_a["headers"])
    client.get("/api/does-not-exist")
    text = client.get("/metrics").text
    assert 'route="/api/locations/{location_id}"' in text
    assert 'route="unmatched"' in text


# ---- subscription expiry
def set_expiry(company_id, delta_days):
    from datetime import datetime, timedelta, timezone

    with SessionLocal() as db:
        db.get(Company, company_id).plan_expires_at = datetime.now(timezone.utc) + timedelta(days=delta_days)
        db.commit()


def test_new_companies_get_a_trial_period_when_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "trial_days", 14)
    tenant = bootstrap(client, "Trial Co", "trial@test.dev")
    sub = client.get("/api/subscription", headers=tenant["headers"]).json()
    assert sub["expired"] is False and sub["expires_at"] is not None


def test_expired_subscription_is_read_only(client, tenant_a):
    create_location(client, tenant_a)
    set_expiry(tenant_a["company_id"], -1)
    assert client.get("/api/locations", headers=tenant_a["headers"]).status_code == 200      # data stays visible
    assert client.get("/api/sales/export.csv", headers=tenant_a["headers"]).status_code == 200  # and exportable
    blocked = client.post("/api/products", headers=tenant_a["headers"], json={"name": "X"})
    assert blocked.status_code == 402 and "expired" in blocked.json()["detail"]
    assert client.get("/api/subscription", headers=tenant_a["headers"]).json()["expired"] is True
    # signing in/out and changing the password still work
    assert client.post("/api/auth/login", json={"email": tenant_a["email"], "password": tenant_a["password"]}).status_code == 200
    changed = client.post("/api/auth/change-password", headers=tenant_a["headers"], json={"current_password": tenant_a["password"], "new_password": "another-pass-1"})
    assert changed.status_code == 200


def test_future_expiry_does_not_block_and_admin_can_renew(client, tenant_a, monkeypatch):
    monkeypatch.setattr(settings, "admin_api_key", "admin-secret")
    admin = {"X-Admin-Key": "admin-secret"}
    set_expiry(tenant_a["company_id"], 5)
    assert client.post("/api/products", headers=tenant_a["headers"], json={"name": "OK"}).status_code == 201
    set_expiry(tenant_a["company_id"], -1)
    assert client.post("/api/products", headers=tenant_a["headers"], json={"name": "Blocked"}).status_code == 402
    renewed = client.patch(
        f"/api/admin/companies/{tenant_a['company_id']}", headers=admin,
        json={"plan_expires_at": "2999-01-01T00:00:00Z"},
    )
    assert renewed.status_code == 200
    assert client.post("/api/products", headers=tenant_a["headers"], json={"name": "Back"}).status_code == 201
    cleared = client.patch(f"/api/admin/companies/{tenant_a['company_id']}", headers=admin, json={"clear_expiry": True})
    assert cleared.json()["plan_expires_at"] is None
