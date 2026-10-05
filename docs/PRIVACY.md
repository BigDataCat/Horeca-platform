# Privacy and GDPR notes

This is an engineering description of what the platform stores and the tools it offers. It is **not legal
advice**: before onboarding customers you need a lawyer-reviewed privacy policy, terms of service and a
data processing agreement (DPA), and a record of processing activities.

## Roles
The customer (restaurant company) is the controller of its business data and its staff accounts; the
platform operator is the processor. Platform staff accessing a tenant's data for support must do so on
documented instructions from the customer.

## Personal data stored
| Data | Where | Purpose |
|---|---|---|
| Staff name, e-mail, role, password hash (Argon2) | `users` | Authentication and authorisation |
| Actions by user id (create/update/delete of business records) | `audit_logs` | Accountability. Secrets and password data are never logged. |
| Request metadata (path, status, timing, request id) | application logs | Operations and security; contain no request bodies |
| Sales | `sales`, `sale_lines` | Business reporting. The platform does **not** store customer names, card data or loyalty ids; if a POS sends such fields they are ignored by the canonical model. Raw vendor payloads are stored in `sales.source_payload` as the canonical JSON only. |

No payment card data is processed. No third-party analytics or tracking scripts are included in the frontend.

## Data subject rights (tooling)
- **Access / portability:** `GET /api/auth/me/export` returns the caller's profile and recorded actions
  (JSON). Business data can be exported as CSV (sales, stock movements, margins).
- **Erasure of a staff member:** `POST /api/users/{id}/anonymize` (owner) replaces name and e-mail, locks the
  account and invalidates tokens. Records they created are kept and point to the anonymous user.
- **Erasure of a whole customer:** `DELETE /api/admin/companies/{id}?confirm_name=...` (operator, admin key)
  deletes the company and all its data irreversibly. Backups still contain the data until they expire
  (14 days with the default rotation): state this in the policy.
- **Rectification:** users and managers can edit names/roles; e-mail changes currently need a manager/owner
  to recreate the account (no e-mail change flow yet).

## Retention (decisions to take; defaults today)
- Business data (sales, stock, costs): kept until the customer deletes the company. Tax law may require
  customers to keep accounting records for years; do not auto-delete without their instruction.
- Audit log: kept indefinitely unless `AUDIT_RETENTION_DAYS` is set; the worker then purges older entries daily.
  Decide a period (e.g. 2–5 years). Finished webhook events are purged after `WEBHOOK_EVENT_RETENTION_DAYS`
  (default 90); failed ones are kept until replayed. Used/expired reset tokens are purged daily.
- Application logs: set the log store retention (suggest 30–90 days).
- Backups: 14 days by default (`KEEP_DAYS`).

## Security measures in place
HTTPS at the edge (Caddy), Argon2 password hashing, JWT with server-side invalidation (password change,
logout, role change, deactivation), login rate limiting, per-tenant data isolation enforced and tested on
every company-scoped endpoint, webhook tokens stored as hashes, secrets excluded from the audit log,
role-based access (owner/manager/employee), security headers and CSP on the frontend.

## Open items before launch
Privacy policy and DPA text; cookie/consent review (the app uses `localStorage` for the session token only);
the chosen retention periods; breach notification procedure; sub-processor list
(hosting, backups, e-mail provider once added); data location (choose an EU region).
