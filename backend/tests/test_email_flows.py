import re
from datetime import datetime, timedelta, timezone

from app.core.database import SessionLocal
from app.models.password_reset import PasswordResetToken
from app.services import email


def request_reset(client, address):
    return client.post("/api/auth/password-reset/request", json={"email": address})


def token_from_outbox(index=-1):
    return re.search(r"reset_token=([\w-]+)", email.outbox[index]["body"]).group(1)


def test_reset_flow_end_to_end(client, tenant_a):
    assert request_reset(client, tenant_a["email"]).status_code == 202
    assert [m["to"] for m in email.outbox] == [tenant_a["email"]]
    token = token_from_outbox()

    confirm = client.post("/api/auth/password-reset/confirm", json={"token": token, "new_password": "brand-new-pass"})
    assert confirm.status_code == 200, confirm.text
    new_headers = {"Authorization": f"Bearer {confirm.json()['access_token']}"}
    assert client.get("/api/auth/me", headers=new_headers).status_code == 200
    assert client.get("/api/auth/me", headers=tenant_a["headers"]).status_code == 401  # old session revoked
    assert client.post("/api/auth/login", json={"email": tenant_a["email"], "password": tenant_a["password"]}).status_code == 401
    assert client.post("/api/auth/login", json={"email": tenant_a["email"], "password": "brand-new-pass"}).status_code == 200


def test_token_is_single_use_and_newer_request_invalidates_older(client, tenant_a):
    request_reset(client, tenant_a["email"])
    request_reset(client, tenant_a["email"])
    first, second = token_from_outbox(0), token_from_outbox(1)
    body = lambda t: {"token": t, "new_password": "brand-new-pass"}
    assert client.post("/api/auth/password-reset/confirm", json=body(first)).status_code == 400
    assert client.post("/api/auth/password-reset/confirm", json=body(second)).status_code == 200
    assert client.post("/api/auth/password-reset/confirm", json=body(second)).status_code == 400


def test_expired_and_garbage_tokens_rejected(client, tenant_a):
    request_reset(client, tenant_a["email"])
    token = token_from_outbox()
    with SessionLocal() as db:
        row = db.query(PasswordResetToken).one()
        row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()
    assert client.post("/api/auth/password-reset/confirm", json={"token": token, "new_password": "brand-new-pass"}).status_code == 400
    assert client.post("/api/auth/password-reset/confirm", json={"token": "x" * 30, "new_password": "brand-new-pass"}).status_code == 400
    assert client.post("/api/auth/password-reset/confirm", json={"token": token, "new_password": "short"}).status_code == 422


def test_request_does_not_reveal_whether_account_exists(client, tenant_a):
    known = request_reset(client, tenant_a["email"])
    unknown = request_reset(client, "nobody@test.dev")
    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json()
    assert len(email.outbox) == 1


def test_inactive_user_gets_no_reset_email(client, tenant_a, manager_a):
    client.delete(f"/api/users/{manager_a['user']['id']}", headers=tenant_a["headers"])
    request_reset(client, "manager-a@test.dev")
    assert email.outbox == []


def test_reset_requests_are_rate_limited(client, tenant_a):
    for _ in range(8):
        assert request_reset(client, tenant_a["email"]).status_code == 202
    assert len(email.outbox) == 5


def test_stored_token_is_a_hash(client, tenant_a):
    request_reset(client, tenant_a["email"])
    token = token_from_outbox()
    with SessionLocal() as db:
        assert db.query(PasswordResetToken).one().token_hash != token


# ---- invitations
def invite(client, headers, address="new@test.dev", role="employee"):
    return client.post(
        "/api/users/invite", headers=headers,
        json={"email": address, "first_name": "New", "last_name": "Hire", "role": role},
    )


def test_invitation_lets_the_invitee_set_a_password(client, tenant_a):
    response = invite(client, tenant_a["headers"])
    assert response.status_code == 201, response.text
    assert response.json()["role"] == "employee"
    assert "invited you" in email.outbox[0]["body"]
    token = token_from_outbox()
    done = client.post("/api/auth/password-reset/confirm", json={"token": token, "new_password": "my-own-password"})
    assert done.status_code == 200
    assert done.json()["user"]["email"] == "new@test.dev"
    assert client.post("/api/auth/login", json={"email": "new@test.dev", "password": "my-own-password"}).status_code == 200


def test_invite_rules(client, tenant_a, manager_a, employee_a):
    assert invite(client, employee_a["headers"]).status_code == 403
    assert invite(client, manager_a["headers"], "o@test.dev", "owner").status_code == 403
    assert invite(client, manager_a["headers"], "m@test.dev", "manager").status_code == 201
    assert invite(client, tenant_a["headers"], "m@test.dev").status_code == 409


def test_invite_respects_plan_limit(client, tenant_a):
    from app.models.company import Company

    with SessionLocal() as db:
        db.get(Company, tenant_a["company_id"]).plan = "trial"  # 3 users
        db.commit()
    assert invite(client, tenant_a["headers"], "a@test.dev").status_code == 201
    assert invite(client, tenant_a["headers"], "b@test.dev").status_code == 201
    assert invite(client, tenant_a["headers"], "c@test.dev").status_code == 402


def test_unsent_invitation_is_reported(client, tenant_a, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "email_backend", "smtp")
    monkeypatch.setattr(settings, "smtp_host", None)
    assert invite(client, tenant_a["headers"], "late@test.dev").status_code == 502
    # the account exists, so a manager can recover with an admin reset
    users = client.get("/api/users", headers=tenant_a["headers"]).json()
    assert "late@test.dev" in [u["email"] for u in users]
