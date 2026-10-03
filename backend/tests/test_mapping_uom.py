from decimal import Decimal

from tests.conftest import (
    create_integration,
    create_location,
    create_product,
    import_sales,
    line,
    sale_payload,
)


def test_mapping_unique_per_integration_and_external_product(client, tenant_a):
    location = create_location(client, tenant_a)
    integration = create_integration(client, tenant_a, location)
    product = create_product(client, tenant_a)
    body = {"integration_id": integration["id"], "external_product_id": "E1", "product_id": product["id"]}
    first = client.post("/api/product-mappings", headers=tenant_a["headers"], json=body)
    assert first.status_code == 201
    assert Decimal(first.json()["confidence"]) == 1
    assert client.post("/api/product-mappings", headers=tenant_a["headers"], json=body).status_code == 409


def test_mapping_delete(client, tenant_a):
    location = create_location(client, tenant_a)
    integration = create_integration(client, tenant_a, location)
    product = create_product(client, tenant_a)
    mapping = client.post(
        "/api/product-mappings",
        headers=tenant_a["headers"],
        json={"integration_id": integration["id"], "external_product_id": "E1", "product_id": product["id"]},
    ).json()
    assert client.delete(f"/api/product-mappings/{mapping['id']}", headers=tenant_a["headers"]).status_code == 204
    assert client.get("/api/product-mappings", headers=tenant_a["headers"]).json() == []


def make_conversion(client, tenant, product, from_uom, to_uom, factor):
    return client.post(
        "/api/product-mappings/uom-conversions",
        headers=tenant["headers"],
        json={"product_id": product["id"], "from_uom": from_uom, "to_uom": to_uom, "factor": factor},
    )


def test_uom_conversion_validation(client, tenant_a):
    product = create_product(client, tenant_a, "Beer", base_uom="EA")
    assert make_conversion(client, tenant_a, product, "case", "ea", "24").status_code == 201
    assert make_conversion(client, tenant_a, product, "CASE", "EA", "24").status_code == 409
    assert make_conversion(client, tenant_a, product, "EA", "ea", "1").status_code == 400
    assert make_conversion(client, tenant_a, product, "PACK", "EA", "0").status_code == 422
    assert make_conversion(client, tenant_a, product, "PACK", "EA", "-1").status_code == 422


def test_sale_quantity_normalized_with_conversion(client, tenant_a):
    location = create_location(client, tenant_a)
    integration = create_integration(client, tenant_a, location)
    product = create_product(client, tenant_a, "Heineken 330ml", sku="HEI-330", base_uom="EA")
    make_conversion(client, tenant_a, product, "CASE", "EA", "24")

    import_sales(
        client, tenant_a, integration,
        sale_payload("S1", lines=[line("Heineken 330ml", "HEI-330", quantity="2", uom="case")]),
    )
    sale_line = client.get("/api/sales", headers=tenant_a["headers"]).json()[0]["lines"][0]
    assert Decimal(sale_line["quantity"]) == Decimal("48")
    assert sale_line["uom"] == "EA"


def test_sale_without_conversion_keeps_original_uom_and_quantity(client, tenant_a):
    """No conversion is invented: quantity and UOM stay exactly as the POS sent them."""
    location = create_location(client, tenant_a)
    integration = create_integration(client, tenant_a, location)
    create_product(client, tenant_a, "Heineken 330ml", sku="HEI-330", base_uom="EA")

    import_sales(
        client, tenant_a, integration,
        sale_payload("S1", lines=[line("Heineken 330ml", "HEI-330", quantity="2", uom="CASE")]),
    )
    sale_line = client.get("/api/sales", headers=tenant_a["headers"]).json()[0]["lines"][0]
    assert Decimal(sale_line["quantity"]) == Decimal("2")
    assert sale_line["uom"] == "CASE"


def test_conversion_is_per_product(client, tenant_a):
    location = create_location(client, tenant_a)
    integration = create_integration(client, tenant_a, location)
    beer = create_product(client, tenant_a, "Beer", sku="B", base_uom="EA")
    water = create_product(client, tenant_a, "Water", sku="W", base_uom="EA")
    make_conversion(client, tenant_a, beer, "PACK", "EA", "6")
    make_conversion(client, tenant_a, water, "PACK", "EA", "12")
    import_sales(
        client, tenant_a, integration,
        sale_payload("S1", lines=[line("Beer", "B", uom="PACK"), line("Water", "W", uom="PACK")]),
    )
    lines = {l["product_name"]: Decimal(l["quantity"]) for l in client.get("/api/sales", headers=tenant_a["headers"]).json()[0]["lines"]}
    assert lines == {"Beer": Decimal("6"), "Water": Decimal("12")}


def test_deleted_conversion_no_longer_applies(client, tenant_a):
    location = create_location(client, tenant_a)
    integration = create_integration(client, tenant_a, location)
    beer = create_product(client, tenant_a, "Beer", sku="B", base_uom="EA")
    conversion = make_conversion(client, tenant_a, beer, "PACK", "EA", "6").json()
    assert client.delete(
        f"/api/product-mappings/uom-conversions/{conversion['id']}", headers=tenant_a["headers"]
    ).status_code == 204
    import_sales(client, tenant_a, integration, sale_payload("S1", lines=[line("Beer", "B", uom="PACK")]))
    sale_line = client.get("/api/sales", headers=tenant_a["headers"]).json()[0]["lines"][0]
    assert sale_line["uom"] == "PACK"
