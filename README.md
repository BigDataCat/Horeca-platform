# HoReCa Platform

Integration-first SaaS platform for HoReCa management and intelligence.

The platform is designed to integrate with existing POS systems rather than replace them.

## Architecture

```
Existing POS
   │
   ├── API polling ──┐
   └── Webhooks ─────┤
                     ▼
              POS Connector Layer
                     ▼
              Canonical Sales Model
                     ▼
        Sales + Product Mapping + UOM
                     ▼
             Inventory / Recipes
                     ▼
               Product Costing
                     ▼
                Dashboard
```

## Implemented modules

- Multi-tenant companies and locations
- JWT authentication and role-based access
- Product master
- POS integration management
- Provider catalog
- Connector abstraction with demo/mock providers
- Idempotent sales ingestion
- Incremental sync cursor/watermark
- POS sync audit history
- Product mapping
- UOM conversion
- Unmatched product workflow
- Inventory balances and stock movements
- Recipe management and automatic recipe consumption
- Product cost history
- Recipe cost calculation
- Operations dashboard
- POS webhook ingestion with event idempotency
- Database health check
- Environment-driven CORS configuration

## API areas

- `/api/auth`
- `/api/companies`
- `/api/locations`
- `/api/users`
- `/api/products`
- `/api/integrations/pos`
- `/api/product-mappings`
- `/api/sales`
- `/api/inventory`
- `/api/recipes`
- `/api/costs`
- `/api/dashboard`

## Database migrations

The migration chain currently reaches:

`0001 → 0002 → 0003 → 0004 → 0005 → 0006 → 0007 → 0008 → 0009 → 0010 → 0011 → 0012 → 0013`

## Run locally

### 1. Start PostgreSQL

Copy `.env.example` to `.env` and adjust credentials if needed.

Then:

```bash
docker compose up -d postgres
```

### 2. Start the backend

From `backend/`:

```bash
python -m venv .venv
# Windows:
.venv\\Scripts\\activate
# macOS/Linux:
# source .venv/bin/activate

pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload
```

API: `http://localhost:8000`

Swagger: `http://localhost:8000/docs`

### 3. Start the frontend

From `frontend/`:

```bash
npm install
npm run dev
```

The frontend expects the API at `http://localhost:8000/api`.

Override it with `frontend/.env`:

```text
VITE_API_URL=http://localhost:8000/api
```

## Production notes

- Set a strong `JWT_SECRET_KEY`.
- Set `CORS_ORIGINS` to the deployed frontend origin(s).
- Store POS webhook tokens in a proper secret manager before production.
- Run Alembic migrations before starting the API.
- Use HTTPS for API and webhook endpoints.
- Replace demo/mock connectors with provider-specific implementations.

## Roadmap

See [docs/ROADMAP.md](docs/ROADMAP.md) for remaining work, priorities and phases.

## Tests

Backend tests run against a real PostgreSQL database (the schema is built with Alembic, so the migrations are exercised too):

```bash
cd backend
pip install -r requirements-dev.txt
# create a throwaway database, e.g. horeca_test, then:
export TEST_DATABASE_URL=postgresql+psycopg://horeca:change-me@localhost:5432/horeca_test
pytest
```

Warning: the test database is dropped and recreated on every run. Never point `TEST_DATABASE_URL` at real data.
