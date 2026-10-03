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

## Background synchronisation

Set `sync_interval_minutes` (5–1440) on an integration to have the `worker` service sync it
automatically (`python -m app.worker`). Failures retry with exponential backoff (1, 2, 4 … 60 min);
after 5 consecutive failures the schedule pauses and `sync_paused_reason` explains why. Updating
`sync_interval_minutes` resumes it. Runs stuck in `running` for 15 minutes are marked failed.
Several workers can run at once.

## Database migrations

The migration chain currently reaches:

`0001 → 0002 → 0003 → 0004 → 0005 → 0006 → 0007 → 0008 → 0009 → 0010 → 0011 → 0012 → 0013 → 0014 → 0015 → 0016 → 0017 → 0018`

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

- Set `APP_ENV=production` and a strong, unique `JWT_SECRET_KEY` (at least 32 characters); the API refuses to start in production with the default or a short secret.
- Set `CORS_ORIGINS` to the deployed frontend origin(s).
- Webhook tokens are generated with `POST /api/integrations/pos/{id}/webhook-token` and stored only as SHA-256 hashes. Provider credentials (`credentials_ref`) should point to a secret manager.
- Migrations run automatically through the one-shot `migrate` service in `docker-compose.yml`; when deploying elsewhere, run `alembic upgrade head` as a release step before starting the API.
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

Warning: all tables in the test database are dropped and recreated on every run. Never point `TEST_DATABASE_URL` at real data.

## CSV sales import (any POS)

For POS systems without an API, create an integration with provider `csv` and upload an export:

```bash
curl -X POST "http://localhost:8000/api/sales/import-csv?integration_id=1" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: text/csv" --data-binary @sales.csv
```

One row per sale line. Required columns: `sale_id`, `occurred_at`, `product_name`, `quantity`, `unit_price`.
Optional: `currency`, `external_product_id`, `uom`, `net_value`, `tax_value`. `,` and `;` delimiters are
detected (decimal comma allowed with `;`). The file is all-or-nothing and re-uploading is idempotent.
