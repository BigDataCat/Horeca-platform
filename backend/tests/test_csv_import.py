from decimal import Decimal

from tests.conftest import (
    add_stock,
    create_integration,
    create_location,
    create_product,
    create_recipe,
    get_stock,
)

HEADER = "sale_id,occurred_at,external_product_id,product_name,quantity,uom,unit_price,tax_value\n"


def setup(client, tenant, provider="csv"):
    location = create_location(client, tenant)
    return location, create_integration(client, tenant, location, provider=provider)


def upload(client, tenant, integration, body, **kwargs):
    return client.post(
        f"/api/sales/import-csv?integration_id={integration['id']}",
        headers={**tenant["headers"], "Content-Type": "text/csv"},
        content=body.encode() if isinstance(body, str) else body,
        **kwargs,
    )


def test_csv_import_groups_lines_into_sales(client, tenant_a):
    _, integration = setup(client, tenant_a)
    body = HEADER + (
        "T1,2026-10-01T10:00:00Z,B1,Burger,2,EA,10.00,3.80\n"
        "T1,2026-10-01T10:00:00Z,F1,Fries,1,EA,5.00,0.95\n"
        "T2,2026-10-01T11:00:00Z,B1,Burger,1,EA,10.00,1.90\n"
    )
    response = upload(client, tenant_a, integration, body)
    assert response.status_code == 200, response.text
    assert response.json() == {"imported": 2, "skipped_duplicates": 0}

    sales = {s["external_id"]: s for s in client.get("/api/sales", headers=tenant_a["headers"]).json()}
    t1 = sales["T1"]
    assert len(t1["lines"]) == 2
    assert Decimal(t1["net_value"]) == Decimal("25.00")
    assert Decimal(t1["tax_value"]) == Decimal("4.75")
    assert Decimal(t1["gross_value"]) == Decimal("29.75")
    assert t1["currency"] == "RON"


def test_csv_reupload_is_idempotent(client, tenant_a):
    _, integration = setup(client, tenant_a)
    body = HEADER + "T1,2026-10-01T10:00:00Z,B1,Burger,1,EA,10,0\n"
    assert upload(client, tenant_a, integration, body).json()["imported"] == 1
    again = upload(client, tenant_a, integration, body)
    assert again.json() == {"imported": 0, "skipped_duplicates": 1}


def test_semicolon_delimiter_with_decimal_comma_and_bom(client, tenant_a):
    _, integration = setup(client, tenant_a)
    body = "﻿sale_id;occurred_at;product_name;quantity;unit_price;tax_value\nT1;2026-10-01 10:00:00;Burger;1,5;10,50;2,99\n"
    response = upload(client, tenant_a, integration, body)
    assert response.status_code == 200, response.text
    sale = client.get("/api/sales", headers=tenant_a["headers"]).json()[0]
    assert Decimal(sale["lines"][0]["quantity"]) == Decimal("1.5")
    assert Decimal(sale["lines"][0]["unit_price"]) == Decimal("10.50")
    assert Decimal(sale["net_value"]) == Decimal("15.75")


def test_csv_drives_mapping_and_recipe_consumption(client, tenant_a):
    location, integration = setup(client, tenant_a)
    burger = create_product(client, tenant_a, "Burger", sku="B1")
    beef = create_product(client, tenant_a, "Beef", base_uom="KG")
    add_stock(client, tenant_a, location, beef, "10", "KG")
    create_recipe(client, tenant_a, burger, [{"ingredient_product_id": beef["id"], "quantity": "0.2", "uom": "KG"}])
    upload(client, tenant_a, integration, HEADER + "T1,2026-10-01T10:00:00Z,B1,Burger,3,EA,10,0\n")
    assert Decimal(get_stock(client, tenant_a, location, beef)["quantity"]) == Decimal("9.4")


def test_invalid_rows_reject_whole_file_with_row_numbers(client, tenant_a):
    _, integration = setup(client, tenant_a)
    body = HEADER + (
        "T1,2026-10-01T10:00:00Z,B1,Burger,1,EA,10,0\n"
        "T2,not-a-date,B1,Burger,1,EA,10,0\n"
        "T3,2026-10-01T10:00:00Z,B1,Burger,abc,EA,10,0\n"
        "T4,2026-10-01T10:00:00Z,B1,Burger,0,EA,10,0\n"
    )
    response = upload(client, tenant_a, integration, body)
    assert response.status_code == 422
    errors = response.json()["detail"]
    assert any(e.startswith("Row 3") for e in errors)
    assert any(e.startswith("Row 4") for e in errors)
    assert any(e.startswith("Row 5") for e in errors)
    assert client.get("/api/sales", headers=tenant_a["headers"]).json() == []


def test_missing_columns_and_empty_file(client, tenant_a):
    _, integration = setup(client, tenant_a)
    missing = upload(client, tenant_a, integration, "sale_id,product_name\nT1,Burger\n")
    assert missing.status_code == 422
    assert "occurred_at" in missing.json()["detail"][0]
    assert upload(client, tenant_a, integration, "").status_code == 422
    assert upload(client, tenant_a, integration, HEADER).status_code == 422


def test_conflicting_sale_header_values_rejected(client, tenant_a):
    _, integration = setup(client, tenant_a)
    body = HEADER + (
        "T1,2026-10-01T10:00:00Z,B1,Burger,1,EA,10,0\n"
        "T1,2026-10-02T10:00:00Z,F1,Fries,1,EA,5,0\n"
    )
    assert upload(client, tenant_a, integration, body).status_code == 422


def test_non_utf8_and_oversize_rejected(client, tenant_a):
    _, integration = setup(client, tenant_a)
    assert upload(client, tenant_a, integration, b"\xff\xfe\x00bad").status_code == 400
    assert upload(client, tenant_a, integration, b"x" * (5 * 1024 * 1024 + 1)).status_code == 413


def test_csv_import_rules(client, tenant_a, tenant_b, employee_a):
    _, integration = setup(client, tenant_a)
    body = HEADER + "T1,2026-10-01T10:00:00Z,B1,Burger,1,EA,10,0\n"
    assert upload(client, employee_a, integration, body).status_code == 403
    assert upload(client, tenant_b, integration, body).status_code == 404
    client.delete(f"/api/integrations/pos/{integration['id']}", headers=tenant_a["headers"])
    assert upload(client, tenant_a, integration, body).status_code == 400


def test_csv_provider_listed(client):
    providers = {p["provider"]: p for p in client.get("/api/integrations/pos/providers").json()}
    assert providers["csv"]["supported_connection_types"] == ["file"]
