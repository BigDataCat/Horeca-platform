from decimal import Decimal

from tests.conftest import (
    add_stock,
    create_integration,
    create_location,
    create_product,
    create_recipe,
    get_stock,
    import_sales,
    line,
    sale_payload,
    with_webhook_token,
)


def setup(client, tenant):
    location = create_location(client, tenant)
    integration = create_integration(client, tenant, location, provider="mock")
    burger = create_product(client, tenant, "Burger", sku="BURGER")
    beef = create_product(client, tenant, "Beef", base_uom="KG")
    add_stock(client, tenant, location, beef, "10", "KG")
    create_recipe(client, tenant, burger, [{"ingredient_product_id": beef["id"], "quantity": "0.2", "uom": "KG"}])
    return location, integration, beef


def sell(client, tenant, integration, external_id="S1", quantity="2"):
    import_sales(client, tenant, integration, sale_payload(external_id, lines=[line("Burger", "BURGER", quantity=quantity)]))
    return next(s for s in client.get("/api/sales", headers=tenant["headers"]).json() if s["external_id"] == external_id)


def stock(client, tenant, location, beef):
    return Decimal(get_stock(client, tenant, location, beef)["quantity"])


def test_cancel_restores_stock_and_is_recorded(client, tenant_a):
    location, integration, beef = setup(client, tenant_a)
    sale = sell(client, tenant_a, integration)
    assert stock(client, tenant_a, location, beef) == Decimal("9.6")

    response = client.post(
        f"/api/sales/{sale['id']}/status", headers=tenant_a["headers"], json={"status": "cancelled", "reason": "customer left"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "cancelled"
    assert response.json()["status_reason"] == "customer left"
    assert stock(client, tenant_a, location, beef) == Decimal("10")

    types = sorted(m["movement_type"] for m in client.get("/api/inventory/movements", headers=tenant_a["headers"]).json())
    assert types == ["adjustment", "recipe_consumption", "sale_reversal"]


def test_cancel_twice_is_rejected_and_does_not_double_restore(client, tenant_a):
    location, integration, beef = setup(client, tenant_a)
    sale = sell(client, tenant_a, integration)
    url = f"/api/sales/{sale['id']}/status"
    assert client.post(url, headers=tenant_a["headers"], json={"status": "cancelled"}).status_code == 200
    assert client.post(url, headers=tenant_a["headers"], json={"status": "refunded"}).status_code == 409
    assert stock(client, tenant_a, location, beef) == Decimal("10")


def test_refund_status(client, tenant_a):
    location, integration, beef = setup(client, tenant_a)
    sale = sell(client, tenant_a, integration)
    response = client.post(f"/api/sales/{sale['id']}/status", headers=tenant_a["headers"], json={"status": "refunded"})
    assert response.json()["status"] == "refunded"
    assert stock(client, tenant_a, location, beef) == Decimal("10")


def test_invalid_status_rejected(client, tenant_a):
    location, integration, beef = setup(client, tenant_a)
    sale = sell(client, tenant_a, integration)
    assert client.post(f"/api/sales/{sale['id']}/status", headers=tenant_a["headers"], json={"status": "completed"}).status_code == 422


def test_cancelled_sales_leave_dashboard_revenue(client, tenant_a):
    location, integration, beef = setup(client, tenant_a)
    keep = sell(client, tenant_a, integration, "S1")
    drop = sell(client, tenant_a, integration, "S2")
    client.post(f"/api/sales/{drop['id']}/status", headers=tenant_a["headers"], json={"status": "cancelled"})
    summary = client.get("/api/dashboard/summary", headers=tenant_a["headers"]).json()
    assert summary["sales_count"] == 1
    assert summary["cancelled_sales"] == 1
    assert Decimal(summary["revenue"]) == Decimal("10.00")


def test_reimport_of_cancelled_sale_does_not_resurrect_it(client, tenant_a):
    location, integration, beef = setup(client, tenant_a)
    sale = sell(client, tenant_a, integration)
    client.post(f"/api/sales/{sale['id']}/status", headers=tenant_a["headers"], json={"status": "cancelled"})
    again = import_sales(client, tenant_a, integration, sale_payload("S1", lines=[line("Burger", "BURGER", quantity="2")]))
    assert again.json() == {"imported": 0, "skipped_duplicates": 1}
    assert stock(client, tenant_a, location, beef) == Decimal("10")


def test_status_change_is_manager_only_and_tenant_scoped(client, tenant_a, tenant_b, employee_a):
    location, integration, beef = setup(client, tenant_a)
    sale = sell(client, tenant_a, integration)
    url = f"/api/sales/{sale['id']}/status"
    assert client.post(url, headers=employee_a["headers"], json={"status": "cancelled"}).status_code == 403
    assert client.post(url, headers=tenant_b["headers"], json={"status": "cancelled"}).status_code == 404


def test_same_external_id_on_two_integrations_reverses_only_the_right_sale(client, tenant_a):
    location, first, beef = setup(client, tenant_a)
    second = create_integration(client, tenant_a, location, provider="mock")
    one = sell(client, tenant_a, first, "S1", quantity="1")
    sell(client, tenant_a, second, "S1", quantity="3")
    assert stock(client, tenant_a, location, beef) == Decimal("9.2")
    client.post(f"/api/sales/{one['id']}/status", headers=tenant_a["headers"], json={"status": "cancelled"})
    assert stock(client, tenant_a, location, beef) == Decimal("9.4")


def webhook(client, integration, event_type, event_id, external_id="W1", quantity="2"):
    return client.post(
        f"/api/integrations/pos/{integration['id']}/webhook",
        headers={"X-Webhook-Token": integration["token"]},
        json={
            "event_id": event_id,
            "event_type": event_type,
            "sale": sale_payload(external_id, lines=[line("Burger", "BURGER", quantity=quantity)]),
        },
    )


def test_webhook_cancel_event_reverses_sale(client, tenant_a):
    location, integration, beef = setup(client, tenant_a)
    integration = with_webhook_token(client, tenant_a, integration)
    assert webhook(client, integration, "sale.created", "E1").status_code == 200
    assert stock(client, tenant_a, location, beef) == Decimal("9.6")
    cancel = webhook(client, integration, "sale.cancelled", "E2")
    assert cancel.status_code == 200
    assert cancel.json()["duplicate"] is False
    assert stock(client, tenant_a, location, beef) == Decimal("10")
    # replayed cancel event (new event id) is a no-op
    assert webhook(client, integration, "sale.cancelled", "E3").json()["duplicate"] is True
    assert stock(client, tenant_a, location, beef) == Decimal("10")


def test_cancel_arriving_before_create_leaves_stock_untouched(client, tenant_a):
    location, integration, beef = setup(client, tenant_a)
    integration = with_webhook_token(client, tenant_a, integration)
    assert webhook(client, integration, "sale.cancelled", "E1").status_code == 200
    late_create = webhook(client, integration, "sale.created", "E2")
    assert late_create.json()["duplicate"] is True
    assert stock(client, tenant_a, location, beef) == Decimal("10")
    sale = client.get("/api/sales", headers=tenant_a["headers"]).json()[0]
    assert sale["status"] == "cancelled"
