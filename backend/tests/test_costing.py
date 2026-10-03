from decimal import Decimal

from tests.conftest import create_location, create_product, create_recipe


def set_cost(client, tenant, product, cost, effective_from="2026-01-01T00:00:00Z", location=None):
    response = client.post(
        "/api/costs/products",
        headers=tenant["headers"],
        json={
            "product_id": product["id"],
            "location_id": location["id"] if location else None,
            "unit_cost": cost,
            "effective_from": effective_from,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def recipe_cost(client, tenant, recipe, location=None):
    params = {"location_id": location["id"]} if location else {}
    response = client.get(f"/api/costs/recipes/{recipe['id']}", headers=tenant["headers"], params=params)
    assert response.status_code == 200, response.text
    return response.json()


def burger_recipe(client, tenant, waste="0"):
    burger = create_product(client, tenant, "Burger")
    beef = create_product(client, tenant, "Beef", base_uom="KG")
    bun = create_product(client, tenant, "Bun")
    recipe = create_recipe(
        client, tenant, burger,
        [
            {"ingredient_product_id": beef["id"], "quantity": "0.2", "uom": "KG", "waste_factor": waste},
            {"ingredient_product_id": bun["id"], "quantity": "1", "uom": "EA"},
        ],
    )
    return recipe, beef, bun


def test_recipe_cost_sums_lines(client, tenant_a):
    recipe, beef, bun = burger_recipe(client, tenant_a)
    set_cost(client, tenant_a, beef, "50")
    set_cost(client, tenant_a, bun, "1.5")
    result = recipe_cost(client, tenant_a, recipe)
    assert Decimal(result["total_cost"]) == Decimal("11.5")
    assert {Decimal(l["line_cost"]) for l in result["lines"]} == {Decimal("10"), Decimal("1.5")}


def test_recipe_cost_includes_waste(client, tenant_a):
    recipe, beef, bun = burger_recipe(client, tenant_a, waste="0.1")
    set_cost(client, tenant_a, beef, "50")
    set_cost(client, tenant_a, bun, "1")
    assert Decimal(recipe_cost(client, tenant_a, recipe)["total_cost"]) == Decimal("12")


def test_missing_cost_gives_null_total(client, tenant_a):
    recipe, beef, bun = burger_recipe(client, tenant_a)
    set_cost(client, tenant_a, beef, "50")
    result = recipe_cost(client, tenant_a, recipe)
    assert result["total_cost"] is None


def test_missing_cost_does_not_hide_costs_of_other_lines(client, tenant_a):
    recipe, beef, bun = burger_recipe(client, tenant_a)
    set_cost(client, tenant_a, bun, "1.5")
    result = recipe_cost(client, tenant_a, recipe)
    by_ingredient = {l["ingredient_product_id"]: l for l in result["lines"]}
    assert by_ingredient[beef["id"]]["unit_cost"] is None
    assert Decimal(by_ingredient[bun["id"]]["unit_cost"]) == Decimal("1.5")


def test_latest_effective_cost_wins_and_future_costs_are_ignored(client, tenant_a):
    recipe, beef, bun = burger_recipe(client, tenant_a)
    set_cost(client, tenant_a, bun, "1", "2026-01-01T00:00:00Z")
    set_cost(client, tenant_a, bun, "2", "2026-03-01T00:00:00Z")
    set_cost(client, tenant_a, bun, "999", "2999-01-01T00:00:00Z")
    set_cost(client, tenant_a, beef, "10")
    result = recipe_cost(client, tenant_a, recipe)
    by_ingredient = {l["ingredient_product_id"]: l for l in result["lines"]}
    assert Decimal(by_ingredient[bun["id"]]["unit_cost"]) == Decimal("2")


def test_location_cost_overrides_global_cost(client, tenant_a):
    recipe, beef, bun = burger_recipe(client, tenant_a)
    location = create_location(client, tenant_a)
    set_cost(client, tenant_a, beef, "50")
    set_cost(client, tenant_a, bun, "1")
    set_cost(client, tenant_a, bun, "3", location=location)
    local = recipe_cost(client, tenant_a, recipe, location)
    by_ingredient = {l["ingredient_product_id"]: l for l in local["lines"]}
    assert Decimal(by_ingredient[bun["id"]]["unit_cost"]) == Decimal("3")
    assert Decimal(by_ingredient[beef["id"]]["unit_cost"]) == Decimal("50")
    glob = recipe_cost(client, tenant_a, recipe)
    assert Decimal({l["ingredient_product_id"]: l for l in glob["lines"]}[bun["id"]]["unit_cost"]) == Decimal("1")


def test_cost_validation(client, tenant_a):
    product = create_product(client, tenant_a)
    for bad in ["0", "-1"]:
        response = client.post(
            "/api/costs/products",
            headers=tenant_a["headers"],
            json={"product_id": product["id"], "unit_cost": bad, "effective_from": "2026-01-01T00:00:00Z"},
        )
        assert response.status_code == 422


def test_company_wide_view_falls_back_to_latest_location_cost(client, tenant_a):
    """A goods receipt records a location cost; a company-wide recipe must still be costable."""
    recipe, beef, bun = burger_recipe(client, tenant_a)
    main = create_location(client, tenant_a, "Main")
    other = create_location(client, tenant_a, "Other")
    set_cost(client, tenant_a, beef, "40", "2026-01-01T00:00:00Z", location=other)
    set_cost(client, tenant_a, beef, "50", "2026-02-01T00:00:00Z", location=main)
    set_cost(client, tenant_a, bun, "1", location=main)
    result = recipe_cost(client, tenant_a, recipe)
    by_ingredient = {l["ingredient_product_id"]: l for l in result["lines"]}
    assert Decimal(by_ingredient[beef["id"]]["unit_cost"]) == Decimal("50")  # newest across locations
    assert Decimal(result["total_cost"]) == Decimal("11")
    # a specific location still only uses its own or global costs
    other_view = recipe_cost(client, tenant_a, recipe, other)
    assert other_view["total_cost"] is None  # no bun cost for "Other" and no global cost
