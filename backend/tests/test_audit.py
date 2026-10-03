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


def audit(client, tenant, **params):
    response = client.get("/api/audit-log", headers=tenant["headers"], params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_product_create_and_update_are_audited_with_field_changes(client, tenant_a):
    product = create_product(client, tenant_a, "Burger", sku="B1")
    client.patch(f"/api/products/{product['id']}", headers=tenant_a["headers"], json={"name": "Big Burger", "category": "Mains"})
    entries = audit(client, tenant_a, entity_type="product")
    assert [e["action"] for e in entries] == ["updated", "created"]
    assert entries[0]["entity_id"] == product["id"]
    assert entries[0]["user_id"] == tenant_a["user"]["id"]
    assert entries[0]["details"] == {"name": ["Burger", "Big Burger"], "category": [None, "Mains"]}
    assert entries[1]["details"]["name"] == "Burger"


def test_sensitive_values_are_never_logged(client, tenant_a, manager_a):
    client.post(
        f"/api/users/{manager_a['user']['id']}/reset-password",
        headers=tenant_a["headers"],
        json={"new_password": "super-secret-1"},
    )
    location = create_location(client, tenant_a)
    integration = create_integration(client, tenant_a, location, config={"api_key": "TOPSECRET"})
    client.post(f"/api/integrations/pos/{integration['id']}/webhook-token", headers=tenant_a["headers"])
    dump = str(audit(client, tenant_a))
    for secret in ["super-secret-1", "password_hash", "TOPSECRET", "webhook_token_hash", "token_version"]:
        assert secret not in dump
    assert "api_key" in dump  # config keys are visible, values are not


def test_users_inventory_costs_recipes_are_audited(client, tenant_a, manager_a):
    location = create_location(client, tenant_a)
    beef = create_product(client, tenant_a, "Beef", base_uom="KG")
    burger = create_product(client, tenant_a, "Burger")
    recipe = create_recipe(client, tenant_a, burger, [{"ingredient_product_id": beef["id"], "quantity": "0.2", "uom": "KG"}])
    client.delete(f"/api/recipes/{recipe['id']}", headers=tenant_a["headers"])
    client.post(
        "/api/costs/products", headers=tenant_a["headers"],
        json={"product_id": beef["id"], "unit_cost": "5", "effective_from": "2026-01-01T00:00:00Z"},
    )
    types = {e["entity_type"] for e in audit(client, tenant_a)}
    assert {"user", "location", "product", "recipe", "product_cost"} <= types
    recipe_entries = audit(client, tenant_a, entity_type="recipe")
    assert [e["action"] for e in recipe_entries] == ["updated", "created"]
    assert recipe_entries[0]["details"] == {"active": [True, False]}


def test_sale_import_is_not_audited_but_cancel_is(client, tenant_a):
    location = create_location(client, tenant_a)
    integration = create_integration(client, tenant_a, location, provider="mock")
    import_sales(client, tenant_a, integration, sale_payload("S1"))
    assert audit(client, tenant_a, entity_type="sale") == []
    sale = client.get("/api/sales", headers=tenant_a["headers"]).json()[0]
    client.post(f"/api/sales/{sale['id']}/status", headers=tenant_a["headers"], json={"status": "cancelled", "reason": "oops"})
    entries = audit(client, tenant_a, entity_type="sale")
    assert len(entries) == 1
    assert entries[0]["details"]["status"] == ["completed", "cancelled"]


def test_sync_cursor_updates_do_not_spam_the_log(client, tenant_a):
    location = create_location(client, tenant_a)
    integration = create_integration(client, tenant_a, location, provider="demo")
    client.post(f"/api/integrations/pos/{integration['id']}/sync", headers=tenant_a["headers"])
    entries = audit(client, tenant_a, entity_type="pos_integration")
    assert [e["action"] for e in entries] == ["created"]


def test_failed_request_leaves_no_audit_entry(client, tenant_a):
    before = len(audit(client, tenant_a))
    client.post("/api/products", headers=tenant_a["headers"], json={"name": ""})
    assert len(audit(client, tenant_a)) == before


def test_audit_log_is_manager_only_tenant_scoped_and_filterable(client, tenant_a, tenant_b, employee_a):
    create_product(client, tenant_a, "A")
    create_product(client, tenant_a, "B")
    create_product(client, tenant_b, "Other tenant")
    assert client.get("/api/audit-log", headers=employee_a["headers"]).status_code == 403
    mine = audit(client, tenant_a, entity_type="product")
    assert len(mine) == 2
    assert all(e["details"]["name"] in {"A", "B"} for e in mine)
    page = client.get("/api/audit-log", headers=tenant_a["headers"], params={"entity_type": "product", "limit": 1, "offset": 1})
    assert len(page.json()) == 1
    assert page.headers["X-Total-Count"] == "2"
    assert audit(client, tenant_a, user_id=999999) == []
    assert audit(client, tenant_a, date_from="2999-01-01T00:00:00Z") == []
