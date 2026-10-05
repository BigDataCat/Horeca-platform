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
from tests.test_costing import recipe_cost, set_cost


def qty(client, tenant, location, product):
    row = get_stock(client, tenant, location, product)
    return Decimal(row["quantity"]) if row else Decimal("0")


def sauce_setup(client, tenant):
    location = create_location(client, tenant)
    sauce = create_product(client, tenant, "Sauce", base_uom="KG")
    mayo = create_product(client, tenant, "Mayo", base_uom="KG")
    herbs = create_product(client, tenant, "Herbs", base_uom="KG")
    add_stock(client, tenant, location, mayo, "10", "KG")
    add_stock(client, tenant, location, herbs, "5", "KG")
    # per 1 kg of sauce: 0.8 kg mayo + 0.2 kg herbs
    create_recipe(client, tenant, sauce, [
        {"ingredient_product_id": mayo["id"], "quantity": "0.8", "uom": "KG"},
        {"ingredient_product_id": herbs["id"], "quantity": "0.2", "uom": "KG"},
    ])
    return location, sauce, mayo, herbs


def produce(client, tenant, location, product, quantity, uom="KG"):
    return client.post(
        "/api/inventory/production", headers=tenant["headers"],
        json={"location_id": location["id"], "product_id": product["id"], "quantity": quantity, "uom": uom},
    )


def test_production_consumes_ingredients_and_stocks_the_product(client, tenant_a):
    location, sauce, mayo, herbs = sauce_setup(client, tenant_a)
    response = produce(client, tenant_a, location, sauce, "5")
    assert response.status_code == 201, response.text
    assert qty(client, tenant_a, location, sauce) == Decimal("5")
    assert qty(client, tenant_a, location, mayo) == Decimal("6")
    assert qty(client, tenant_a, location, herbs) == Decimal("4")
    kinds = sorted(m["movement_type"] for m in client.get("/api/inventory/movements", headers=tenant_a["headers"]).json() if m["movement_type"].startswith("production"))
    assert kinds == ["production_consume", "production_consume", "production_output"]
    assert len(client.get("/api/inventory/production", headers=tenant_a["headers"]).json()) == 1


def test_production_records_cost_that_feeds_parent_recipe_costing(client, tenant_a):
    location, sauce, mayo, herbs = sauce_setup(client, tenant_a)
    set_cost(client, tenant_a, mayo, "10")
    set_cost(client, tenant_a, herbs, "40")
    order = produce(client, tenant_a, location, sauce, "5").json()
    assert Decimal(order["unit_cost"]) == Decimal("16")  # 0.8*10 + 0.2*40
    burger = create_product(client, tenant_a, "Burger")
    recipe = create_recipe(client, tenant_a, burger, [{"ingredient_product_id": sauce["id"], "quantity": "0.05", "uom": "KG"}])
    assert Decimal(recipe_cost(client, tenant_a, recipe, location)["total_cost"]) == Decimal("0.8")


def test_missing_ingredient_cost_leaves_unit_cost_unknown(client, tenant_a):
    location, sauce, mayo, herbs = sauce_setup(client, tenant_a)
    set_cost(client, tenant_a, mayo, "10")  # herbs have no cost
    order = produce(client, tenant_a, location, sauce, "1").json()
    assert order["unit_cost"] is None
    assert client.get("/api/costs/products", headers=tenant_a["headers"]).json().__len__() == 1


def test_selling_a_dish_consumes_the_semi_finished_stock(client, tenant_a):
    location, sauce, mayo, herbs = sauce_setup(client, tenant_a)
    produce(client, tenant_a, location, sauce, "5")
    burger = create_product(client, tenant_a, "Burger", sku="BURGER")
    create_recipe(client, tenant_a, burger, [{"ingredient_product_id": sauce["id"], "quantity": "0.05", "uom": "KG"}])
    integration = create_integration(client, tenant_a, location, provider="mock")
    import_sales(client, tenant_a, integration, sale_payload("S1", lines=[line("Burger", "BURGER", quantity="10")]))
    assert qty(client, tenant_a, location, sauce) == Decimal("4.5")


def test_production_rules(client, tenant_a, tenant_b, employee_a):
    location, sauce, mayo, herbs = sauce_setup(client, tenant_a)
    plain = create_product(client, tenant_a, "Plain")
    assert produce(client, tenant_a, location, plain, "1").status_code == 400          # no recipe
    assert produce(client, tenant_a, location, sauce, "50").status_code == 400         # not enough mayo
    assert qty(client, tenant_a, location, mayo) == Decimal("10")                      # nothing consumed
    assert produce(client, tenant_a, location, sauce, "0").status_code == 422
    assert produce(client, tenant_a, location, sauce, "1", uom="G").status_code == 400  # no conversion
    assert produce(client, employee_a, location, sauce, "1").status_code == 403
    assert produce(client, tenant_b, location, sauce, "1").status_code == 404
    assert client.get("/api/inventory/production", headers=tenant_b["headers"]).json() == []


def test_recipe_cycles_are_rejected(client, tenant_a):
    a = create_product(client, tenant_a, "A")
    b = create_product(client, tenant_a, "B")
    c = create_product(client, tenant_a, "C")

    def body(product, ingredient):
        return {"product_id": product["id"], "name": "r", "lines": [{"ingredient_product_id": ingredient["id"], "quantity": "1", "uom": "EA"}]}

    assert client.post("/api/recipes", headers=tenant_a["headers"], json=body(a, a)).status_code == 400  # itself
    assert client.post("/api/recipes", headers=tenant_a["headers"], json=body(a, b)).status_code == 201
    assert client.post("/api/recipes", headers=tenant_a["headers"], json=body(b, c)).status_code == 201
    assert client.post("/api/recipes", headers=tenant_a["headers"], json=body(c, a)).status_code == 400  # A->B->C->A
    assert client.post("/api/recipes", headers=tenant_a["headers"], json=body(c, b)).status_code == 400  # B->C->B
