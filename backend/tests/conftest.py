import os

# Must be set before the application settings are imported.
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://horeca:change-me@localhost:5432/horeca_test",
)
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-with-at-least-32-bytes")

import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.database import SessionLocal, engine
from app.main import app
from app.models.base import Base


@pytest.fixture(scope="session", autouse=True)
def migrated_database():
    """Build the schema from the Alembic chain so migrations are exercised too."""
    Base.metadata.drop_all(engine)
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS alembic_version"))

    # Run the CLI in a subprocess: the local ``alembic/`` directory shadows the
    # installed package when it is imported from the backend root.
    backend_dir = os.path.join(os.path.dirname(__file__), "..")
    subprocess.run(
        [shutil.which("alembic") or "alembic", "upgrade", "head"],
        cwd=backend_dir,
        check=True,
        env={**os.environ, "DATABASE_URL": TEST_DATABASE_URL},
    )
    yield


@pytest.fixture(autouse=True)
def clean_tables(migrated_database):
    yield
    tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    with engine.begin() as connection:
        connection.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


@pytest.fixture(autouse=True)
def reset_login_limiter():
    from app.api.auth import login_limiter

    login_limiter.clear()
    yield
    login_limiter.clear()


@pytest.fixture()
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def db():
    with SessionLocal() as session:
        yield session


def bootstrap(client, company_name="Acme", email="owner@acme.dev", password="password123"):
    response = client.post(
        "/api/auth/bootstrap",
        json={
            "company_name": company_name,
            "email": email,
            "first_name": "Owner",
            "last_name": company_name,
            "password": password,
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return {
        "token": body["access_token"],
        "headers": {"Authorization": f"Bearer {body['access_token']}"},
        "user": body["user"],
        "company_id": body["user"]["company_id"],
        "email": email,
        "password": password,
    }


@pytest.fixture()
def tenant_a(client):
    return bootstrap(client, "Tenant A", "owner-a@test.dev")


@pytest.fixture()
def tenant_b(client):
    return bootstrap(client, "Tenant B", "owner-b@test.dev")


def create_user(client, owner, role, email):
    response = client.post(
        "/api/users",
        headers=owner["headers"],
        json={
            "company_id": owner["company_id"],
            "email": email,
            "first_name": role.title(),
            "last_name": "User",
            "password": "password123",
            "role": role,
        },
    )
    assert response.status_code == 201, response.text
    login = client.post("/api/auth/login", json={"email": email, "password": "password123"})
    assert login.status_code == 200, login.text
    return {"headers": {"Authorization": f"Bearer {login.json()['access_token']}"}, "user": response.json()}


@pytest.fixture()
def manager_a(client, tenant_a):
    return create_user(client, tenant_a, "manager", "manager-a@test.dev")


@pytest.fixture()
def employee_a(client, tenant_a):
    return create_user(client, tenant_a, "employee", "employee-a@test.dev")


def create_location(client, tenant, name="Main"):
    response = client.post(
        "/api/locations",
        headers=tenant["headers"],
        json={"company_id": tenant["company_id"], "name": name},
    )
    assert response.status_code == 201, response.text
    return response.json()


def create_product(client, tenant, name="Burger", sku=None, base_uom="EA"):
    response = client.post(
        "/api/products",
        headers=tenant["headers"],
        json={"name": name, "sku": sku, "base_uom": base_uom},
    )
    assert response.status_code == 201, response.text
    return response.json()


def create_integration(client, tenant, location, provider="demo", config=None):
    response = client.post(
        "/api/integrations/pos",
        headers=tenant["headers"],
        json={
            "location_id": location["id"],
            "provider": provider,
            "name": f"{provider} POS",
            "config": config,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def sale_payload(external_id="S1", lines=None, occurred_at="2026-10-01T10:00:00Z", net="10.00", tax="1.90"):
    lines = lines or [
        {
            "external_product_id": "EXT-1",
            "product_name": "Burger",
            "quantity": "1",
            "uom": "EA",
            "unit_price": "10.00",
            "net_value": "10.00",
            "tax_value": "1.90",
        }
    ]
    from decimal import Decimal

    return {
        "external_id": external_id,
        "occurred_at": occurred_at,
        "currency": "RON",
        "net_value": net,
        "tax_value": tax,
        "gross_value": str(Decimal(net) + Decimal(tax)),
        "lines": lines,
    }


def import_sales(client, tenant, integration, *sales):
    return client.post(
        "/api/sales/import",
        headers=tenant["headers"],
        json={"integration_id": integration["id"], "sales": list(sales)},
    )


def line(product_name="Burger", external_product_id="EXT-1", quantity="1", uom="EA", price="10.00"):
    return {
        "external_product_id": external_product_id,
        "product_name": product_name,
        "quantity": quantity,
        "uom": uom,
        "unit_price": price,
        "net_value": str(float(price) * float(quantity)),
        "tax_value": "0",
    }


def add_stock(client, tenant, location, product, quantity, uom):
    response = client.post(
        "/api/inventory/adjustments",
        headers=tenant["headers"],
        json={
            "location_id": location["id"],
            "product_id": product["id"],
            "quantity": str(quantity),
            "uom": uom,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def get_stock(client, tenant, location, product):
    rows = client.get("/api/inventory/stock", headers=tenant["headers"]).json()
    for row in rows:
        if row["location_id"] == location["id"] and row["product_id"] == product["id"]:
            return row
    return None


def create_recipe(client, tenant, product, lines, location=None, name="Recipe"):
    response = client.post(
        "/api/recipes",
        headers=tenant["headers"],
        json={
            "product_id": product["id"],
            "location_id": location["id"] if location else None,
            "name": name,
            "lines": lines,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def with_webhook_token(client, tenant, integration):
    """Generate a webhook token and attach it to the integration dict as ``token``."""
    response = client.post(
        f"/api/integrations/pos/{integration['id']}/webhook-token", headers=tenant["headers"]
    )
    assert response.status_code == 200, response.text
    return {**integration, "token": response.json()["webhook_token"]}
