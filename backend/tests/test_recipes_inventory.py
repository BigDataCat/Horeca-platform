from datetime import datetime, timezone
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
)


def burger_setup(client, tenant):
    location = create_location(client, tenant)
    integration = create_integration(client, tenant, location)
    burger = create_product(client, tenant, "Burger", sku="BURGER")
    beef = create_product(client, tenant, "Beef", sku="BEEF", base_uom="KG")
    add_stock(client, tenant, location, beef, "10", "KG")
    return location, integration, burger, beef


def sell(client, tenant, integration, quantity="1", external_id="S1"):
    response = import_sales(
        client, tenant, integration,
        sale_payload(external_id, lines=[line("Burger", "BURGER", quantity=quantity)]),
    )
    assert response.status_code == 200, response.text


def test_manual_adjustment_updates_balance_and_ledger(client, tenant_a, manager_a):
    location = create_location(client, tenant_a)
    beef = create_product(client, tenant_a, "Beef", base_uom="KG")
    add_stock(client, tenant_a, location, beef, "10", "KG")
    add_stock(client, tenant_a, location, beef, "-3.5", "KG")
    assert Decimal(get_stock(client, tenant_a, location, beef)["quantity"]) == Decimal("6.5")
    movements = client.get("/api/inventory/movements", headers=tenant_a["headers"]).json()
    assert sorted(Decimal(m["quantity"]) for m in movements) == [Decimal("-3.5"), Decimal("10")]


def test_zero_adjustment_rejected(client, tenant_a):
    location = create_location(client, tenant_a)
    beef = create_product(client, tenant_a, "Beef", base_uom="KG")
    response = client.post(
        "/api/inventory/adjustments",
        headers=tenant_a["headers"],
        json={"location_id": location["id"], "product_id": beef["id"], "quantity": "0", "uom": "KG"},
    )
    assert response.status_code == 400


def test_adjustment_in_foreign_uom_is_rejected(client, tenant_a):
    """Stock is kept in the product base UOM; mixing units would corrupt the balance."""
    location = create_location(client, tenant_a)
    beef = create_product(client, tenant_a, "Beef", base_uom="KG")
    add_stock(client, tenant_a, location, beef, "10", "KG")
    response = client.post(
        "/api/inventory/adjustments",
        headers=tenant_a["headers"],
        json={"location_id": location["id"], "product_id": beef["id"], "quantity": "500", "uom": "G"},
    )
    assert response.status_code == 400
    assert Decimal(get_stock(client, tenant_a, location, beef)["quantity"]) == Decimal("10")


def test_recipe_validation(client, tenant_a):
    burger = create_product(client, tenant_a, "Burger")
    beef = create_product(client, tenant_a, "Beef", base_uom="KG")
    bad_waste = client.post(
        "/api/recipes",
        headers=tenant_a["headers"],
        json={
            "product_id": burger["id"],
            "name": "R",
            "lines": [{"ingredient_product_id": beef["id"], "quantity": "1", "uom": "KG", "waste_factor": "1.5"}],
        },
    )
    assert bad_waste.status_code == 422
    no_lines = client.post(
        "/api/recipes", headers=tenant_a["headers"], json={"product_id": burger["id"], "name": "R", "lines": []}
    )
    assert no_lines.status_code == 422
    zero_qty = client.post(
        "/api/recipes",
        headers=tenant_a["headers"],
        json={"product_id": burger["id"], "name": "R", "lines": [{"ingredient_product_id": beef["id"], "quantity": "0", "uom": "KG"}]},
    )
    assert zero_qty.status_code == 422


def test_sale_consumes_ingredients(client, tenant_a):
    location, integration, burger, beef = burger_setup(client, tenant_a)
    create_recipe(client, tenant_a, burger, [{"ingredient_product_id": beef["id"], "quantity": "0.2", "uom": "KG"}])
    sell(client, tenant_a, integration, quantity="3")
    assert Decimal(get_stock(client, tenant_a, location, beef)["quantity"]) == Decimal("9.4")
    movement = [m for m in client.get("/api/inventory/movements", headers=tenant_a["headers"]).json() if m["movement_type"] == "recipe_consumption"]
    assert len(movement) == 1
    assert Decimal(movement[0]["quantity"]) == Decimal("-0.6")
    assert movement[0]["reference_type"] == "sale"
    assert movement[0]["reference_id"] == "S1"


def test_waste_factor_increases_consumption(client, tenant_a):
    location, integration, burger, beef = burger_setup(client, tenant_a)
    create_recipe(client, tenant_a, burger, [{"ingredient_product_id": beef["id"], "quantity": "0.2", "uom": "KG", "waste_factor": "0.1"}])
    sell(client, tenant_a, integration, quantity="1")
    assert Decimal(get_stock(client, tenant_a, location, beef)["quantity"]) == Decimal("9.78")


def test_ingredient_uom_conversion_in_recipe(client, tenant_a):
    location, integration, burger, beef = burger_setup(client, tenant_a)
    client.post(
        "/api/product-mappings/uom-conversions",
        headers=tenant_a["headers"],
        json={"product_id": beef["id"], "from_uom": "G", "to_uom": "KG", "factor": "0.001"},
    )
    create_recipe(client, tenant_a, burger, [{"ingredient_product_id": beef["id"], "quantity": "200", "uom": "G"}])
    sell(client, tenant_a, integration, quantity="2")
    assert Decimal(get_stock(client, tenant_a, location, beef)["quantity"]) == Decimal("9.6")


def test_missing_ingredient_conversion_fails_whole_import_without_side_effects(client, tenant_a):
    location, integration, burger, beef = burger_setup(client, tenant_a)
    create_recipe(client, tenant_a, burger, [{"ingredient_product_id": beef["id"], "quantity": "200", "uom": "G"}])
    response = client.post(
        "/api/sales/import",
        headers=tenant_a["headers"],
        json={"integration_id": integration["id"], "sales": [sale_payload("S1", lines=[line("Burger", "BURGER")])]},
    )
    assert response.status_code == 400
    assert "No UOM conversion" in response.json()["detail"]
    assert client.get("/api/sales", headers=tenant_a["headers"]).json() == []
    assert Decimal(get_stock(client, tenant_a, location, beef)["quantity"]) == Decimal("10")


def test_location_recipe_takes_precedence_over_company_recipe(client, tenant_a):
    location, integration, burger, beef = burger_setup(client, tenant_a)
    create_recipe(client, tenant_a, burger, [{"ingredient_product_id": beef["id"], "quantity": "0.2", "uom": "KG"}], name="global")
    create_recipe(client, tenant_a, burger, [{"ingredient_product_id": beef["id"], "quantity": "0.5", "uom": "KG"}], location=location, name="local")
    sell(client, tenant_a, integration)
    assert Decimal(get_stock(client, tenant_a, location, beef)["quantity"]) == Decimal("9.5")


def test_company_recipe_used_when_no_location_recipe(client, tenant_a):
    location, integration, burger, beef = burger_setup(client, tenant_a)
    other = create_location(client, tenant_a, "Other")
    create_recipe(client, tenant_a, burger, [{"ingredient_product_id": beef["id"], "quantity": "0.2", "uom": "KG"}], name="global")
    create_recipe(client, tenant_a, burger, [{"ingredient_product_id": beef["id"], "quantity": "0.5", "uom": "KG"}], location=other, name="other-site")
    sell(client, tenant_a, integration)
    assert Decimal(get_stock(client, tenant_a, location, beef)["quantity"]) == Decimal("9.8")


def test_inactive_recipe_is_ignored(client, tenant_a):
    location, integration, burger, beef = burger_setup(client, tenant_a)
    recipe = create_recipe(client, tenant_a, burger, [{"ingredient_product_id": beef["id"], "quantity": "0.2", "uom": "KG"}])
    client.delete(f"/api/recipes/{recipe['id']}", headers=tenant_a["headers"])
    sell(client, tenant_a, integration)
    assert Decimal(get_stock(client, tenant_a, location, beef)["quantity"]) == Decimal("10")


def test_duplicate_sale_does_not_consume_twice(client, tenant_a):
    location, integration, burger, beef = burger_setup(client, tenant_a)
    create_recipe(client, tenant_a, burger, [{"ingredient_product_id": beef["id"], "quantity": "0.2", "uom": "KG"}])
    sell(client, tenant_a, integration)
    sell(client, tenant_a, integration)
    assert Decimal(get_stock(client, tenant_a, location, beef)["quantity"]) == Decimal("9.8")


def test_consumption_movement_is_dated_at_the_sale_time(client, tenant_a):
    location, integration, burger, beef = burger_setup(client, tenant_a)
    create_recipe(client, tenant_a, burger, [{"ingredient_product_id": beef["id"], "quantity": "0.2", "uom": "KG"}])
    import_sales(
        client, tenant_a, integration,
        sale_payload("S1", occurred_at="2026-01-05T12:00:00Z", lines=[line("Burger", "BURGER")]),
    )
    movement = next(
        m for m in client.get("/api/inventory/movements", headers=tenant_a["headers"]).json()
        if m["movement_type"] == "recipe_consumption"
    )
    occurred = datetime.fromisoformat(movement["occurred_at"].replace("Z", "+00:00"))
    assert occurred == datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc)
