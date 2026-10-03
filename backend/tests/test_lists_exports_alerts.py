import csv
import io
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.core.database import SessionLocal
from app.models.pos_integration import POSIntegration
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


def rows(response):
    assert response.status_code == 200, response.text
    return list(csv.reader(io.StringIO(response.text.lstrip("﻿"))))


# ---- pagination and filters
def test_products_pagination_search_and_filters(client, tenant_a):
    for name in ["Alpha", "Beta", "Gamma", "100% Juice", "Under_score"]:
        create_product(client, tenant_a, name)
    page = client.get("/api/products", headers=tenant_a["headers"], params={"limit": 2, "offset": 1})
    assert [p["name"] for p in page.json()] == ["Alpha", "Beta"]
    assert page.headers["X-Total-Count"] == "5"
    assert [p["name"] for p in client.get("/api/products", headers=tenant_a["headers"], params={"q": "ALP"}).json()] == ["Alpha"]
    assert [p["name"] for p in client.get("/api/products", headers=tenant_a["headers"], params={"q": "%"}).json()] == ["100% Juice"]
    assert [p["name"] for p in client.get("/api/products", headers=tenant_a["headers"], params={"q": "_"}).json()] == ["Under_score"]
    client.patch("/api/products/1", headers=tenant_a["headers"], json={"active": False})
    assert client.get("/api/products", headers=tenant_a["headers"], params={"active": "true"}).headers["X-Total-Count"] == "4"


def test_sales_filters_and_pagination(client, tenant_a):
    first = create_location(client, tenant_a, "One")
    second = create_location(client, tenant_a, "Two")
    one = create_integration(client, tenant_a, first, provider="mock")
    two = create_integration(client, tenant_a, second, provider="mock")
    import_sales(client, tenant_a, one, sale_payload("A", occurred_at="2026-01-10T10:00:00Z"), sale_payload("B", occurred_at="2026-02-10T10:00:00Z"))
    import_sales(client, tenant_a, two, sale_payload("C", occurred_at="2026-03-10T10:00:00Z"))
    ids = lambda **p: [s["external_id"] for s in client.get("/api/sales", headers=tenant_a["headers"], params=p).json()]
    assert ids() == ["C", "B", "A"]
    assert ids(location_id=first["id"]) == ["B", "A"]
    assert ids(integration_id=two["id"]) == ["C"]
    assert ids(date_from="2026-02-01T00:00:00Z", date_to="2026-03-01T00:00:00Z") == ["B"]
    assert ids(limit=1, offset=1) == ["B"]
    assert ids(status="cancelled") == []
    assert client.get("/api/sales", headers=tenant_a["headers"], params={"limit": 1}).headers["X-Total-Count"] == "3"


def test_movement_and_stock_filters(client, tenant_a):
    one = create_location(client, tenant_a, "One")
    two = create_location(client, tenant_a, "Two")
    beef = create_product(client, tenant_a, "Beef", base_uom="KG")
    add_stock(client, tenant_a, one, beef, "5", "KG")
    add_stock(client, tenant_a, two, beef, "7", "KG")
    assert len(client.get("/api/inventory/stock", headers=tenant_a["headers"], params={"location_id": one["id"]}).json()) == 1
    moves = client.get("/api/inventory/movements", headers=tenant_a["headers"], params={"location_id": two["id"], "movement_type": "adjustment"})
    assert [Decimal(m["quantity"]) for m in moves.json()] == [Decimal("7")]
    assert client.get("/api/inventory/movements", headers=tenant_a["headers"], params={"movement_type": "receipt"}).json() == []


# ---- exports
def test_sales_export_csv(client, tenant_a, tenant_b):
    location = create_location(client, tenant_a)
    integration = create_integration(client, tenant_a, location, provider="mock")
    import_sales(client, tenant_a, integration, sale_payload("S1", lines=[line("=HYPERLINK(\"x\")", "E1", quantity="2")]))
    response = client.get("/api/sales/export.csv", headers=tenant_a["headers"])
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    table = rows(response)
    assert table[0][0] == "sale_id" and len(table) == 2
    assert table[1][0] == "S1"
    assert table[1][8].startswith("'=")  # formula injection neutralised
    assert rows(client.get("/api/sales/export.csv", headers=tenant_b["headers"])) == [table[0]]


def test_movements_and_margins_export_csv(client, tenant_a):
    location = create_location(client, tenant_a)
    beef = create_product(client, tenant_a, "Beef", base_uom="KG")
    add_stock(client, tenant_a, location, beef, "5", "KG")
    table = rows(client.get("/api/inventory/movements/export.csv", headers=tenant_a["headers"]))
    assert table[0][:2] == ["id", "occurred_at"] and table[1][4] == "adjustment"
    assert rows(client.get("/api/reports/margins.csv", headers=tenant_a["headers"]))[0][1] == "product_name"


# ---- alerts
def alerts(client, tenant):
    response = client.get("/api/alerts", headers=tenant["headers"])
    assert response.status_code == 200
    return response.json()


def kinds(client, tenant):
    return {a["type"] for a in alerts(client, tenant)}


def test_no_alerts_for_a_clean_tenant(client, tenant_a):
    assert alerts(client, tenant_a) == []


def test_low_and_negative_stock_alerts(client, tenant_a):
    location = create_location(client, tenant_a)
    beef = client.post("/api/products", headers=tenant_a["headers"], json={"name": "Beef", "base_uom": "KG", "reorder_level": "5"}).json()
    add_stock(client, tenant_a, location, beef, "4", "KG")
    assert kinds(client, tenant_a) == {"low_stock"}
    add_stock(client, tenant_a, location, beef, "-10", "KG")
    assert kinds(client, tenant_a) == {"negative_stock"}
    add_stock(client, tenant_a, location, beef, "20", "KG")
    assert alerts(client, tenant_a) == []


def test_sync_failure_pause_and_stale_alerts(client, tenant_a):
    location = create_location(client, tenant_a)
    failed = create_integration(client, tenant_a, location, provider="nonexistent")
    client.post(f"/api/integrations/pos/{failed['id']}/sync", headers=tenant_a["headers"])
    assert "sync_failed" in kinds(client, tenant_a)

    with SessionLocal() as db:
        row = db.get(POSIntegration, failed["id"])
        row.sync_paused_reason = "Paused after 5 failures"
        db.commit()
    assert "sync_paused" in kinds(client, tenant_a)

    healthy = client.post(
        "/api/integrations/pos", headers=tenant_a["headers"],
        json={"location_id": location["id"], "provider": "mock", "name": "ok", "sync_interval_minutes": 10},
    ).json()
    with SessionLocal() as db:
        row = db.get(POSIntegration, healthy["id"])
        row.last_synced_at = datetime.now(timezone.utc) - timedelta(minutes=45)
        db.commit()
    assert "sync_stale" in kinds(client, tenant_a)


def test_unmatched_and_missing_cost_and_failed_webhook_alerts(client, tenant_a):
    location = create_location(client, tenant_a)
    integration = create_integration(client, tenant_a, location, provider="mock")
    import_sales(client, tenant_a, integration, sale_payload("S1", lines=[line("Mystery", "NOPE")]))
    burger = create_product(client, tenant_a, "Burger")
    beef = create_product(client, tenant_a, "Beef", base_uom="KG")
    create_recipe(client, tenant_a, burger, [{"ingredient_product_id": beef["id"], "quantity": "0.2", "uom": "KG"}])
    found = {a["type"]: a for a in alerts(client, tenant_a)}
    assert {"unmatched_products", "missing_cost"} <= set(found)
    assert found["missing_cost"]["entity_id"] == beef["id"]
    client.post(
        "/api/costs/products", headers=tenant_a["headers"],
        json={"product_id": beef["id"], "unit_cost": "5", "effective_from": "2026-01-01T00:00:00Z"},
    )
    assert "missing_cost" not in kinds(client, tenant_a)


def test_alerts_are_tenant_scoped_and_sorted_by_severity(client, tenant_a, tenant_b):
    location = create_location(client, tenant_a)
    beef = client.post("/api/products", headers=tenant_a["headers"], json={"name": "Beef", "base_uom": "KG", "reorder_level": "5"}).json()
    add_stock(client, tenant_a, location, beef, "-1", "KG")
    integration = create_integration(client, tenant_a, location, provider="mock")
    import_sales(client, tenant_a, integration, sale_payload("S1", lines=[line("Mystery", "NOPE")]))
    severities = [a["severity"] for a in alerts(client, tenant_a)]
    assert severities == sorted(severities, key=["critical", "warning", "info"].index)
    assert alerts(client, tenant_b) == []
