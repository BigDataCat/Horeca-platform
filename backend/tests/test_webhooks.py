from tests.conftest import create_integration, create_location, sale_payload, with_webhook_token

_DEFAULT = object()


def setup(client, tenant):
    location = create_location(client, tenant)
    return with_webhook_token(
        client, tenant, create_integration(client, tenant, location, provider="mock")
    )


def post(client, integration, event_id="E1", sale=None, token=_DEFAULT):
    if token is _DEFAULT:
        token = integration["token"]
    headers = {"X-Webhook-Token": token} if token is not None else {}
    return client.post(
        f"/api/integrations/pos/{integration['id']}/webhook",
        headers=headers,
        json={"event_id": event_id, "event_type": "sale.created", "sale": sale or sale_payload("W1")},
    )


def test_valid_webhook_imports_sale(client, tenant_a):
    integration = setup(client, tenant_a)
    response = post(client, integration)
    assert response.status_code == 200
    assert response.json()["duplicate"] is False
    sales = client.get("/api/sales", headers=tenant_a["headers"]).json()
    assert [s["external_id"] for s in sales] == ["W1"]


def test_missing_or_wrong_token_rejected(client, tenant_a):
    integration = setup(client, tenant_a)
    assert post(client, integration, token=None).status_code == 401
    assert post(client, integration, token="wrong").status_code == 401
    assert client.get("/api/sales", headers=tenant_a["headers"]).json() == []


def test_integration_without_configured_token_rejects_everything(client, tenant_a):
    location = create_location(client, tenant_a)
    integration = create_integration(client, tenant_a, location, provider="mock")
    assert post(client, integration, token="").status_code == 401
    assert post(client, integration, token="anything").status_code == 401


def test_duplicate_event_is_idempotent(client, tenant_a):
    integration = setup(client, tenant_a)
    assert post(client, integration).json()["duplicate"] is False
    again = post(client, integration)
    assert again.status_code == 200
    assert again.json()["duplicate"] is True
    assert len(client.get("/api/sales", headers=tenant_a["headers"]).json()) == 1


def test_new_event_with_already_imported_sale_is_flagged_duplicate(client, tenant_a):
    integration = setup(client, tenant_a)
    post(client, integration, event_id="E1")
    second = post(client, integration, event_id="E2")
    assert second.status_code == 200
    assert second.json()["duplicate"] is True
    assert len(client.get("/api/sales", headers=tenant_a["headers"]).json()) == 1


def test_inactive_integration_not_found(client, tenant_a):
    integration = setup(client, tenant_a)
    client.delete(f"/api/integrations/pos/{integration['id']}", headers=tenant_a["headers"])
    assert post(client, integration).status_code == 404


def test_token_of_one_integration_does_not_work_on_another(client, tenant_a, tenant_b):
    mine = setup(client, tenant_a)
    location = create_location(client, tenant_b)
    other = with_webhook_token(client, tenant_b, create_integration(client, tenant_b, location, provider="mock"))
    assert post(client, other, token=mine["token"]).status_code == 401
    assert post(client, mine, token=other["token"]).status_code == 401


def test_webhook_sale_applies_to_integrations_company_only(client, tenant_a, tenant_b):
    integration = setup(client, tenant_a)
    post(client, integration)
    assert client.get("/api/sales", headers=tenant_b["headers"]).json() == []


def _failing_setup(client, tenant):
    """Burger consumes grams of beef without a conversion, so the import fails."""
    from tests.conftest import add_stock, create_product, create_recipe, line

    location = create_location(client, tenant)
    integration = with_webhook_token(
        client, tenant, create_integration(client, tenant, location, provider="mock")
    )
    burger = create_product(client, tenant, "Burger", sku="BURGER")
    beef = create_product(client, tenant, "Beef", base_uom="KG")
    add_stock(client, tenant, location, beef, "10", "KG")
    create_recipe(client, tenant, burger, [{"ingredient_product_id": beef["id"], "quantity": "200", "uom": "G"}])
    sale = sale_payload("W-FAIL", lines=[line("Burger", "BURGER")])
    return integration, sale, beef


def test_failed_event_is_persisted_and_can_be_replayed(client, tenant_a):
    integration, sale, beef = _failing_setup(client, tenant_a)
    failed = post(client, integration, event_id="E-FAIL", sale=sale)
    assert failed.status_code == 502
    assert client.get("/api/sales", headers=tenant_a["headers"]).json() == []

    events = client.get(
        f"/api/integrations/pos/{integration['id']}/webhook-events", headers=tenant_a["headers"]
    ).json()
    assert [(e["external_event_id"], e["status"], e["attempts"]) for e in events] == [("E-FAIL", "failed", 1)]
    assert "No UOM conversion" in events[0]["error_message"]

    # Operator fixes the data (adds the missing conversion) and replays the event.
    client.post(
        "/api/product-mappings/uom-conversions",
        headers=tenant_a["headers"],
        json={"product_id": beef["id"], "from_uom": "G", "to_uom": "KG", "factor": "0.001"},
    )
    replay = client.post(
        f"/api/integrations/pos/{integration['id']}/webhook-events/{events[0]['id']}/replay",
        headers=tenant_a["headers"],
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["status"] == "processed"
    assert replay.json()["attempts"] == 2
    assert len(client.get("/api/sales", headers=tenant_a["headers"]).json()) == 1


def test_redelivery_of_failed_event_is_retried(client, tenant_a):
    integration, sale, beef = _failing_setup(client, tenant_a)
    assert post(client, integration, event_id="E-FAIL", sale=sale).status_code == 502
    client.post(
        "/api/product-mappings/uom-conversions",
        headers=tenant_a["headers"],
        json={"product_id": beef["id"], "from_uom": "G", "to_uom": "KG", "factor": "0.001"},
    )
    again = post(client, integration, event_id="E-FAIL", sale=sale)
    assert again.status_code == 200
    assert again.json()["duplicate"] is False


def test_only_failed_events_can_be_replayed(client, tenant_a):
    integration = setup(client, tenant_a)
    post(client, integration)
    event = client.get(
        f"/api/integrations/pos/{integration['id']}/webhook-events", headers=tenant_a["headers"]
    ).json()[0]
    response = client.post(
        f"/api/integrations/pos/{integration['id']}/webhook-events/{event['id']}/replay",
        headers=tenant_a["headers"],
    )
    assert response.status_code == 400


def test_webhook_events_are_tenant_scoped_and_manager_only(client, tenant_a, tenant_b, employee_a):
    integration, sale, _ = _failing_setup(client, tenant_a)
    post(client, integration, event_id="E-FAIL", sale=sale)
    url = f"/api/integrations/pos/{integration['id']}/webhook-events"
    assert client.get(url, headers=tenant_b["headers"]).status_code == 404
    event = client.get(url, headers=tenant_a["headers"]).json()[0]
    assert client.post(f"{url}/{event['id']}/replay", headers=tenant_b["headers"]).status_code == 404
    assert client.post(f"{url}/{event['id']}/replay", headers=employee_a["headers"]).status_code == 403


def test_token_is_never_exposed_and_rotation_invalidates_old_token(client, tenant_a):
    integration = setup(client, tenant_a)
    listed = client.get("/api/integrations/pos", headers=tenant_a["headers"]).json()[0]
    assert listed["webhook_configured"] is True
    assert integration["token"] not in str(listed)

    old = integration["token"]
    rotated = with_webhook_token(client, tenant_a, integration)
    assert rotated["token"] != old
    assert post(client, integration, token=old).status_code == 401
    assert post(client, rotated).status_code == 200


def test_webhook_token_in_config_is_rejected(client, tenant_a):
    location = create_location(client, tenant_a)
    response = client.post(
        "/api/integrations/pos",
        headers=tenant_a["headers"],
        json={"location_id": location["id"], "provider": "mock", "name": "x", "config": {"webhook_token": "abc"}},
    )
    assert response.status_code == 400


def test_webhook_token_management_requires_manager_and_tenant(client, tenant_a, tenant_b, employee_a):
    integration = setup(client, tenant_a)
    url = f"/api/integrations/pos/{integration['id']}/webhook-token"
    assert client.post(url, headers=employee_a["headers"]).status_code == 403
    assert client.post(url, headers=tenant_b["headers"]).status_code == 404
