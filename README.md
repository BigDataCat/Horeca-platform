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

## Documentation

- [docs/ROADMAP.md](docs/ROADMAP.md) – status of every area and what is still open
- [docs/OPERATIONS.md](docs/OPERATIONS.md) – deployment, releases, backups, monitoring, incidents
- [docs/CONNECTORS.md](docs/CONNECTORS.md) – how to write a POS connector
- [docs/PRIVACY.md](docs/PRIVACY.md) – data stored, GDPR tooling, retention decisions
- [e2e/README.md](e2e/README.md) – browser smoke test

## Implemented modules

- Sale cancellations/refunds with stock reversal, CSV sales import, scheduled background sync with retries
- Suppliers, goods receipts, stock counts, transfers, margin / food-cost report
- Audit log, alerts, CSV exports, plans with limits, admin support API, Prometheus metrics

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

## Audit log, exports and alerts

- `GET /api/audit-log` (owner/manager): who created/changed/deleted products, costs, recipes, mappings,
  users, integrations, suppliers, receipts, counts and transfers, plus sale cancellations. Recorded
  automatically in the same transaction; secrets (passwords, tokens, config values) are never logged.
- List endpoints accept `limit`/`offset` and return the full count in `X-Total-Count`; sales, movements and
  stock also accept date/location/status filters. CSV exports: `/api/sales/export.csv`,
  `/api/inventory/movements/export.csv`, `/api/reports/margins.csv`.
- `GET /api/alerts` computes operational alerts (low/negative stock via `reorder_level`, failed/paused/stale
  sync, failed webhooks, unmatched products, missing ingredient costs). There is no notification
  delivery yet (email/push): alerts are pulled by the UI.

## Plans, administration and metrics

- Plans (`trial`, `starter`, `business`, `unlimited`) limit active locations, users and integrations
  (HTTP 402 when exceeded). New companies get `DEFAULT_PLAN` (default `business`; use `trial` for self-service
  sign-up). `GET /api/subscription` returns plan, limits and usage. There is no payment provider yet:
  plans are changed by platform staff.
- Set `TRIAL_DAYS` to give new companies a time-limited subscription: after `plan_expires_at` the account is
  read-only (reads and exports work, writes return 402) until platform staff renew it.
- Support/admin API, disabled unless `ADMIN_API_KEY` is set: `GET /api/admin/companies` and
  `PATCH /api/admin/companies/{id}` (`plan`, `active`) with header `X-Admin-Key`. Deactivating a company
  signs all its users out.
- `GET /metrics` exposes Prometheus counters (set `METRICS_TOKEN` to require `Authorization: Bearer ...`).
  Counters are per process.

## E-mail

Password reset (`POST /api/auth/password-reset/request|confirm`), invitations (`POST /api/users/invite`) and a
daily alert digest to owners need an SMTP server: set `EMAIL_BACKEND=smtp`, `SMTP_HOST`, `SMTP_PORT`,
`SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, and `APP_BASE_URL` (used in links). In development the default
`console` backend logs the message instead; tests use `memory`. Reset requests never reveal whether an
account exists and are rate limited.

## Database migrations

The migration chain currently reaches:

`0001 → 0002 → 0003 → 0004 → 0005 → 0006 → 0007 → 0008 → 0009 → 0010 → 0011 → 0012 → 0013 → 0014 → 0015 → 0016 → 0017 → 0018 → 0019 → 0020 → 0021 → 0022 → 0023 → 0024 → 0025 → 0026`

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
- Use `deploy/docker-compose.prod.yml` (TLS, no exposed DB, backups) – see [docs/OPERATIONS.md](docs/OPERATIONS.md).
- Replace demo/mock connectors with a provider-specific implementation ([docs/CONNECTORS.md](docs/CONNECTORS.md)); until then use CSV import.


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
