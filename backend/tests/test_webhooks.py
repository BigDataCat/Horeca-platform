from tests.conftest import create_integration, create_location, sale_payload

TOKEN = "s3cret-token"


def setup(client, tenant):
    location = create_location(client, tenant)
    return create_integration(client, tenant, location, provider="mock", config={"webhook_token": TOKEN})


def post(client, integration, event_id="E1", sale=None, token=TOKEN):
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
    integration = create_integration(client, tenant_a, location, provider="mock", config=None)
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
    other = create_integration(client, tenant_b, location, provider="mock", config={"webhook_token": "other-token"})
    assert post(client, other, token=TOKEN).status_code == 401
    assert post(client, mine, token="other-token").status_code == 401


def test_webhook_sale_applies_to_integrations_company_only(client, tenant_a, tenant_b):
    integration = setup(client, tenant_a)
    post(client, integration)
    assert client.get("/api/sales", headers=tenant_b["headers"]).json() == []
