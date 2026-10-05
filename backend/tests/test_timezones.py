from datetime import date
from decimal import Decimal

from tests.conftest import bootstrap, create_integration, create_location, create_product, import_sales, line, sale_payload


def make_location(client, tenant, name, timezone=None):
    body = {"company_id": tenant["company_id"], "name": name}
    if timezone:
        body["timezone"] = timezone
    return client.post("/api/locations", headers=tenant["headers"], json=body)


def daily(client, tenant, **params):
    response = client.get("/api/reports/daily-sales", headers=tenant["headers"], params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_location_timezone_default_validation_and_update(client, tenant_a):
    assert make_location(client, tenant_a, "Default").json()["timezone"] == "Europe/Bucharest"
    assert make_location(client, tenant_a, "Bad", "Mars/Olympus").status_code == 422
    assert make_location(client, tenant_a, "Bad2", "../../etc/passwd").status_code == 422
    location = make_location(client, tenant_a, "Lisbon", "Europe/Lisbon").json()
    assert client.patch(f"/api/locations/{location['id']}", headers=tenant_a["headers"], json={"timezone": "Asia/Tokyo"}).json()["timezone"] == "Asia/Tokyo"
    assert client.patch(f"/api/locations/{location['id']}", headers=tenant_a["headers"], json={"timezone": "nope"}).status_code == 422


def test_day_boundaries_follow_the_location_time_zone(client, tenant_a):
    bucharest = make_location(client, tenant_a, "Bucharest", "Europe/Bucharest").json()  # UTC+3 in October
    london = make_location(client, tenant_a, "London", "Europe/London").json()          # UTC+1 in October
    b_int = create_integration(client, tenant_a, bucharest, provider="mock")
    l_int = create_integration(client, tenant_a, london, provider="mock")
    # 2026-10-01 22:30 UTC = 01:30 on Oct 2 in Bucharest, 23:30 on Oct 1 in London
    import_sales(client, tenant_a, b_int, sale_payload("B1", occurred_at="2026-10-01T22:30:00Z", net="100.00", tax="19.00"))
    import_sales(client, tenant_a, l_int, sale_payload("L1", occurred_at="2026-10-01T22:30:00Z", net="50.00", tax="9.50"))
    rows = {(r["date"], r["location_id"]): r for r in daily(client, tenant_a)}
    assert set(rows) == {("2026-10-02", bucharest["id"]), ("2026-10-01", london["id"])}
    assert Decimal(rows[("2026-10-02", bucharest["id"])]["net_revenue"]) == Decimal("100.00")
    assert rows[("2026-10-01", london["id"])]["sales"] == 1


def test_daily_report_filters_refunds_and_cancellations(client, tenant_a):
    location = make_location(client, tenant_a, "Main").json()
    integration = create_integration(client, tenant_a, location, provider="mock")
    create_product(client, tenant_a, "Burger", sku="B")
    import_sales(client, tenant_a, integration,
                 sale_payload("S1", occurred_at="2026-10-01T10:00:00Z", net="40.00", tax="7.60", lines=[line("Burger", "B", quantity="4", price="10")]),
                 sale_payload("S2", occurred_at="2026-10-01T11:00:00Z", net="10.00", tax="1.90"),
                 sale_payload("S3", occurred_at="2026-10-03T11:00:00Z", net="20.00", tax="3.80"))
    sales = {s["external_id"]: s for s in client.get("/api/sales", headers=tenant_a["headers"]).json()}
    client.post(f"/api/sales/{sales['S2']['id']}/status", headers=tenant_a["headers"], json={"status": "cancelled"})
    client.post(f"/api/sales/{sales['S1']['id']}/refund-lines", headers=tenant_a["headers"],
                json={"lines": [{"line_id": sales["S1"]["lines"][0]["id"], "quantity": "1"}]})

    day = daily(client, tenant_a, date_from="2026-10-01", date_to="2026-10-01")
    assert len(day) == 1
    assert day[0]["sales"] == 1 and day[0]["cancelled"] == 1
    assert Decimal(day[0]["net_revenue"]) == Decimal("30.00")   # 40 - 10 refunded
    assert [r["date"] for r in daily(client, tenant_a, date_from="2026-10-02")] == ["2026-10-03"]
    assert daily(client, tenant_a, date_to="2026-09-30") == []
    assert date.fromisoformat(daily(client, tenant_a)[0]["date"]) == date(2026, 10, 1)


def test_daily_report_is_tenant_scoped(client, tenant_a, tenant_b):
    location = make_location(client, tenant_a, "Main").json()
    integration = create_integration(client, tenant_a, location, provider="mock")
    import_sales(client, tenant_a, integration, sale_payload("S1"))
    assert daily(client, tenant_b) == []
    other = make_location(client, tenant_b, "Other").json()
    assert daily(client, tenant_b, location_id=location["id"]) == []
    assert other["id"] != location["id"]
