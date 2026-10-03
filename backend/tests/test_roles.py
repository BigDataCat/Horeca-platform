from tests.conftest import create_location, create_product


def test_employee_can_read_but_not_write(client, tenant_a, employee_a):
    create_product(client, tenant_a)
    location = create_location(client, tenant_a)

    assert client.get("/api/products", headers=employee_a["headers"]).status_code == 200
    assert client.get("/api/locations", headers=employee_a["headers"]).status_code == 200
    assert client.get("/api/users", headers=employee_a["headers"]).status_code == 200

    forbidden = [
        client.post("/api/products", headers=employee_a["headers"], json={"name": "X"}),
        client.post(
            "/api/users",
            headers=employee_a["headers"],
            json={
                "company_id": tenant_a["company_id"],
                "email": "new@test.dev",
                "first_name": "N",
                "last_name": "U",
                "password": "password123",
            },
        ),
        client.post(
            "/api/integrations/pos",
            headers=employee_a["headers"],
            json={"location_id": location["id"], "provider": "demo", "name": "POS"},
        ),
        client.post(
            "/api/inventory/adjustments",
            headers=employee_a["headers"],
            json={"location_id": location["id"], "product_id": 1, "quantity": "1", "uom": "EA"},
        ),
        client.post(
            "/api/recipes",
            headers=employee_a["headers"],
            json={"product_id": 1, "name": "R", "lines": [{"ingredient_product_id": 1, "quantity": "1", "uom": "EA"}]},
        ),
        client.post(
            "/api/costs/products",
            headers=employee_a["headers"],
            json={"product_id": 1, "unit_cost": "1", "effective_from": "2026-01-01T00:00:00Z"},
        ),
        client.post(
            "/api/sales/import",
            headers=employee_a["headers"],
            json={
                "integration_id": 1,
                "sales": [
                    {
                        "external_id": "S1",
                        "occurred_at": "2026-01-01T10:00:00Z",
                        "currency": "RON",
                        "net_value": "10",
                        "gross_value": "11",
                        "lines": [
                            {
                                "product_name": "X",
                                "quantity": "1",
                                "uom": "EA",
                                "unit_price": "10",
                                "net_value": "10",
                            }
                        ],
                    }
                ],
            },
        ),
    ]
    assert [r.status_code for r in forbidden] == [403] * len(forbidden)


def test_manager_can_write_products(client, manager_a):
    response = client.post("/api/products", headers=manager_a["headers"], json={"name": "Fries"})
    assert response.status_code == 201


def test_manager_cannot_create_owner(client, tenant_a, manager_a):
    response = client.post(
        "/api/users",
        headers=manager_a["headers"],
        json={
            "company_id": tenant_a["company_id"],
            "email": "owner2@test.dev",
            "first_name": "O",
            "last_name": "2",
            "password": "password123",
            "role": "owner",
        },
    )
    assert response.status_code == 403


def test_manager_cannot_promote_to_owner_or_deactivate_owner(client, tenant_a, manager_a, employee_a):
    promote = client.patch(
        f"/api/users/{employee_a['user']['id']}",
        headers=manager_a["headers"],
        json={"role": "owner"},
    )
    assert promote.status_code == 403

    deactivate = client.delete(
        f"/api/users/{tenant_a['user']['id']}", headers=manager_a["headers"]
    )
    assert deactivate.status_code == 403


def test_owner_cannot_deactivate_self(client, tenant_a):
    response = client.delete(f"/api/users/{tenant_a['user']['id']}", headers=tenant_a["headers"])
    assert response.status_code == 400
    response = client.patch(
        f"/api/users/{tenant_a['user']['id']}", headers=tenant_a["headers"], json={"active": False}
    )
    assert response.status_code == 400
