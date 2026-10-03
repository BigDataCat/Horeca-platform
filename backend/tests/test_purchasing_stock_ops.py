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
from tests.test_costing import recipe_cost


def qty(client, tenant, location, product):
    row = get_stock(client, tenant, location, product)
    return Decimal(row["quantity"]) if row else Decimal("0")


def post_receipt(client, tenant, location, lines, **extra):
    return client.post(
        "/api/inventory/receipts",
        headers=tenant["headers"],
        json={"location_id": location["id"], "lines": lines, **extra},
    )


def test_supplier_crud_and_uniqueness(client, tenant_a, tenant_b, employee_a):
    created = client.post("/api/suppliers", headers=tenant_a["headers"], json={"name": "Metro"})
    assert created.status_code == 201
    assert client.post("/api/suppliers", headers=tenant_a["headers"], json={"name": "Metro"}).status_code == 409
    assert client.post("/api/suppliers", headers=tenant_b["headers"], json={"name": "Metro"}).status_code == 201
    assert client.post("/api/suppliers", headers=employee_a["headers"], json={"name": "X"}).status_code == 403
    supplier_id = created.json()["id"]
    assert client.patch(f"/api/suppliers/{supplier_id}", headers=tenant_a["headers"], json={"phone": "123"}).json()["phone"] == "123"
    assert client.patch(f"/api/suppliers/{supplier_id}", headers=tenant_b["headers"], json={"phone": "1"}).status_code == 404
    assert [s["name"] for s in client.get("/api/suppliers", headers=tenant_b["headers"]).json()] == ["Metro"]
    assert len(client.get("/api/suppliers", headers=employee_a["headers"]).json()) == 1


def test_receipt_increases_stock_and_sets_cost(client, tenant_a):
    location = create_location(client, tenant_a)
    beef = create_product(client, tenant_a, "Beef", base_uom="KG")
    supplier = client.post("/api/suppliers", headers=tenant_a["headers"], json={"name": "Metro"}).json()
    response = post_receipt(
        client, tenant_a, location,
        [{"product_id": beef["id"], "quantity": "10", "uom": "KG", "unit_cost": "42.5"}],
        supplier_id=supplier["id"], document_number="NIR-1",
    )
    assert response.status_code == 201, response.text
    assert qty(client, tenant_a, location, beef) == Decimal("10")
    costs = client.get("/api/costs/products", headers=tenant_a["headers"]).json()
    assert len(costs) == 1 and Decimal(costs[0]["unit_cost"]) == Decimal("42.5")
    assert costs[0]["location_id"] == location["id"]
    movements = client.get("/api/inventory/movements", headers=tenant_a["headers"]).json()
    assert [m["movement_type"] for m in movements] == ["receipt"]
    assert client.get(f"/api/inventory/receipts/{response.json()['id']}", headers=tenant_a["headers"]).status_code == 200


def test_receipt_converts_uom_and_cost_to_base_unit(client, tenant_a):
    location = create_location(client, tenant_a)
    beer = create_product(client, tenant_a, "Beer", base_uom="EA")
    client.post(
        "/api/product-mappings/uom-conversions",
        headers=tenant_a["headers"],
        json={"product_id": beer["id"], "from_uom": "CASE", "to_uom": "EA", "factor": "24"},
    )
    response = post_receipt(client, tenant_a, location, [{"product_id": beer["id"], "quantity": "2", "uom": "CASE", "unit_cost": "48"}])
    assert response.status_code == 201, response.text
    assert qty(client, tenant_a, location, beer) == Decimal("48")
    assert Decimal(response.json()["lines"][0]["unit_cost"]) == Decimal("2")


def test_receipt_without_conversion_is_rejected_without_side_effects(client, tenant_a):
    location = create_location(client, tenant_a)
    beer = create_product(client, tenant_a, "Beer", base_uom="EA")
    response = post_receipt(client, tenant_a, location, [{"product_id": beer["id"], "quantity": "2", "uom": "CASE", "unit_cost": "48"}])
    assert response.status_code == 400
    assert client.get("/api/inventory/receipts", headers=tenant_a["headers"]).json() == []
    assert client.get("/api/costs/products", headers=tenant_a["headers"]).json() == []


def test_receipt_cost_feeds_recipe_costing(client, tenant_a):
    location = create_location(client, tenant_a)
    burger = create_product(client, tenant_a, "Burger")
    beef = create_product(client, tenant_a, "Beef", base_uom="KG")
    recipe = create_recipe(client, tenant_a, burger, [{"ingredient_product_id": beef["id"], "quantity": "0.2", "uom": "KG"}])
    post_receipt(client, tenant_a, location, [{"product_id": beef["id"], "quantity": "5", "uom": "KG", "unit_cost": "50"}])
    assert Decimal(recipe_cost(client, tenant_a, recipe, location)["total_cost"]) == Decimal("10")


def test_duplicate_document_number_per_supplier_rejected(client, tenant_a):
    location = create_location(client, tenant_a)
    beef = create_product(client, tenant_a, "Beef", base_uom="KG")
    supplier = client.post("/api/suppliers", headers=tenant_a["headers"], json={"name": "Metro"}).json()
    other = client.post("/api/suppliers", headers=tenant_a["headers"], json={"name": "Selgros"}).json()
    lines = [{"product_id": beef["id"], "quantity": "1", "uom": "KG", "unit_cost": "10"}]
    assert post_receipt(client, tenant_a, location, lines, supplier_id=supplier["id"], document_number="D1").status_code == 201
    assert post_receipt(client, tenant_a, location, lines, supplier_id=supplier["id"], document_number="D1").status_code == 409
    assert post_receipt(client, tenant_a, location, lines, supplier_id=other["id"], document_number="D1").status_code == 201
    assert qty(client, tenant_a, location, beef) == Decimal("2")


def test_receipt_validation_and_isolation(client, tenant_a, tenant_b, employee_a):
    location = create_location(client, tenant_a)
    beef = create_product(client, tenant_a, "Beef", base_uom="KG")
    ok_lines = [{"product_id": beef["id"], "quantity": "1", "uom": "KG", "unit_cost": "10"}]
    assert post_receipt(client, employee_a, location, ok_lines).status_code == 403
    assert post_receipt(client, tenant_b, location, ok_lines).status_code == 404
    other_location = create_location(client, tenant_b)
    assert post_receipt(client, tenant_b, other_location, ok_lines).status_code == 404  # foreign product
    bad = [{"product_id": beef["id"], "quantity": "0", "uom": "KG", "unit_cost": "10"}]
    assert post_receipt(client, tenant_a, location, bad).status_code == 422
    assert post_receipt(client, tenant_a, location, []).status_code == 422
    supplier_b = client.post("/api/suppliers", headers=tenant_b["headers"], json={"name": "B"}).json()
    assert post_receipt(client, tenant_a, location, ok_lines, supplier_id=supplier_b["id"]).status_code == 404
    receipt = post_receipt(client, tenant_a, location, ok_lines).json()
    assert client.get(f"/api/inventory/receipts/{receipt['id']}", headers=tenant_b["headers"]).status_code == 404
    assert client.get("/api/inventory/receipts", headers=tenant_b["headers"]).json() == []


def test_stock_count_records_differences(client, tenant_a):
    location = create_location(client, tenant_a)
    beef = create_product(client, tenant_a, "Beef", base_uom="KG")
    oil = create_product(client, tenant_a, "Oil", base_uom="L")
    add_stock(client, tenant_a, location, beef, "10", "KG")
    response = client.post(
        "/api/inventory/counts",
        headers=tenant_a["headers"],
        json={
            "location_id": location["id"],
            "lines": [
                {"product_id": beef["id"], "counted_quantity": "8.5", "uom": "KG"},
                {"product_id": oil["id"], "counted_quantity": "3", "uom": "L"},
            ],
        },
    )
    assert response.status_code == 201, response.text
    by_product = {l["product_id"]: l for l in response.json()["lines"]}
    assert Decimal(by_product[beef["id"]]["difference"]) == Decimal("-1.5")
    assert Decimal(by_product[oil["id"]]["expected_quantity"]) == 0
    assert Decimal(by_product[oil["id"]]["difference"]) == Decimal("3")
    assert qty(client, tenant_a, location, beef) == Decimal("8.5")
    assert qty(client, tenant_a, location, oil) == Decimal("3")
    kinds = [m["movement_type"] for m in client.get("/api/inventory/movements", headers=tenant_a["headers"]).json()]
    assert kinds.count("count_adjustment") == 2


def test_stock_count_with_no_difference_creates_no_movement_and_zero_count_allowed(client, tenant_a):
    location = create_location(client, tenant_a)
    beef = create_product(client, tenant_a, "Beef", base_uom="KG")
    add_stock(client, tenant_a, location, beef, "4", "KG")
    same = client.post(
        "/api/inventory/counts", headers=tenant_a["headers"],
        json={"location_id": location["id"], "lines": [{"product_id": beef["id"], "counted_quantity": "4", "uom": "KG"}]},
    )
    assert same.status_code == 201
    zero = client.post(
        "/api/inventory/counts", headers=tenant_a["headers"],
        json={"location_id": location["id"], "lines": [{"product_id": beef["id"], "counted_quantity": "0", "uom": "KG"}]},
    )
    assert zero.status_code == 201
    assert qty(client, tenant_a, location, beef) == 0
    kinds = [m["movement_type"] for m in client.get("/api/inventory/movements", headers=tenant_a["headers"]).json()]
    assert kinds.count("count_adjustment") == 1


def test_stock_count_rules(client, tenant_a, tenant_b, employee_a):
    location = create_location(client, tenant_a)
    beef = create_product(client, tenant_a, "Beef", base_uom="KG")
    body = {"location_id": location["id"], "lines": [{"product_id": beef["id"], "counted_quantity": "1", "uom": "KG"}]}
    assert client.post("/api/inventory/counts", headers=employee_a["headers"], json=body).status_code == 403
    assert client.post("/api/inventory/counts", headers=tenant_b["headers"], json=body).status_code == 404
    dup = {**body, "lines": body["lines"] * 2}
    assert client.post("/api/inventory/counts", headers=tenant_a["headers"], json=dup).status_code == 400
    wrong_uom = {**body, "lines": [{"product_id": beef["id"], "counted_quantity": "1", "uom": "G"}]}
    assert client.post("/api/inventory/counts", headers=tenant_a["headers"], json=wrong_uom).status_code == 400
    assert client.get("/api/inventory/counts", headers=tenant_b["headers"]).json() == []


def test_transfer_moves_stock_between_locations(client, tenant_a):
    source = create_location(client, tenant_a, "Source")
    target = create_location(client, tenant_a, "Target")
    beef = create_product(client, tenant_a, "Beef", base_uom="KG")
    add_stock(client, tenant_a, source, beef, "10", "KG")
    response = client.post(
        "/api/inventory/transfers", headers=tenant_a["headers"],
        json={"from_location_id": source["id"], "to_location_id": target["id"], "lines": [{"product_id": beef["id"], "quantity": "4", "uom": "KG"}]},
    )
    assert response.status_code == 201, response.text
    assert qty(client, tenant_a, source, beef) == Decimal("6")
    assert qty(client, tenant_a, target, beef) == Decimal("4")
    kinds = sorted(m["movement_type"] for m in client.get("/api/inventory/movements", headers=tenant_a["headers"]).json())
    assert kinds == ["adjustment", "transfer_in", "transfer_out"]


def test_transfer_rules(client, tenant_a, tenant_b, employee_a):
    source = create_location(client, tenant_a, "Source")
    target = create_location(client, tenant_a, "Target")
    foreign = create_location(client, tenant_b)
    beef = create_product(client, tenant_a, "Beef", base_uom="KG")
    add_stock(client, tenant_a, source, beef, "2", "KG")
    line_ = [{"product_id": beef["id"], "quantity": "3", "uom": "KG"}]

    def go(headers, a, b, lines):
        return client.post("/api/inventory/transfers", headers=headers, json={"from_location_id": a["id"], "to_location_id": b["id"], "lines": lines})

    assert go(tenant_a["headers"], source, target, line_).status_code == 400  # insufficient
    assert qty(client, tenant_a, source, beef) == Decimal("2")
    assert go(tenant_a["headers"], source, source, line_).status_code == 400
    assert go(tenant_a["headers"], source, foreign, line_).status_code == 404
    assert go(employee_a["headers"], source, target, line_).status_code == 403
    assert go(tenant_b["headers"], source, target, line_).status_code == 404
    assert client.get("/api/inventory/transfers", headers=tenant_b["headers"]).json() == []
