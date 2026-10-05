# Operations runbook

Status of this document: written alongside the code. The container images, the production compose file and
the backup scripts were validated statically (compose config, shell syntax, Dockerfile health check
command) but **not run end to end on a real server**. Do a full staging rehearsal (below) before the
first customer.

## Environments
| | Compose file | Notes |
|---|---|---|
| Local development | `docker-compose.yml` | database port exposed, `APP_ENV=development` |
| Staging / production | `deploy/docker-compose.prod.yml` | TLS via Caddy, DB not exposed, secrets required |

Staging is the same stack with its own `deploy/.env` (own `DOMAIN`, database, secrets). Use a copy of
anonymised or synthetic data there, never a raw production dump with personal data.

## First deployment
1. DNS `A` record for `DOMAIN` points at the server; ports 80/443 open.
2. `cp deploy/.env.prod.example deploy/.env`, fill every value (`openssl rand -hex 32` for secrets).
3. `docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env up -d --build`
4. `curl https://$DOMAIN/health` → `{"status":"ok","database":"ok"}`.
5. Open the site and create the first company (owner). Set `DEFAULT_PLAN`/plans as needed.
6. Install the backup cron (below) and run one backup + one restore test on staging.

## Release procedure
1. CI green on the commit (backend tests, `alembic check`, frontend build).
2. Take a backup (`deploy/backup.sh`).
3. `git pull && docker compose ... up -d --build`. The `migrate` service runs `alembic upgrade head`
   before `backend` and `worker` start; if it fails, the new version does not start and the old
   containers keep running.
4. Verify `/health`, sign in, check the Alerts tab.

### Rollback
- Code only (no schema change in the release): check out the previous tag and `up -d --build`.
- Schema changed: migrations 0013 and later add columns/tables/constraints. Prefer rolling **forward**
  with a fix. If you must go back: restore the pre-release backup (`deploy/restore.sh`) and deploy the
  previous code. `alembic downgrade` exists for each migration, but `0015` cannot restore webhook tokens
  (they were hashed); integrations need new tokens afterwards.
- Migration `0013` (unique sale ids) fails if duplicate `(integration_id, external_id)` sales already
  exist. De-duplicate first.

## Backups and restore
- `deploy/backup.sh` writes a custom-format `pg_dump`, verifies it can be listed, and deletes dumps
  older than `KEEP_DAYS` (default 14). Cron example is in the script header. Copy dumps off the server
  (object storage / another host); a backup on the same disk is not a backup.
- `deploy/restore.sh <dump>` replaces the database, then runs migrations. **Rehearse it on staging at
  least monthly** and record the time it took.
- Managed PostgreSQL (recommended for production) with point-in-time recovery replaces these scripts;
  keep the same rehearsal discipline.

## Monitoring
- `GET /health` – liveness + database. Use for uptime checks (e.g. every minute).
- `GET /metrics` – Prometheus text, per-process counters (requests by route/status, latency). Not routed
  by Caddy; scrape from inside the network, set `METRICS_TOKEN`.
- Structured JSON request logs on stdout (`event=http_request`, `request_id`, `status`, `duration_ms`);
  worker logs `worker_started/worker_synced/worker_tick_failed`. Ship container logs to a central store.
- Suggested alerts: `/health` failing 3×; 5xx rate; no `worker_synced` for scheduled integrations; the
  in-app Alerts tab (paused sync, failed webhooks, negative stock, missing costs).
- Not built yet: alert delivery (email/push), tracing, DB metrics. Wire an external monitor to `/health`.

## Common incidents
| Symptom | Cause / action |
|---|---|
| Alert `sync_paused` | 5 consecutive sync failures. Read the reason in Integrations → select the integration → Sync history; fix credentials/connectivity; set the schedule again (or press "Sync now") to resume. |
| Alert `webhook_failed` | An event could not be processed (often a missing UOM conversion or a recipe ingredient without conversion). Fix data, then Integrations → Failed webhook events → Replay. |
| `/api/sales/import*` returns 400 "No UOM conversion" | Add the product's conversion (Overview → UOM conversions) and re-upload; imports are all-or-nothing and idempotent. |
| Negative stock alert | Sales consumed more than recorded. Receive goods or do a stock count to correct it. |
| 402 on creating a location/user/integration | Plan limit; change plan via `PATCH /api/admin/companies/{id}`. |
| Users locked out | Rate limit (10 failed logins/5 min per e-mail or IP, resets on restart or success); a manager can reset a password (`POST /api/users/{id}/reset-password`). |
| Worker not syncing | `docker compose ... logs worker`; stale `running` runs are failed after 15 minutes automatically. |

## Secrets and rotation
- `JWT_SECRET_KEY`: rotating it signs everyone out (acceptable). Change it in `deploy/.env`, `up -d`.
- Webhook tokens: rotate per integration (`POST .../webhook-token`); the old token stops working at once.
- `ADMIN_API_KEY`/`METRICS_TOKEN`: rotate in `.env`. Leave `ADMIN_API_KEY` empty to disable admin endpoints.
- Database password: change in Postgres and `.env` together, then restart.
- `credentials_ref` on integrations is a pointer to a secret store; no connector reads real vendor
  credentials yet (the first real connector must define this: environment variable names or a vault path).

## Invoice intake
- AI reading needs outbound HTTPS to `api.anthropic.com` and `ANTHROPIC_API_KEY`. A page or photo costs a few cents
  at the default model (estimate: a few thousand input tokens plus roughly a thousand output tokens per invoice);
  measure on your own invoices and pick a cheaper `INVOICE_AI_MODEL` if accuracy allows. Without the key, PDF/photo
  uploads fail with an explanation and XML keeps working.
- Mailbox: create one mailbox (e.g. `invoices@yourdomain`) that accepts plus-addresses, enable IMAP, and set
  `IMAP_*` and `INVOICE_INBOX_ADDRESS` on the **worker**. Messages are marked seen after handling; a message that
  crashed the processor stays unseen and is retried. Check `docker compose logs worker` for `invoice_mail_polled`.
- A failed or unreadable file is kept (status *failed*) and raises an *info* alert so nothing is silently lost.
- Always spot-check the first invoices of each supplier before turning on automatic posting.

## Known limitations
- Rate limiting and metrics are in-process: with several backend replicas the login limit and counters
  are per replica. Use a shared store (Redis) before scaling out horizontally.
- Single database, no read replicas; reports run live queries (margin report issues several queries per
  product/location, fine for thousands of sales, not for years of data without aggregation).
- No e-mail sending: no password-reset e-mails or alert e-mails; managers reset passwords.
