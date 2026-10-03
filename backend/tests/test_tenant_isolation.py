"""Tenant B must never see or modify tenant A's data."""
import pytest

from tests.conftest import create_location, create_product

DENIED = {403, 404}


@pytest.fixture()
def seeded_a(client, tenant_a):
    location = create_location(client, tenant_a)
    product = create_product(client, tenant_a, "Beef", sku="BEEF", base_uom="KG")
    burger = create_product(client, tenant_a, "Burger", sku="BURGER")
    integration = client.post(
        "/api/integrations/pos",
        headers=tenant_a["headers"],
        json={"location_id": location["id"], "provider": "demo", "name": "Demo POS"},
    )
    assert integration.status_code == 201, integration.text
    return {
        "location": location,
        "beef": product,
        "burger": burger,
        "integration": integration.json(),
    }


def test_lists_are_scoped_to_own_company(client, tenant_b, seeded_a):
    for path in [
        "/api/products",
        "/api/locations",
        "/api/integrations/pos",
        "/api/product-mappings",
        "/api/product-mappings/uom-conversions",
        "/api/sales",
        "/api/sales/unmatched-products",
        "/api/inventory/stock",
        "/api/inventory/movements",
        "/api/recipes",
        "/api/costs/products",
    ]:
        response = client.get(path, headers=tenant_b["headers"])
        assert response.status_code == 200, path
        assert response.json() == [], path

    users = client.get("/api/users", headers=tenant_b["headers"]).json()
    assert {u["company_id"] for u in users} == {tenant_b["company_id"]}
    companies = client.get("/api/companies", headers=tenant_b["headers"]).json()
    assert [c["id"] for c in companies] == [tenant_b["company_id"]]


def test_company_access_denied(client, tenant_a, tenant_b):
    assert client.get(f"/api/companies/{tenant_a['company_id']}", headers=tenant_b["headers"]).status_code == 403
    assert (
        client.patch(
            f"/api/companies/{tenant_a['company_id']}", headers=tenant_b["headers"], json={"name": "Hacked"}
        ).status_code
        == 403
    )
    assert client.get("/api/locations", params={"company_id": tenant_a["company_id"]}, headers=tenant_b["headers"]).status_code == 403


def test_location_access_denied(client, tenant_b, seeded_a):
    lid = seeded_a["location"]["id"]
    assert client.get(f"/api/locations/{lid}", headers=tenant_b["headers"]).status_code in DENIED
    assert client.patch(f"/api/locations/{lid}", headers=tenant_b["headers"], json={"name": "x"}).status_code in DENIED
    assert client.delete(f"/api/locations/{lid}", headers=tenant_b["headers"]).status_code in DENIED


def test_cannot_create_location_in_other_company(client, tenant_a, tenant_b):
    response = client.post(
        "/api/locations",
        headers=tenant_b["headers"],
        json={"company_id": tenant_a["company_id"], "name": "Sneaky"},
    )
    assert response.status_code in DENIED


def test_cannot_create_user_in_other_company(client, tenant_a, tenant_b):
    response = client.post(
        "/api/users",
        headers=tenant_b["headers"],
        json={
            "company_id": tenant_a["company_id"],
            "email": "sneaky@test.dev",
            "first_name": "S",
            "last_name": "N",
            "password": "password123",
        },
    )
    assert response.status_code in DENIED


def test_user_modification_denied(client, tenant_a, tenant_b):
    uid = tenant_a["user"]["id"]
    assert client.patch(f"/api/users/{uid}", headers=tenant_b["headers"], json={"first_name": "x"}).status_code in DENIED
    assert client.delete(f"/api/users/{uid}", headers=tenant_b["headers"]).status_code in DENIED


def test_product_update_denied(client, tenant_b, seeded_a):
    pid = seeded_a["beef"]["id"]
    assert client.patch(f"/api/products/{pid}", headers=tenant_b["headers"], json={"name": "x"}).status_code in DENIED


def test_integration_access_denied(client, tenant_b, seeded_a):
    iid = seeded_a["integration"]["id"]
    assert client.get(f"/api/integrations/pos/{iid}/sync-runs", headers=tenant_b["headers"]).status_code in DENIED
    assert client.patch(f"/api/integrations/pos/{iid}", headers=tenant_b["headers"], json={"name": "x"}).status_code in DENIED
    assert client.delete(f"/api/integrations/pos/{iid}", headers=tenant_b["headers"]).status_code in DENIED
    assert client.post(f"/api/integrations/pos/{iid}/sync", headers=tenant_b["headers"]).status_code in DENIED
    assert client.post(f"/api/integrations/pos/{iid}/test", headers=tenant_b["headers"]).status_code in DENIED


def test_cannot_create_integration_on_other_tenant_location(client, tenant_b, seeded_a):
    response = client.post(
        "/api/integrations/pos",
        headers=tenant_b["headers"],
        json={"location_id": seeded_a["location"]["id"], "provider": "demo", "name": "x"},
    )
    assert response.status_code in DENIED


def test_cannot_map_other_tenant_product_or_integration(client, tenant_b, seeded_a):
    own_product = create_product(client, tenant_b, "Own")
    cross_integration = client.post(
        "/api/product-mappings",
        headers=tenant_b["headers"],
        json={
            "integration_id": seeded_a["integration"]["id"],
            "external_product_id": "E1",
            "product_id": own_product["id"],
        },
    )
    assert cross_integration.status_code in DENIED

    location_b = create_location(client, tenant_b)
    integration_b = client.post(
        "/api/integrations/pos",
        headers=tenant_b["headers"],
        json={"location_id": location_b["id"], "provider": "demo", "name": "B POS"},
    ).json()
    cross_product = client.post(
        "/api/product-mappings",
        headers=tenant_b["headers"],
        json={
            "integration_id": integration_b["id"],
            "external_product_id": "E1",
            "product_id": seeded_a["beef"]["id"],
        },
    )
    assert cross_product.status_code in DENIED


def test_cannot_create_uom_conversion_for_other_tenant_product(client, tenant_b, seeded_a):
    response = client.post(
        "/api/product-mappings/uom-conversions",
        headers=tenant_b["headers"],
        json={"product_id": seeded_a["beef"]["id"], "from_uom": "G", "to_uom": "KG", "factor": "0.001"},
    )
    assert response.status_code in DENIED


def test_cannot_adjust_other_tenant_stock(client, tenant_b, seeded_a):
    response = client.post(
        "/api/inventory/adjustments",
        headers=tenant_b["headers"],
        json={
            "location_id": seeded_a["location"]["id"],
            "product_id": seeded_a["beef"]["id"],
            "quantity": "10",
            "uom": "KG",
        },
    )
    assert response.status_code in DENIED


def test_cannot_build_recipe_from_other_tenant_products(client, tenant_b, seeded_a):
    response = client.post(
        "/api/recipes",
        headers=tenant_b["headers"],
        json={
            "product_id": seeded_a["burger"]["id"],
            "name": "Stolen",
            "lines": [{"ingredient_product_id": seeded_a["beef"]["id"], "quantity": "0.2", "uom": "KG"}],
        },
    )
    assert response.status_code in DENIED


def test_cannot_set_cost_or_read_recipe_cost_across_tenants(client, tenant_a, tenant_b, seeded_a):
    cost = client.post(
        "/api/costs/products",
        headers=tenant_b["headers"],
        json={
            "product_id": seeded_a["beef"]["id"],
            "unit_cost": "10",
            "effective_from": "2026-01-01T00:00:00Z",
        },
    )
    assert cost.status_code in DENIED

    recipe = client.post(
        "/api/recipes",
        headers=tenant_a["headers"],
        json={
            "product_id": seeded_a["burger"]["id"],
            "name": "Burger",
            "lines": [{"ingredient_product_id": seeded_a["beef"]["id"], "quantity": "0.2", "uom": "KG"}],
        },
    )
    assert recipe.status_code == 201, recipe.text
    response = client.get(f"/api/costs/recipes/{recipe.json()['id']}", headers=tenant_b["headers"])
    assert response.status_code in DENIED
    assert client.delete(f"/api/recipes/{recipe.json()['id']}", headers=tenant_b["headers"]).status_code in DENIED


def test_webhook_unknown_integration_is_not_found(client, seeded_a):
    response = client.post("/api/integrations/pos/999999/webhook", json={})
    assert response.status_code in {401, 403, 404, 422}


def test_dashboard_is_scoped(client, tenant_b, seeded_a):
    response = client.get("/api/dashboard/summary", headers=tenant_b["headers"])
    assert response.status_code == 200
    body = response.json()
    assert body.get("sales_count", 0) == 0
