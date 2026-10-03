from decimal import Decimal

from tests.conftest import (
    create_integration,
    create_location,
    create_product,
    import_sales,
    line,
    sale_payload,
)


def setup(client, tenant):
    location = create_location(client, tenant)
    integration = create_integration(client, tenant, location)
    return location, integration


def test_import_and_duplicate_detection(client, tenant_a):
    _, integration = setup(client, tenant_a)
    first = import_sales(client, tenant_a, integration, sale_payload("S1"))
    assert first.json() == {"imported": 1, "skipped_duplicates": 0}

    again = import_sales(client, tenant_a, integration, sale_payload("S1"))
    assert again.json() == {"imported": 0, "skipped_duplicates": 1}

    sales = client.get("/api/sales", headers=tenant_a["headers"]).json()
    assert len(sales) == 1


def test_same_external_id_allowed_on_different_integrations(client, tenant_a):
    location = create_location(client, tenant_a)
    one = create_integration(client, tenant_a, location)
    two = create_integration(client, tenant_a, location)
    assert import_sales(client, tenant_a, one, sale_payload("S1")).json()["imported"] == 1
    assert import_sales(client, tenant_a, two, sale_payload("S1")).json()["imported"] == 1


def test_duplicate_inside_single_batch_does_not_crash(client, tenant_a):
    _, integration = setup(client, tenant_a)
    response = import_sales(client, tenant_a, integration, sale_payload("S1"), sale_payload("S1"))
    assert response.status_code == 200, response.text
    assert response.json() == {"imported": 1, "skipped_duplicates": 1}


def test_inactive_integration_rejected(client, tenant_a):
    _, integration = setup(client, tenant_a)
    client.delete(f"/api/integrations/pos/{integration['id']}", headers=tenant_a["headers"])
    response = import_sales(client, tenant_a, integration, sale_payload("S1"))
    assert response.status_code == 400


def test_matching_by_mapping_sku_and_name(client, tenant_a):
    _, integration = setup(client, tenant_a)
    mapped = create_product(client, tenant_a, "Mapped Product")
    by_sku = create_product(client, tenant_a, "Sku Product", sku="SKU-1")
    by_name = create_product(client, tenant_a, "Pizza Margherita")

    client.post(
        "/api/product-mappings",
        headers=tenant_a["headers"],
        json={"integration_id": integration["id"], "external_product_id": "EXT-M", "product_id": mapped["id"]},
    )
    import_sales(
        client,
        tenant_a,
        integration,
        sale_payload(
            "S1",
            lines=[
                line("Whatever", "EXT-M"),
                line("Other", "SKU-1"),
                line("pizza margherita", "NOPE"),
                line("Unknown thing", "EXT-U"),
            ],
        ),
    )
    sale = client.get("/api/sales", headers=tenant_a["headers"]).json()[0]
    resolved = {l["product_name"]: l["product_id"] for l in sale["lines"]}
    assert resolved["Whatever"] == mapped["id"]
    assert resolved["Other"] == by_sku["id"]
    assert resolved["pizza margherita"] == by_name["id"]
    assert resolved["Unknown thing"] is None


def test_unmatched_products_report(client, tenant_a):
    _, integration = setup(client, tenant_a)
    import_sales(
        client,
        tenant_a,
        integration,
        sale_payload("S1", lines=[line("Mystery", "EXT-X", quantity="2")]),
        sale_payload("S2", lines=[line("Mystery", "EXT-X", quantity="3")]),
    )
    rows = client.get("/api/sales/unmatched-products", headers=tenant_a["headers"]).json()
    assert len(rows) == 1
    assert rows[0]["external_product_id"] == "EXT-X"
    assert rows[0]["occurrences"] == 2
    assert Decimal(rows[0]["total_quantity"]) == Decimal("5")


def test_mapping_resolves_previously_unmatched_after_creation(client, tenant_a):
    _, integration = setup(client, tenant_a)
    product = create_product(client, tenant_a, "Real")
    import_sales(client, tenant_a, integration, sale_payload("S1", lines=[line("Mystery", "EXT-X")]))
    client.post(
        "/api/product-mappings",
        headers=tenant_a["headers"],
        json={"integration_id": integration["id"], "external_product_id": "EXT-X", "product_id": product["id"]},
    )
    import_sales(client, tenant_a, integration, sale_payload("S2", lines=[line("Mystery", "EXT-X")]))
    sales = {s["external_id"]: s for s in client.get("/api/sales", headers=tenant_a["headers"]).json()}
    assert sales["S1"]["lines"][0]["product_id"] is None
    assert sales["S2"]["lines"][0]["product_id"] == product["id"]


def test_name_match_does_not_treat_sql_wildcards_as_patterns(client, tenant_a):
    _, integration = setup(client, tenant_a)
    create_product(client, tenant_a, "Cola")
    import_sales(client, tenant_a, integration, sale_payload("S1", lines=[line("%", "EXT-W")]))
    sale = client.get("/api/sales", headers=tenant_a["headers"]).json()[0]
    assert sale["lines"][0]["product_id"] is None
