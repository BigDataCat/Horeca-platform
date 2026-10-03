import pytest

from app.services import pos_connectors
from tests.conftest import create_integration, create_location, create_product


@pytest.fixture()
def integration(client, tenant_a):
    location = create_location(client, tenant_a)
    return create_integration(client, tenant_a, location, provider="demo")


def sync(client, tenant, integration):
    return client.post(f"/api/integrations/pos/{integration['id']}/sync", headers=tenant["headers"])


def get_integration(client, tenant, integration):
    rows = client.get("/api/integrations/pos", headers=tenant["headers"]).json()
    return next(r for r in rows if r["id"] == integration["id"])


def test_provider_catalog(client):
    response = client.get("/api/integrations/pos/providers")
    assert response.status_code == 200
    assert {p["provider"] for p in response.json()} >= {"demo", "mock"}


def test_test_connection(client, tenant_a, integration):
    response = client.post(f"/api/integrations/pos/{integration['id']}/test", headers=tenant_a["headers"])
    assert response.status_code == 200
    assert response.json()["success"] is True
    assert get_integration(client, tenant_a, integration)["status"] == "connected"


def test_first_sync_imports_and_sets_cursor(client, tenant_a, integration):
    response = sync(client, tenant_a, integration)
    assert response.status_code == 200
    assert response.json()["fetched"] == 2
    assert response.json()["imported"] == 2
    current = get_integration(client, tenant_a, integration)
    assert current["last_sync_cursor"] == "2026-10-01T19:15:00Z"
    assert current["last_synced_at"] is not None
    assert current["status"] == "connected"


def test_second_sync_uses_cursor_and_fetches_nothing(client, tenant_a, integration):
    sync(client, tenant_a, integration)
    again = sync(client, tenant_a, integration)
    assert again.json() == {
        "integration_id": integration["id"],
        "provider": "demo",
        "fetched": 0,
        "imported": 0,
        "skipped_duplicates": 0,
    }
    assert len(client.get("/api/sales", headers=tenant_a["headers"]).json()) == 2


def test_cursor_reset_reimports_nothing_thanks_to_idempotency(client, tenant_a, integration):
    sync(client, tenant_a, integration)
    # force a re-pull from scratch by clearing the cursor directly
    from app.core.database import SessionLocal
    from app.models.pos_integration import POSIntegration

    with SessionLocal() as db:
        db.get(POSIntegration, integration["id"]).last_sync_cursor = None
        db.commit()
    result = sync(client, tenant_a, integration).json()
    assert result["fetched"] == 2
    assert result["imported"] == 0
    assert result["skipped_duplicates"] == 2


def test_sync_history_is_recorded(client, tenant_a, integration):
    sync(client, tenant_a, integration)
    sync(client, tenant_a, integration)
    runs = client.get(f"/api/integrations/pos/{integration['id']}/sync-runs", headers=tenant_a["headers"]).json()
    assert len(runs) == 2
    assert {r["status"] for r in runs} == {"success"}
    assert sorted(r["imported"] for r in runs) == [0, 2]


def test_inactive_integration_cannot_sync(client, tenant_a, integration):
    client.delete(f"/api/integrations/pos/{integration['id']}", headers=tenant_a["headers"])
    assert sync(client, tenant_a, integration).status_code == 400


class ExplodingConnector:
    def __init__(self, exc):
        self.exc = exc

    def test_connection(self, integration):
        raise self.exc

    def pull_sales(self, integration, cursor=None):
        raise self.exc


@pytest.fixture()
def restore_connectors():
    saved = dict(pos_connectors.CONNECTORS)
    yield
    pos_connectors.CONNECTORS.clear()
    pos_connectors.CONNECTORS.update(saved)


@pytest.mark.parametrize("exc,status", [(RuntimeError("boom"), 502), (ValueError("bad config"), 400)])
def test_failed_sync_is_audited_and_marks_integration_error(client, tenant_a, restore_connectors, exc, status):
    location = create_location(client, tenant_a)
    integration = create_integration(client, tenant_a, location, provider="flaky")
    pos_connectors.register_connector("flaky", ExplodingConnector(exc))

    response = sync(client, tenant_a, integration)
    assert response.status_code == status
    runs = client.get(f"/api/integrations/pos/{integration['id']}/sync-runs", headers=tenant_a["headers"]).json()
    assert len(runs) == 1
    assert runs[0]["status"] == "error"
    assert str(exc) in runs[0]["error_message"]
    assert get_integration(client, tenant_a, integration)["status"] == "error"


def test_unknown_provider_sync_fails_cleanly(client, tenant_a):
    location = create_location(client, tenant_a)
    integration = create_integration(client, tenant_a, location, provider="nonexistent")
    response = sync(client, tenant_a, integration)
    assert response.status_code == 400


def test_failed_sync_keeps_cursor_and_imports_nothing(client, tenant_a, restore_connectors):
    from datetime import datetime, timezone
    from decimal import Decimal

    from app.schemas.sales import CanonicalSale, CanonicalSaleLine

    class HalfBadConnector:
        def test_connection(self, integration):
            ...

        def pull_sales(self, integration, cursor=None):
            def sale(external_id, uom):
                return CanonicalSale(
                    external_id=external_id,
                    occurred_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                    currency="RON",
                    net_value=Decimal("1"),
                    gross_value=Decimal("1"),
                    lines=[CanonicalSaleLine(
                        external_product_id="BURGER", product_name="Burger", quantity=Decimal("1"),
                        uom=uom, unit_price=Decimal("1"), net_value=Decimal("1"),
                    )],
                )
            return pos_connectors.SalesPullResult(sales=[sale("OK-1", "EA"), sale("BAD", "EA")], next_cursor="next")

    from tests.conftest import add_stock, create_recipe
    location = create_location(client, tenant_a)
    burger = create_product(client, tenant_a, "Burger", sku="BURGER")
    beef = create_product(client, tenant_a, "Beef", base_uom="KG")
    add_stock(client, tenant_a, location, beef, "10", "KG")
    # grams with no conversion: consumption raises on the first sale, failing the whole batch
    create_recipe(client, tenant_a, burger, [{"ingredient_product_id": beef["id"], "quantity": "200", "uom": "G"}])
    integration = create_integration(client, tenant_a, location, provider="halfbad")
    pos_connectors.register_connector("halfbad", HalfBadConnector())

    assert sync(client, tenant_a, integration).status_code == 400
    assert client.get("/api/sales", headers=tenant_a["headers"]).json() == []
    assert get_integration(client, tenant_a, integration)["last_sync_cursor"] is None
