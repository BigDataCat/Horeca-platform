from decimal import Decimal

from tests.conftest import (
    create_integration,
    create_location,
    create_product,
    create_recipe,
    import_sales,
    line,
    sale_payload,
)
from tests.test_costing import set_cost


def setup(client, tenant):
    location = create_location(client, tenant)
    integration = create_integration(client, tenant, location, provider="mock")
    burger = create_product(client, tenant, "Burger", sku="BURGER")
    beef = create_product(client, tenant, "Beef", base_uom="KG")
    create_recipe(client, tenant, burger, [{"ingredient_product_id": beef["id"], "quantity": "0.2", "uom": "KG", "waste_factor": "0.1"}])
    return location, integration, burger, beef


def margins(client, tenant, **params):
    response = client.get("/api/reports/margins", headers=tenant["headers"], params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_margin_report_computes_cost_and_food_cost_pct(client, tenant_a):
    location, integration, burger, beef = setup(client, tenant_a)
    set_cost(client, tenant_a, beef, "50")
    import_sales(client, tenant_a, integration, sale_payload("S1", lines=[line("Burger", "BURGER", quantity="10", price="10")]))
    rows = margins(client, tenant_a)
    assert len(rows) == 1
    row = rows[0]
    assert Decimal(row["quantity_sold"]) == 10
    assert Decimal(row["revenue"]) == Decimal("100")
    assert Decimal(row["cost"]) == Decimal("110")  # 0.2 * 1.1 * 50 = 11 per burger
    assert Decimal(row["margin"]) == Decimal("-10")
    assert Decimal(row["food_cost_pct"]) == Decimal("110")


def test_missing_cost_or_recipe_gives_null_cost(client, tenant_a):
    location, integration, burger, beef = setup(client, tenant_a)
    create_product(client, tenant_a, "Water", sku="WATER")
    import_sales(
        client, tenant_a, integration,
        sale_payload("S1", lines=[line("Burger", "BURGER"), line("Water", "WATER")]),
    )
    rows = {r["product_name"]: r for r in margins(client, tenant_a)}
    assert rows["Burger"]["cost"] is None and rows["Burger"]["margin"] is None
    assert rows["Water"]["cost"] is None
    assert Decimal(rows["Water"]["revenue"]) == Decimal("10")


def test_cancelled_sales_and_unmatched_lines_are_excluded(client, tenant_a):
    location, integration, burger, beef = setup(client, tenant_a)
    set_cost(client, tenant_a, beef, "50")
    import_sales(client, tenant_a, integration, sale_payload("S1", lines=[line("Burger", "BURGER"), line("Mystery", "NOPE")]))
    sale = client.get("/api/sales", headers=tenant_a["headers"]).json()[0]
    assert len(margins(client, tenant_a)) == 1
    client.post(f"/api/sales/{sale['id']}/status", headers=tenant_a["headers"], json={"status": "cancelled"})
    assert margins(client, tenant_a) == []


def test_filters_by_date_and_location(client, tenant_a):
    location, integration, burger, beef = setup(client, tenant_a)
    set_cost(client, tenant_a, beef, "50")
    import_sales(client, tenant_a, integration, sale_payload("S1", occurred_at="2026-01-10T10:00:00Z", lines=[line("Burger", "BURGER")]))
    import_sales(client, tenant_a, integration, sale_payload("S2", occurred_at="2026-03-10T10:00:00Z", lines=[line("Burger", "BURGER", quantity="3")]))
    assert Decimal(margins(client, tenant_a)[0]["quantity_sold"]) == 4
    only_march = margins(client, tenant_a, date_from="2026-02-01T00:00:00Z")
    assert Decimal(only_march[0]["quantity_sold"]) == 3
    only_jan = margins(client, tenant_a, date_to="2026-02-01T00:00:00Z")
    assert Decimal(only_jan[0]["quantity_sold"]) == 1
    other_location = create_location(client, tenant_a, "Other")
    assert margins(client, tenant_a, location_id=other_location["id"]) == []


def test_report_is_tenant_scoped(client, tenant_a, tenant_b):
    location, integration, burger, beef = setup(client, tenant_a)
    import_sales(client, tenant_a, integration, sale_payload("S1", lines=[line("Burger", "BURGER")]))
    assert margins(client, tenant_b) == []
