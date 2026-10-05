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


def setup(client, tenant):
    location = create_location(client, tenant)
    integration = create_integration(client, tenant, location, provider="mock")
    burger = create_product(client, tenant, "Burger", sku="BURGER")
    fries = create_product(client, tenant, "Fries", sku="FRIES")
    beef = create_product(client, tenant, "Beef", base_uom="KG")
    potato = create_product(client, tenant, "Potato", base_uom="KG")
    add_stock(client, tenant, location, beef, "10", "KG")
    add_stock(client, tenant, location, potato, "10", "KG")
    create_recipe(client, tenant, burger, [{"ingredient_product_id": beef["id"], "quantity": "0.2", "uom": "KG"}])
    create_recipe(client, tenant, fries, [{"ingredient_product_id": potato["id"], "quantity": "0.3", "uom": "KG"}])
    return location, integration, beef, potato


def make_sale(client, tenant, integration):
    # 4 burgers at 10 (net 40) + 2 fries at 5 (net 10)
    import_sales(
        client, tenant, integration,
        sale_payload(
            "S1", net="50.00", tax="9.50",
            lines=[line("Burger", "BURGER", quantity="4", price="10"), line("Fries", "FRIES", quantity="2", price="5")],
        ),
    )
    return client.get("/api/sales", headers=tenant["headers"]).json()[0]


def stock(client, tenant, location, product):
    return Decimal(get_stock(client, tenant, location, product)["quantity"])


def refund(client, tenant, sale, *pairs, reason=None):
    return client.post(
        f"/api/sales/{sale['id']}/refund-lines", headers=tenant["headers"],
        json={"lines": [{"line_id": l, "quantity": q} for l, q in pairs], "reason": reason},
    )


def test_partial_refund_returns_proportional_stock_and_revenue(client, tenant_a):
    location, integration, beef, potato = setup(client, tenant_a)
    sale = make_sale(client, tenant_a, integration)
    burger_line = next(l for l in sale["lines"] if l["product_name"] == "Burger")
    assert stock(client, tenant_a, location, beef) == Decimal("9.2")

    response = refund(client, tenant_a, sale, (burger_line["id"], "1"), reason="cold")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "partially_refunded"
    assert Decimal(body["refunded_net_value"]) == Decimal("10.00")
    assert stock(client, tenant_a, location, beef) == Decimal("9.4")
    assert stock(client, tenant_a, location, potato) == Decimal("9.4")  # fries untouched
    refunded_line = next(l for l in body["lines"] if l["id"] == burger_line["id"])
    assert Decimal(refunded_line["refunded_quantity"]) == 1

    summary = client.get("/api/dashboard/summary", headers=tenant_a["headers"]).json()
    assert summary["sales_count"] == 1 and summary["cancelled_sales"] == 0
    assert Decimal(summary["revenue"]) == Decimal("40.00")


def test_refunding_every_remaining_quantity_marks_sale_refunded_and_restores_all_stock(client, tenant_a):
    location, integration, beef, potato = setup(client, tenant_a)
    sale = make_sale(client, tenant_a, integration)
    ids = {l["product_name"]: l["id"] for l in sale["lines"]}
    refund(client, tenant_a, sale, (ids["Burger"], "3"))
    final = refund(client, tenant_a, sale, (ids["Burger"], "1"), (ids["Fries"], "2"))
    assert final.json()["status"] == "refunded"
    assert Decimal(final.json()["refunded_net_value"]) == Decimal("50.00")
    assert stock(client, tenant_a, location, beef) == Decimal("10")
    assert stock(client, tenant_a, location, potato) == Decimal("10")
    assert client.get("/api/dashboard/summary", headers=tenant_a["headers"]).json()["cancelled_sales"] == 1


def test_uneven_fractions_do_not_leak_stock_or_money(client, tenant_a):
    location, integration, beef, potato = setup(client, tenant_a)
    import_sales(client, tenant_a, integration, sale_payload("S9", net="10.00", tax="1.90", lines=[line("Burger", "BURGER", quantity="3", price="3.3333")]))
    sale = client.get("/api/sales", headers=tenant_a["headers"]).json()[0]
    lid = sale["lines"][0]["id"]
    for _ in range(3):
        assert refund(client, tenant_a, sale, (lid, "1")).status_code == 200
    final = client.get("/api/sales", headers=tenant_a["headers"]).json()[0]
    assert final["status"] == "refunded"
    assert Decimal(final["refunded_net_value"]) == Decimal(final["net_value"])
    assert stock(client, tenant_a, location, beef) == Decimal("10")


def test_cancel_after_partial_refund_restores_only_the_remainder(client, tenant_a):
    location, integration, beef, potato = setup(client, tenant_a)
    sale = make_sale(client, tenant_a, integration)
    burger_line = next(l for l in sale["lines"] if l["product_name"] == "Burger")
    refund(client, tenant_a, sale, (burger_line["id"], "2"))
    assert stock(client, tenant_a, location, beef) == Decimal("9.6")
    response = client.post(f"/api/sales/{sale['id']}/status", headers=tenant_a["headers"], json={"status": "cancelled"})
    assert response.status_code == 200
    assert stock(client, tenant_a, location, beef) == Decimal("10")  # not 10.4
    assert stock(client, tenant_a, location, potato) == Decimal("10")
    assert Decimal(response.json()["refunded_net_value"]) == Decimal("50.00")


def test_refund_validation(client, tenant_a, tenant_b, employee_a):
    location, integration, beef, potato = setup(client, tenant_a)
    sale = make_sale(client, tenant_a, integration)
    lid = sale["lines"][0]["id"]
    assert refund(client, tenant_a, sale, (lid, "99")).status_code == 400            # more than sold
    assert refund(client, tenant_a, sale, (999999, "1")).status_code == 400         # foreign line
    assert refund(client, tenant_a, sale, (lid, "1"), (lid, "1")).status_code == 400  # duplicate line
    assert client.post(f"/api/sales/{sale['id']}/refund-lines", headers=tenant_a["headers"], json={"lines": [{"line_id": lid, "quantity": "0"}]}).status_code == 422
    assert client.post(f"/api/sales/{sale['id']}/refund-lines", headers=tenant_a["headers"], json={"lines": []}).status_code == 422
    assert refund(client, employee_a, sale, (lid, "1")).status_code == 403
    assert refund(client, tenant_b, sale, (lid, "1")).status_code == 404
    # nothing changed by the failed attempts
    assert stock(client, tenant_a, location, beef) == Decimal("9.2")


def test_cannot_refund_a_cancelled_sale(client, tenant_a):
    location, integration, beef, potato = setup(client, tenant_a)
    sale = make_sale(client, tenant_a, integration)
    client.post(f"/api/sales/{sale['id']}/status", headers=tenant_a["headers"], json={"status": "cancelled"})
    assert refund(client, tenant_a, sale, (sale["lines"][0]["id"], "1")).status_code == 409


def test_margin_report_uses_net_of_refunds(client, tenant_a):
    from tests.test_costing import set_cost

    location, integration, beef, potato = setup(client, tenant_a)
    set_cost(client, tenant_a, beef, "50")
    sale = make_sale(client, tenant_a, integration)
    burger_line = next(l for l in sale["lines"] if l["product_name"] == "Burger")
    refund(client, tenant_a, sale, (burger_line["id"], "1"))
    rows = client.get("/api/reports/margins", headers=tenant_a["headers"]).json()
    burger = next(r for r in rows if r["product_name"] == "Burger")
    assert Decimal(burger["quantity_sold"]) == 3
    assert Decimal(burger["revenue"]) == Decimal("30.00")
    assert Decimal(burger["cost"]) == Decimal("30")  # 3 * 0.2kg * 50


def test_legacy_sale_without_line_links_requires_full_cancel(client, tenant_a):
    from app.core.database import SessionLocal
    from app.models.inventory import StockMovement

    location, integration, beef, potato = setup(client, tenant_a)
    sale = make_sale(client, tenant_a, integration)
    with SessionLocal() as db:
        for movement in db.query(StockMovement).filter(StockMovement.movement_type == "recipe_consumption"):
            movement.sale_line_id = None  # as if imported before line-level tracking
        db.commit()
    response = refund(client, tenant_a, sale, (sale["lines"][0]["id"], "1"))
    assert response.status_code == 400 and "whole sale" in response.json()["detail"]
    assert client.post(f"/api/sales/{sale['id']}/status", headers=tenant_a["headers"], json={"status": "refunded"}).status_code == 200
    assert stock(client, tenant_a, location, beef) == Decimal("10")
