from datetime import datetime, timedelta, timezone

import pytest

from app.core.database import SessionLocal
from app.models.pos_integration import POSIntegration
from app.models.sync_run import SyncRun
from app.services import pos_connectors
from app.services.sync import (
    MAX_CONSECUTIVE_FAILURES,
    backoff_minutes,
    claim_due_integrations,
    fail_stale_runs,
    run_due_syncs,
)
from tests.conftest import create_integration, create_location


def make(client, tenant, provider="demo", interval=15):
    location = create_location(client, tenant)
    body = {"location_id": location["id"], "provider": provider, "name": "x"}
    if interval:
        body["sync_interval_minutes"] = interval
    response = client.post("/api/integrations/pos", headers=tenant["headers"], json=body)
    assert response.status_code == 201, response.text
    return response.json()


def state(integration_id):
    with SessionLocal() as db:
        row = db.get(POSIntegration, integration_id)
        return {
            "next": row.next_sync_at,
            "failures": row.consecutive_failures,
            "paused": row.sync_paused_reason,
            "status": row.status,
            "cursor": row.last_sync_cursor,
        }


def make_due(integration_id, minutes_ago=1):
    with SessionLocal() as db:
        db.get(POSIntegration, integration_id).next_sync_at = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
        db.commit()


def tick():
    with SessionLocal() as db:
        return run_due_syncs(db)


class FailingConnector:
    def test_connection(self, integration):
        ...

    def pull_sales(self, integration, cursor=None):
        raise RuntimeError("pos is down")


@pytest.fixture()
def failing_provider():
    saved = dict(pos_connectors.CONNECTORS)
    pos_connectors.register_connector("down", FailingConnector())
    yield
    pos_connectors.CONNECTORS.clear()
    pos_connectors.CONNECTORS.update(saved)


def test_interval_validation_and_initial_schedule(client, tenant_a):
    location = create_location(client, tenant_a)
    bad = client.post(
        "/api/integrations/pos",
        headers=tenant_a["headers"],
        json={"location_id": location["id"], "provider": "demo", "name": "x", "sync_interval_minutes": 1},
    )
    assert bad.status_code == 422
    integration = make(client, tenant_a)
    assert integration["sync_interval_minutes"] == 15
    assert integration["next_sync_at"] is not None
    assert make(client, tenant_a, interval=None)["next_sync_at"] is None


def test_due_integration_is_synced_and_rescheduled(client, tenant_a):
    integration = make(client, tenant_a)
    assert tick() == 1
    assert len(client.get("/api/sales", headers=tenant_a["headers"]).json()) == 2
    after = state(integration["id"])
    assert after["cursor"] == "2026-10-01T19:15:00Z"
    assert after["next"] > datetime.now(timezone.utc) + timedelta(minutes=14)
    runs = client.get(f"/api/integrations/pos/{integration['id']}/sync-runs", headers=tenant_a["headers"]).json()
    assert [r["trigger"] for r in runs] == ["scheduled"]
    assert tick() == 0


def test_not_yet_due_and_manual_only_integrations_are_skipped(client, tenant_a):
    scheduled = make(client, tenant_a)
    make_due(scheduled["id"], minutes_ago=-30)
    make(client, tenant_a, interval=None)
    assert tick() == 0


def test_inactive_integration_is_not_scheduled(client, tenant_a):
    integration = make(client, tenant_a)
    client.delete(f"/api/integrations/pos/{integration['id']}", headers=tenant_a["headers"])
    assert tick() == 0


def test_claim_leases_integration_so_a_second_worker_skips_it(client, tenant_a):
    integration = make(client, tenant_a)
    with SessionLocal() as db:
        assert claim_due_integrations(db) == [integration["id"]]
    with SessionLocal() as db:
        assert claim_due_integrations(db) == []


def test_failures_back_off_then_pause(client, tenant_a, failing_provider):
    integration = make(client, tenant_a, provider="down")
    previous_delay = timedelta(0)
    for attempt in range(1, MAX_CONSECUTIVE_FAILURES + 1):
        make_due(integration["id"])
        assert tick() == 1
        current = state(integration["id"])
        assert current["failures"] == attempt
        assert current["status"] == "error"
        if attempt < MAX_CONSECUTIVE_FAILURES:
            delay = current["next"] - datetime.now(timezone.utc)
            assert delay > previous_delay
            previous_delay = delay
    final = state(integration["id"])
    assert final["next"] is None
    assert "pos is down" in final["paused"]
    assert tick() == 0

    runs = client.get(f"/api/integrations/pos/{integration['id']}/sync-runs", headers=tenant_a["headers"]).json()
    assert len(runs) == MAX_CONSECUTIVE_FAILURES
    assert all(r["status"] == "error" and r["trigger"] == "scheduled" for r in runs)


def test_reconfiguring_schedule_resumes_paused_integration(client, tenant_a, failing_provider):
    integration = make(client, tenant_a, provider="down")
    for _ in range(MAX_CONSECUTIVE_FAILURES):
        make_due(integration["id"])
        tick()
    assert state(integration["id"])["paused"]
    response = client.patch(
        f"/api/integrations/pos/{integration['id']}", headers=tenant_a["headers"], json={"sync_interval_minutes": 30}
    )
    assert response.status_code == 200
    resumed = state(integration["id"])
    assert resumed["paused"] is None and resumed["failures"] == 0 and resumed["next"] is not None


def test_success_after_failure_resets_counter(client, tenant_a, failing_provider):
    integration = make(client, tenant_a, provider="down")
    make_due(integration["id"])
    tick()
    assert state(integration["id"])["failures"] == 1
    pos_connectors.register_connector("down", pos_connectors.MockPOSConnector())
    make_due(integration["id"])
    tick()
    assert state(integration["id"])["failures"] == 0
    assert state(integration["id"])["status"] == "connected"


def test_removing_interval_disables_schedule(client, tenant_a):
    integration = make(client, tenant_a)
    client.patch(f"/api/integrations/pos/{integration['id']}", headers=tenant_a["headers"], json={"sync_interval_minutes": None})
    assert state(integration["id"])["next"] is None


def test_stale_running_runs_are_failed(client, tenant_a):
    integration = make(client, tenant_a, interval=None)
    with SessionLocal() as db:
        db.add(
            SyncRun(
                company_id=tenant_a["company_id"],
                integration_id=integration["id"],
                started_at=datetime.now(timezone.utc) - timedelta(hours=1),
                status="running",
            )
        )
        db.add(
            SyncRun(
                company_id=tenant_a["company_id"],
                integration_id=integration["id"],
                started_at=datetime.now(timezone.utc),
                status="running",
            )
        )
        db.commit()
        assert fail_stale_runs(db) == 1


def test_backoff_is_exponential_and_capped():
    assert [backoff_minutes(n) for n in (1, 2, 3, 4)] == [1, 2, 4, 8]
    assert backoff_minutes(20) == 60
