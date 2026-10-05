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
| First real POS connector | 🟡 | ✅ configurable generic REST/JSON connector (`http`, SSRF-safe, retries, pagination, mapping test) and CSV import. 🔒 Validating against a real vendor API needs a pilot account/sandbox credentials; `docs/CONNECTORS.md` has the contract and checklist. |
| Background sync | ✅ | Worker, schedules, backoff, auto-pause, stale-run cleanup, SKIP LOCKED claiming. |
| Webhook resilience | ✅ | Persisted payloads, failed-event list, replay, redelivery retry, hashed tokens, out-of-order cancel events. |
| Cancellations / returns | ✅ | Full cancel/refund and line-level partial refunds with proportional, exact stock and revenue reversal (API, UI, webhook events for full cancel/refund). |
| User lifecycle | ✅ | Change password, e-mail reset, e-mail invitations, admin reset, logout-everywhere, immediate role/deactivation effect. ⛔ refresh tokens, e-mail address change flow. |
| Inventory operations | ✅ | Suppliers, goods receipts (stock + last-purchase cost), counts, transfers, movements, adjustments with explicit UOM. ⛔ supplier payments, lot/expiry tracking. |
| Invoice / NIR intake | ✅ | e-Factura XML/ZIP read exactly; PDF/photos read **locally** by default (text layer or Tesseract OCR + arithmetic-checked rules; optional local LLM via Ollama or the Claude API), always reviewed; e-mail inbox per company, learned product names, optional auto-post for exact XML, reconciliation warnings. Tested with generated invoices (including rasterised scans); **not yet verified against real invoices from your suppliers**, and the Ollama and Claude paths only against mocks. ⛔ credit notes/returns, reading ANAF's SPV inbox directly (needs ANAF OAuth credentials), supplier-payment tracking. |
| Costing & margins | ✅ | Effective-dated costs, location override, recipe cost, margin / food-cost % report, CSV export. |
| Recipes | ✅ | Waste, location override, semi-finished production orders (sub-recipes with cost roll-up, cycle protection). Modifiers and combos are handled by sending them as ordinary lines (each with its own mapping/recipe). |
| Operational UI | ✅ | Sales (incl. partial refunds), inventory (incl. production), recipes & costs, reports with daily-sales chart, integrations, alerts, settings (subscription, team invites, time zones, audit log), forgot/reset password. Romanian/English switch (`src/locales/ro.ts`; server error messages, browser prompt dialogs and a few legacy-page strings stay English). Legacy overview page kept. Checked at phone width (390 px): no horizontal overflow on any tab. ⛔ more charts. |
| Alerts | ✅ | Computed alerts in the UI plus a daily e-mail digest to owners (opt-out per company). ⛔ push notifications, per-user preferences. |
| Observability | 🟡 | ✅ health, JSON logs, `/metrics`. ⛔ tracing, dashboards, alert rules (see `docs/OPERATIONS.md`). |
| Deployment | 🟡 | ✅ prod compose (TLS), migrate-before-start, health checks, non-root image, backup/restore scripts, runbook. ⛔ never executed on a real server (no Docker daemon in the build environment): rehearse on staging. |
| SaaS | 🟡 | ✅ plans with enforced limits, trial/subscription expiry (read-only after expiry, `TRIAL_DAYS`), subscription view and banner, admin support API (plan, expiry, deactivate, delete). ⛔ payment provider, invoices, self-service plan change, usage-based billing (needs business decisions: prices, VAT, provider). |
| Compliance | 🟡 | ✅ tooling for access/erasure, privacy notes (`docs/PRIVACY.md`). ⛔ lawyer-reviewed policy/DPA, audit-log retention job. |
| Romanian fiscal | 🟡 | ✅ per-location time zone (default Europe/Bucharest) with local-day reporting. VAT is carried from the POS as given. ⛔ e-Factura, fiscal-register integration, multi-currency per location. |
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
3. Choose and configure an SMTP provider (the code is ready: `EMAIL_BACKEND=smtp`).
4. Shared rate-limit/metrics store before running multiple backend replicas.
5. Payment provider integration.
6. Polish driven by the pilot: more charts, dedicated screens for audit/retention settings.

## Development rules (unchanged)
- Every business feature has an API test; every company-scoped endpoint enforces tenant isolation.
- External POS operations are idempotent; no invented conversions (UOM and cost gaps stay visible).
- Provider-specific behaviour lives in connectors; core logic is reusable by API, webhooks and jobs.
- Schema changes go through Alembic (`alembic check` runs in the test suite).
- Production configuration never relies on development defaults.
- No second connector before the first has a stable operational lifecycle.
