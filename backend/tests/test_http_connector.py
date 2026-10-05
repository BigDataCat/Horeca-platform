import json
from decimal import Decimal

import httpx
import pytest

from app.core.config import settings
from app.services import http_connector
from tests.conftest import add_stock, create_location, create_product, create_recipe, get_stock

CONFIG = {
    "sales_path": "/v1/transactions",
    "cursor_param": "updated_after",
    "page_size_param": "limit",
    "page_size": 2,
    "page_param": "page",
    "items_path": "data.items",
    "auth": {"type": "bearer"},
    "amount_divisor": 100,
    "default_currency": "RON",
    "mapping": {
        "external_id": "id",
        "occurred_at": "created_at",
        "currency": "currency",
        "lines_path": "lines",
        "line": {
            "external_product_id": "sku", "product_name": "name", "quantity": "qty",
            "uom": "unit", "unit_price": "price", "net_value": "net", "tax_value": "tax",
        },
    },
}


def record(index, created="2026-10-01T10:00:00Z", sku="BURGER", qty=1):
    return {
        "id": f"T{index}", "created_at": created, "currency": "RON",
        "lines": [{"sku": sku, "name": "Burger", "qty": qty, "unit": "EA", "price": 1000, "net": 1000 * qty, "tax": 190 * qty}],
    }


@pytest.fixture(autouse=True)
def http_env(monkeypatch):
    monkeypatch.setenv("POS_TEST_TOKEN", "secret-token")
    monkeypatch.setattr(settings, "http_connector_allow_private", False)
    monkeypatch.setattr(http_connector, "resolve_host", lambda host: ["93.184.216.34"])
    monkeypatch.setattr(http_connector, "sleep", lambda seconds: None)
    yield
    http_connector.transport = None


def serve(monkeypatch, handler):
    monkeypatch.setattr(http_connector, "transport", httpx.MockTransport(handler))


def make_integration(client, tenant, config=None, base_url="https://pos.example.com", credentials_ref="env:POS_TEST_TOKEN"):
    location = create_location(client, tenant)
    response = client.post(
        "/api/integrations/pos", headers=tenant["headers"],
        json={"location_id": location["id"], "provider": "http", "name": "REST POS", "base_url": base_url,
              "credentials_ref": credentials_ref, "config": CONFIG if config is None else config},
    )
    assert response.status_code == 201, response.text
    return location, response.json()


def sync(client, tenant, integration):
    return client.post(f"/api/integrations/pos/{integration['id']}/sync", headers=tenant["headers"])


def test_sync_maps_records_and_authenticates(client, tenant_a, monkeypatch):
    seen = []

    def handler(request: httpx.Request):
        seen.append(request)
        return httpx.Response(200, json={"data": {"items": [record(1), record(2, "2026-10-01T12:00:00Z", qty=3)]}})

    serve(monkeypatch, handler)
    location, integration = make_integration(client, tenant_a)
    # page_size 2 and 2 items returned => the connector asks for page 2, which is empty
    responses = iter([{"data": {"items": [record(1), record(2, "2026-10-01T12:00:00Z", qty=3)]}}, {"data": {"items": []}}])
    serve(monkeypatch, lambda request: (seen.append(request), httpx.Response(200, json=next(responses)))[1])
    seen.clear()

    result = sync(client, tenant_a, integration)
    assert result.status_code == 200, result.text
    assert result.json()["imported"] == 2
    assert seen[0].headers["Authorization"] == "Bearer secret-token"
    assert seen[0].url.params["page"] == "1" and seen[1].url.params["page"] == "2"
    assert "updated_after" not in seen[0].url.params

    sales = {s["external_id"]: s for s in client.get("/api/sales", headers=tenant_a["headers"]).json()}
    assert Decimal(sales["T1"]["net_value"]) == Decimal("10")          # 1000 cents
    assert Decimal(sales["T2"]["gross_value"]) == Decimal("35.70")      # 3 * (10 + 1.90)
    assert sales["T2"]["lines"][0]["external_product_id"] == "BURGER"

    cursor = client.get("/api/integrations/pos", headers=tenant_a["headers"]).json()[0]["last_sync_cursor"]
    assert cursor == "2026-10-01T12:00:00Z"

    # the next sync sends the cursor and is idempotent when the API repeats a record
    seen.clear()
    serve(monkeypatch, lambda request: (seen.append(request), httpx.Response(200, json={"data": {"items": [record(2, "2026-10-01T12:00:00Z", qty=3)]}}))[1])
    second = sync(client, tenant_a, integration)
    assert second.json() == {"integration_id": integration["id"], "provider": "http", "fetched": 1, "imported": 0, "skipped_duplicates": 1}
    assert seen[0].url.params["updated_after"] == "2026-10-01T12:00:00Z"


def test_imported_sales_drive_recipes(client, tenant_a, monkeypatch):
    serve(monkeypatch, lambda request: httpx.Response(200, json={"data": {"items": [record(1, qty=4)]}}))
    location, integration = make_integration(client, tenant_a)
    burger = create_product(client, tenant_a, "Burger", sku="BURGER")
    beef = create_product(client, tenant_a, "Beef", base_uom="KG")
    add_stock(client, tenant_a, location, beef, "10", "KG")
    create_recipe(client, tenant_a, burger, [{"ingredient_product_id": beef["id"], "quantity": "0.2", "uom": "KG"}])
    assert sync(client, tenant_a, integration).status_code == 200
    assert Decimal(get_stock(client, tenant_a, location, beef)["quantity"]) == Decimal("9.2")


def test_retries_transient_failures_then_succeeds(client, tenant_a, monkeypatch):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503 if calls["n"] == 1 else 429, headers={"Retry-After": "1"})
        return httpx.Response(200, json={"data": {"items": [record(1)]}})

    serve(monkeypatch, handler)
    _, integration = make_integration(client, tenant_a)
    assert sync(client, tenant_a, integration).status_code == 200
    assert calls["n"] == 3


def test_persistent_outage_is_a_502_and_audited(client, tenant_a, monkeypatch):
    serve(monkeypatch, lambda request: httpx.Response(500))
    _, integration = make_integration(client, tenant_a)
    response = sync(client, tenant_a, integration)
    assert response.status_code == 502
    runs = client.get(f"/api/integrations/pos/{integration['id']}/sync-runs", headers=tenant_a["headers"]).json()
    assert runs[0]["status"] == "error" and "unavailable" in runs[0]["error_message"]


def test_rejected_credentials_and_missing_secret_are_configuration_errors(client, tenant_a, monkeypatch):
    serve(monkeypatch, lambda request: httpx.Response(401))
    _, integration = make_integration(client, tenant_a)
    bad = sync(client, tenant_a, integration)
    assert bad.status_code == 400 and "credentials" in bad.json()["detail"]

    monkeypatch.delenv("POS_TEST_TOKEN")
    missing = sync(client, tenant_a, integration)
    assert missing.status_code == 400 and "POS_TEST_TOKEN" in missing.json()["detail"]


def test_invalid_record_fails_loudly_and_imports_nothing(client, tenant_a, monkeypatch):
    broken = record(2)
    broken["lines"][0]["price"] = "abc"
    serve(monkeypatch, lambda request: httpx.Response(200, json={"data": {"items": [record(1), broken]}}))
    _, integration = make_integration(client, tenant_a)
    response = sync(client, tenant_a, integration)
    assert response.status_code == 400
    assert "Record 2" in response.json()["detail"]
    assert client.get("/api/sales", headers=tenant_a["headers"]).json() == []
    assert client.get("/api/integrations/pos", headers=tenant_a["headers"]).json()[0]["last_sync_cursor"] is None


def test_configuration_is_validated(client, tenant_a, monkeypatch):
    serve(monkeypatch, lambda request: httpx.Response(200, json={}))
    for broken in ({}, {**CONFIG, "sales_path": ""}, {**CONFIG, "mapping": {"external_id": "id"}}):
        _, integration = make_integration(client, tenant_a, config=broken)
        response = sync(client, tenant_a, integration)
        assert response.status_code == 400, broken
    _, no_url = make_integration(client, tenant_a, base_url=None)
    assert sync(client, tenant_a, no_url).status_code == 400


def test_private_and_non_https_urls_are_blocked(client, tenant_a, monkeypatch):
    serve(monkeypatch, lambda request: httpx.Response(200, json={"data": {"items": []}}))
    for url in ("http://pos.example.com", "ftp://pos.example.com"):
        _, integration = make_integration(client, tenant_a, base_url=url)
        assert sync(client, tenant_a, integration).status_code == 400
    for ip in ("127.0.0.1", "10.0.0.5", "169.254.169.254", "192.168.1.10", "::1"):
        monkeypatch.setattr(http_connector, "resolve_host", lambda host, ip=ip: [ip])
        _, integration = make_integration(client, tenant_a, base_url="https://internal.example.com")
        response = sync(client, tenant_a, integration)
        assert response.status_code == 400 and "private" in response.json()["detail"], ip


def test_connection_test_validates_mapping_on_a_sample(client, tenant_a, monkeypatch):
    serve(monkeypatch, lambda request: httpx.Response(200, json={"data": {"items": [record(1)]}}))
    _, integration = make_integration(client, tenant_a)
    ok = client.post(f"/api/integrations/pos/{integration['id']}/test", headers=tenant_a["headers"])
    assert ok.status_code == 200 and ok.json()["success"] is True

    serve(monkeypatch, lambda request: httpx.Response(200, json={"wrong": []}))
    bad = client.post(f"/api/integrations/pos/{integration['id']}/test", headers=tenant_a["headers"])
    assert bad.json()["success"] is False

    serve(monkeypatch, lambda request: httpx.Response(503))
    down = client.post(f"/api/integrations/pos/{integration['id']}/test", headers=tenant_a["headers"])
    assert down.status_code == 502


def test_server_cursor_page_tokens_epoch_time_and_header_auth(client, tenant_a, monkeypatch):
    config = {
        **CONFIG,
        "page_param": None, "page_token_param": "after", "next_page_token_path": "paging.next",
        "next_cursor_path": "paging.cursor", "time_format": "epoch_ms", "amount_divisor": 1,
        "auth": {"type": "header", "header_name": "X-Api-Key"},
    }
    pages = iter([
        {"data": {"items": [{**record(1), "created_at": 1790000000000}]}, "paging": {"next": "p2"}},
        {"data": {"items": [{**record(2), "created_at": 1790000060000}]}, "paging": {"cursor": "CUR-2"}},
    ])
    seen = []
    serve(monkeypatch, lambda request: (seen.append(request), httpx.Response(200, json=next(pages)))[1])
    _, integration = make_integration(client, tenant_a, config=config)
    result = sync(client, tenant_a, integration)
    assert result.json()["imported"] == 2
    assert seen[0].headers["X-Api-Key"] == "secret-token"
    assert seen[1].url.params["after"] == "p2"
    assert client.get("/api/integrations/pos", headers=tenant_a["headers"]).json()[0]["last_sync_cursor"] == "CUR-2"
    sale = client.get("/api/sales", headers=tenant_a["headers"]).json()[-1]
    assert sale["occurred_at"].startswith("2026-09-")  # epoch converted to UTC


def test_get_path_helper():
    data = {"a": {"b": [{"c": 5}]}}
    assert http_connector.get_path(data, "a.b.0.c") == 5
    assert http_connector.get_path(data, "a.x") is None
    assert http_connector.get_path(data, "a.b.3") is None
    assert http_connector.get_path(data, None) is None
