# Roadmap and status

Baseline: 3 October 2026 (Soft POS blueprint). Updated after the engineering push that followed it.
Legend: ✅ done and tested · 🟡 partly done · ⛔ not done · 🔒 blocked on something outside the code.

## Summary
The platform is feature-complete for a **pilot using CSV or demo data**. What stands between it and a
real production launch is mostly outside the codebase: a pilot POS account (for the first vendor
connector), a rehearsal of the deployment on real infrastructure, legal documents, and billing.

## Status by blueprint area

| Area | Status | Notes |
|---|---|---|
| Automated tests | ✅ | ~200 backend tests on PostgreSQL (auth, roles, tenant isolation, ingestion, UOM, recipes, inventory, costing, webhooks, sync, CSV, audit, plans, privacy, schema drift) + browser smoke test (`e2e/`). |
| Reproducible build & CI | ✅ | Pinned frontend deps + lockfile, GitHub Actions (backend tests, frontend build). The workflow was added but has not yet run on GitHub. |
| Security hardening | 🟡 | ✅ production secret check, hashed webhook tokens, login rate limit, token invalidation, plan/role gaps fixed, audit log, request ids, security headers. ⛔ shared rate-limit store, secret-manager integration (needs the first real connector), dependency/vulnerability scanning in CI. |
| First real POS connector | 🔒 | Needs a pilot POS and sandbox credentials. `docs/CONNECTORS.md` defines the contract and checklist; CSV import covers any POS that exports files. |
| Background sync | ✅ | Worker, schedules, backoff, auto-pause, stale-run cleanup, SKIP LOCKED claiming. |
| Webhook resilience | ✅ | Persisted payloads, failed-event list, replay, redelivery retry, hashed tokens, out-of-order cancel events. |
| Cancellations / returns | ✅ | Full-sale cancel/refund with exact stock reversal (API + webhook events). Partial refunds ⛔. |
| User lifecycle | 🟡 | ✅ change password, admin reset, logout-everywhere, immediate role/deactivation effect. ⛔ e-mail based reset/invites (no e-mail sending yet), refresh tokens. |
| Inventory operations | ✅ | Suppliers, goods receipts (stock + last-purchase cost), counts, transfers, movements, adjustments with explicit UOM. ⛔ supplier invoices/payments, lot/expiry tracking. |
| Costing & margins | ✅ | Effective-dated costs, location override, recipe cost, margin / food-cost % report, CSV export. |
| Recipes | 🟡 | ✅ waste, location override. ⛔ sub-recipes / semi-finished production, modifiers, combo menus. |
| Operational UI | ✅ | Sales, inventory, recipes & costs, reports, integrations, alerts, settings (subscription, audit log). Legacy overview page kept. ⛔ i18n (English only), charts, mobile-first layouts. |
| Alerts | 🟡 | ✅ computed alerts in the UI. ⛔ delivery (e-mail/push). |
| Observability | 🟡 | ✅ health, JSON logs, `/metrics`. ⛔ tracing, dashboards, alert rules (see `docs/OPERATIONS.md`). |
| Deployment | 🟡 | ✅ prod compose (TLS), migrate-before-start, health checks, non-root image, backup/restore scripts, runbook. ⛔ never executed on a real server (no Docker daemon in the build environment): rehearse on staging. |
| SaaS | 🟡 | ✅ plans with enforced limits, subscription view, admin support API, company deactivation/deletion. ⛔ payment provider, invoices, self-service plan change, usage-based billing. |
| Compliance | 🟡 | ✅ tooling for access/erasure, privacy notes (`docs/PRIVACY.md`). ⛔ lawyer-reviewed policy/DPA, audit-log retention job. |
| Romanian fiscal | ⛔ | VAT is carried from the POS as given. e-Factura, fiscal-register integration and per-location currency/time zone are not implemented. |
| Multi-POS | ⛔ | By design only after the first connector is stable. |

## What is needed from people (cannot be done in code)
1. **Pick the pilot POS and get sandbox/API access** → implement connector (see `docs/CONNECTORS.md`).
2. **Rehearse a staging deployment**: first deploy, a release with a migration, a backup and a restore.
3. **Legal**: privacy policy, terms, DPA, sub-processor list; decide retention periods.
4. **Choose a billing approach** (payment provider or manual invoicing) before charging customers.
5. **Decide the fiscal scope** for Romania (e-Factura, fiscal registers) with an accountant.

## Suggested next engineering work (in order)
1. Run CI on GitHub and fix anything environment-specific; add dependency/vulnerability scanning.
2. First vendor connector once access exists (include status-change reporting for polling connectors).
3. E-mail sending (password reset, invites, alert delivery) with a provider chosen by the operator.
4. Sub-recipes / semi-finished products and modifiers, driven by the pilot's actual menu.
5. Shared rate-limit/metrics store before running multiple backend replicas.
6. Payment provider integration; i18n (RO/EN); audit-log purge job.

## Development rules (unchanged)
- Every business feature has an API test; every company-scoped endpoint enforces tenant isolation.
- External POS operations are idempotent; no invented conversions (UOM and cost gaps stay visible).
- Provider-specific behaviour lives in connectors; core logic is reusable by API, webhooks and jobs.
- Schema changes go through Alembic (`alembic check` runs in the test suite).
- Production configuration never relies on development defaults.
- No second connector before the first has a stable operational lifecycle.
