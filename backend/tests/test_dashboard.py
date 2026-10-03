from decimal import Decimal

from tests.conftest import (
    add_stock,
    create_integration,
    create_location,
    create_product,
    import_sales,
    line,
    sale_payload,
)
from tests.test_costing import set_cost


def summary(client, tenant):
    response = client.get("/api/dashboard/summary", headers=tenant["headers"])
    assert response.status_code == 200
    return response.json()


def test_empty_dashboard(client, tenant_a):
    body = summary(client, tenant_a)
    assert body["sales_count"] == 0
    assert Decimal(body["average_ticket"]) == 0
    assert Decimal(body["stock_value"]) == 0


def test_sales_totals_and_average_ticket(client, tenant_a):
    location = create_location(client, tenant_a)
    integration = create_integration(client, tenant_a, location)
    import_sales(
        client, tenant_a, integration,
        sale_payload("S1", net="100.00", tax="19.00"),
        sale_payload("S2", net="50.00", tax="9.50"),
    )
    body = summary(client, tenant_a)
    assert body["sales_count"] == 2
    assert Decimal(body["revenue"]) == Decimal("150.00")
    assert Decimal(body["tax"]) == Decimal("28.50")
    assert Decimal(body["gross_revenue"]) == Decimal("178.50")
    assert Decimal(body["average_ticket"]) == Decimal("89.25")


def test_unmatched_products_counts_distinct_external_ids(client, tenant_a):
    location = create_location(client, tenant_a)
    integration = create_integration(client, tenant_a, location)
    import_sales(
        client, tenant_a, integration,
        sale_payload("S1", lines=[line("A", "X1"), line("B", "X2")]),
        sale_payload("S2", lines=[line("A", "X1")]),
    )
    assert summary(client, tenant_a)["unmatched_products"] == 2


def test_stock_value_uses_effective_costs(client, tenant_a):
    location = create_location(client, tenant_a)
    beef = create_product(client, tenant_a, "Beef", base_uom="KG")
    add_stock(client, tenant_a, location, beef, "10", "KG")
    set_cost(client, tenant_a, beef, "5", "2026-01-01T00:00:00Z")
    set_cost(client, tenant_a, beef, "8", "2026-02-01T00:00:00Z")
    body = summary(client, tenant_a)
    assert body["stock_items"] == 1
    assert Decimal(body["stock_value"]) == Decimal("80")


def test_stock_value_prefers_location_cost_over_newer_global_cost(client, tenant_a):
    location = create_location(client, tenant_a)
    beef = create_product(client, tenant_a, "Beef", base_uom="KG")
    add_stock(client, tenant_a, location, beef, "10", "KG")
    set_cost(client, tenant_a, beef, "5", "2026-01-01T00:00:00Z", location=location)
    set_cost(client, tenant_a, beef, "8", "2026-02-01T00:00:00Z")
    assert Decimal(summary(client, tenant_a)["stock_value"]) == Decimal("50")


def test_stock_value_ignores_future_costs(client, tenant_a):
    location = create_location(client, tenant_a)
    beef = create_product(client, tenant_a, "Beef", base_uom="KG")
    add_stock(client, tenant_a, location, beef, "10", "KG")
    set_cost(client, tenant_a, beef, "5", "2026-01-01T00:00:00Z")
    set_cost(client, tenant_a, beef, "500", "2999-01-01T00:00:00Z")
    assert Decimal(summary(client, tenant_a)["stock_value"]) == Decimal("50")
