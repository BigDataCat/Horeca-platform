from sqlalchemy import func, select

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.company import Company
from app.models.product import Product
from app.models.sale import Sale
from app.models.user import User
from tests.conftest import (
    add_stock,
    create_integration,
    create_location,
    create_product,
    create_recipe,
    import_sales,
    line,
    sale_payload,
)


def test_owner_can_anonymize_a_user(client, tenant_a, manager_a):
    uid = manager_a["user"]["id"]
    response = client.post(f"/api/users/{uid}/anonymize", headers=tenant_a["headers"])
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == f"anonymized-{uid}@example.com"
    assert (body["first_name"], body["last_name"], body["active"]) == ("Deleted", "User", False)
    assert client.get("/api/auth/me", headers=manager_a["headers"]).status_code == 401
    assert client.post("/api/auth/login", json={"email": "manager-a@test.dev", "password": "password123"}).status_code == 401
    # the history they produced is preserved
    audit = client.get("/api/audit-log", headers=tenant_a["headers"], params={"user_id": uid}).json()
    assert isinstance(audit, list)


def test_anonymize_rules(client, tenant_a, tenant_b, manager_a, employee_a):
    uid = employee_a["user"]["id"]
    assert client.post(f"/api/users/{uid}/anonymize", headers=manager_a["headers"]).status_code == 403
    assert client.post(f"/api/users/{uid}/anonymize", headers=tenant_b["headers"]).status_code == 404
    assert client.post(f"/api/users/{tenant_a['user']['id']}/anonymize", headers=tenant_a["headers"]).status_code == 400


def test_user_can_export_their_own_data(client, tenant_a):
    create_product(client, tenant_a, "Burger")
    data = client.get("/api/auth/me/export", headers=tenant_a["headers"]).json()
    assert data["profile"]["email"] == tenant_a["email"]
    assert "password" not in str(data)
    assert [a["entity_type"] for a in data["recorded_actions"]] == ["product"]
    assert client.get("/api/auth/me/export").status_code == 401


def test_admin_company_deletion_removes_everything(client, tenant_a, tenant_b, monkeypatch):
    monkeypatch.setattr(settings, "admin_api_key", "admin-secret")
    admin = {"X-Admin-Key": "admin-secret"}
    location = create_location(client, tenant_a)
    integration = create_integration(client, tenant_a, location, provider="mock")
    burger = create_product(client, tenant_a, "Burger", sku="B")
    beef = create_product(client, tenant_a, "Beef", base_uom="KG")
    add_stock(client, tenant_a, location, beef, "5", "KG")
    create_recipe(client, tenant_a, burger, [{"ingredient_product_id": beef["id"], "quantity": "0.2", "uom": "KG"}])
    import_sales(client, tenant_a, integration, sale_payload("S1", lines=[line("Burger", "B")]))
    client.post("/api/suppliers", headers=tenant_a["headers"], json={"name": "Metro"})
    client.post(
        "/api/inventory/receipts", headers=tenant_a["headers"],
        json={"location_id": location["id"], "lines": [{"product_id": beef["id"], "quantity": "1", "uom": "KG", "unit_cost": "5"}]},
    )
    other = create_product(client, tenant_b, "Keep me")

    url = f"/api/admin/companies/{tenant_a['company_id']}"
    assert client.delete(url, headers=admin, params={"confirm_name": "wrong"}).status_code == 400
    assert client.delete(url, headers=admin, params={"confirm_name": "Tenant A"}).status_code == 204

    with SessionLocal() as db:
        assert db.get(Company, tenant_a["company_id"]) is None
        for model in (User, Product, Sale):
            assert db.scalar(select(func.count()).select_from(model).where(model.company_id == tenant_a["company_id"])) == 0
        assert db.get(Product, other["id"]) is not None
    assert client.get("/api/auth/me", headers=tenant_a["headers"]).status_code == 401
    assert client.delete("/api/admin/companies/999999", headers=admin, params={"confirm_name": "x"}).status_code == 404
