# Roadmap

Baseline: 3 October 2026. Derived from the Soft POS Complete Project Blueprint, extended with gaps identified after review.

Items marked **(new)** are additions to the original blueprint.

## Already implemented

Multi-tenant companies/locations, JWT auth and roles, products, POS integrations and provider catalog, connector abstraction with demo/mock connectors, incremental sync cursor and sync history, idempotent sales import, product mapping, UOM conversions, unmatched products, webhooks with event idempotency, inventory and stock movements, recipes with automatic consumption, product cost history, recipe costing, operations and inventory dashboards, health check, env-based CORS, Dockerfiles, Nginx API proxy, full Docker Compose stack, `.env.example`.

## Priorities

| Priority | Work |
|----------|------|
| P0 | Automated tests + CI |
| P0 | Production security hardening |
| P0 | First real POS connector |
| P0 (new) | User lifecycle (invites, password reset/change, deactivation, token refresh, logout) |
| P0 (new) | Sale cancellations, returns and voids from the POS |
| P1 | Background sync + retries, webhook replay / dead-letter |
| P1 (new) | Goods receipts, suppliers, physical stock counts, inter-location transfers |
| P1 (new) | Automatic ingredient costs (from receipts/invoices), food cost % and margin reports |
| P1 | Operational UX: mapping, recipes, costs, inventory workflows, filters |
| P1 | Staging pilot |
| P2 | Observability, alerts (new: low stock, failed sync, new unmatched products, missing cost) |
| P2 (new) | Audit log of user actions (cost, stock, recipe, mapping changes) |
| P2 (new) | Pagination, filters and CSV/Excel export |
| P2 (new) | Sub-recipes, modifiers and combo/menu items |
| P2 (new) | Bulk onboarding import (products, recipes, opening stock) from Excel/CSV |
| P2 | Second/third POS connectors |
| P3 | Billing, subscriptions, plan limits |
| P3 (new) | Romanian fiscal/localisation (VAT rates, e-Factura, fiscal registers if required, currency/timezone per location) |
| P3 (new) | Frontend i18n (RO/EN) |

## Phases

### Phase 0 — Baseline and freeze
- Tag a baseline release; record migration head (`0012`) and versions.
- Keep Docker Compose as the reproducible dev baseline.

### Phase 1 — Automated quality layer
- pytest, fixtures (company/user/location/product/integration).
- Tests: auth and invalid tokens, roles, tenant isolation, mapping, UOM, duplicate sales, sync cursor, recipe selection/fallback, waste, stock adjustments, webhook auth and duplicates, recipe costing, dashboard totals.
- Frontend build validation.
- (new) Volume/performance test of ingestion (thousands of transactions) and index review.

### Phase 2 — Reproducible build and CI
- Pin frontend dependencies, generate `package-lock.json`; backend dependency reproducibility.
- GitHub Actions: backend tests, frontend typecheck/build, migration validation; fail on any break.

### Phase 3 — Security and production hardening
- Reject default JWT secret in production; secure secret storage.
- Separate webhook credentials from integration config.
- Review token expiry, CORS, constraints/indexes, sync transaction boundaries; deterministic failed `SyncRun` persistence.
- Structured logs; rate limiting.
- (new) User lifecycle: invites, password reset/change, deactivation, refresh token, logout.

### Phase 4 — First real POS connector
- Provider choice by API/access feasibility.
- Auth, connection test, location/product discovery, historical import, incremental sync, pagination, retry/backoff, webhooks where supported, tax/currency semantics, provider integration tests.
- (new) Handle cancellations, returns and voids, including reversing stock consumption.

### Phase 5 — Integration operations
- Background jobs, scheduled sync, job states, retries, failure reasons, manual retry, webhook replay, dead-letter, integration health, sync metrics.
- (new) Alerts for failed sync and new unmatched products.

### Phase 6 — Complete the user product
- Connection wizard, mapping workspace, unmatched resolution, recipes and ingredients, cost management, inventory adjustments, movement history, sales detail, filters, charts, error/sync status screens, role-based UI.
- (new) Goods receipts and suppliers, physical counts with variances, inter-location transfers.
- (new) Automatic costs from receipts/invoices; food cost % and margin reports.
- (new) Sub-recipes, modifiers, combos.
- (new) Pagination, filters, CSV/Excel export; bulk onboarding import.
- (new) Audit log of user actions; low-stock alerts.
- (new) i18n (RO/EN).

### Phase 7 — Staging and pilot
- Isolated staging, production-like PostgreSQL, real secrets, monitoring, backups.
- Pilot POS, historical import, daily sync; validate stock/recipe/cost outputs; measure failure/recovery; runbooks.

### Phase 8 — Production SaaS
- Production infra, HTTPS, managed PostgreSQL, tested backup/restore, monitoring, centralised logs, CI/CD with migration step and rollback.
- Tenant onboarding, billing, usage metering, plan limits, admin/support tools.
- (new) Romanian fiscal and localisation requirements; privacy/GDPR/retention.

### Phase 9 — Multi-POS expansion
- Second connector only after the first is operationally stable.
- Connector SDK/interface documentation (new), connector health and versioning, provider onboarding process.

## Immediate next work package

1. Backend test infrastructure.
2. Tenant-isolation tests.
3. Auth/role tests.
4. Sales import and duplicate tests.
5. Mapping and UOM tests.
6. Recipe/inventory/costing tests.
7. Webhook tests.
8. Dashboard tests.
9. Pin frontend dependencies, lockfile.
10. CI workflow.
11. Harden sync transaction handling.
12. Enforce production JWT secret rules.
13. Select and build the first real POS connector.

## Development rules

- Every business feature has an API test.
- Every company-scoped endpoint enforces tenant isolation.
- External POS operations are idempotent where possible.
- No invented conversions; mappings/UOM must be explicit.
- Provider-specific behaviour lives in connectors.
- Core logic is reusable by API, webhooks and background jobs.
- Schema changes go through Alembic.
- Production config must not rely on development defaults.
- No second connector before the first has a stable lifecycle.
- Prefer measurable end-to-end milestones over isolated features.
