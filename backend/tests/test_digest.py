from datetime import datetime, timedelta, timezone

from app.core.database import SessionLocal
from app.models.company import Company
from app.services import email
from app.services.digest import send_alert_digests
from tests.conftest import add_stock, create_location, create_user


def make_problem(client, tenant):
    location = create_location(client, tenant)
    beef = client.post("/api/products", headers=tenant["headers"], json={"name": "Beef", "base_uom": "KG", "reorder_level": "5"}).json()
    add_stock(client, tenant, location, beef, "1", "KG")


def run(now=None):
    with SessionLocal() as db:
        return send_alert_digests(db, now)


def test_no_alerts_no_email(client, tenant_a):
    assert run() == 0
    assert email.outbox == []


def test_owner_gets_a_digest_once_per_day(client, tenant_a, manager_a):
    make_problem(client, tenant_a)
    assert run() == 1
    assert [m["to"] for m in email.outbox] == [tenant_a["email"]]  # managers are not included
    assert "low_stock" in email.outbox[0]["subject"] or "Beef" in email.outbox[0]["body"]
    assert run() == 0  # within 24h
    later = datetime.now(timezone.utc) + timedelta(hours=25)
    assert run(later) == 1
    assert len(email.outbox) == 2


def test_digest_can_be_disabled_per_company(client, tenant_a):
    make_problem(client, tenant_a)
    response = client.patch(f"/api/companies/{tenant_a['company_id']}", headers=tenant_a["headers"], json={"alert_digest_enabled": False})
    assert response.json()["alert_digest_enabled"] is False
    assert run() == 0


def test_digest_only_for_own_company_and_skips_info_alerts(client, tenant_a, tenant_b):
    make_problem(client, tenant_a)
    from tests.conftest import create_integration, import_sales, line, sale_payload

    location = create_location(client, tenant_b)
    integration = create_integration(client, tenant_b, location, provider="mock")
    import_sales(client, tenant_b, integration, sale_payload("S1", lines=[line("Mystery", "NOPE")]))  # info only
    assert run() == 1
    assert [m["to"] for m in email.outbox] == [tenant_a["email"]]


def test_inactive_company_is_skipped(client, tenant_a):
    make_problem(client, tenant_a)
    with SessionLocal() as db:
        db.get(Company, tenant_a["company_id"]).active = False
        db.commit()
    assert run() == 0
