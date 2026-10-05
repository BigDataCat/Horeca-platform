# Writing a POS connector

A connector is the only place that knows a POS vendor's API. Everything after it (mapping, UOM,
inventory, recipes, costs, dashboards) works on the canonical model, so adding a vendor never changes
core business code.

## Contract (`backend/app/services/pos_connectors.py`)

```python
class POSConnector(Protocol):
    def test_connection(self, integration: POSIntegration) -> ConnectorResult: ...
    def pull_sales(self, integration: POSIntegration, cursor: str | None = None) -> SalesPullResult: ...
```

Register it and add a catalog entry:

```python
register_connector("myvendor", MyVendorConnector())
PROVIDER_CATALOG += (POSProviderInfo("myvendor", "My Vendor", ("api", "webhook"), ("sales_pull", ...)),)
```

### `pull_sales`
- Return `SalesPullResult(sales=[CanonicalSale, ...], next_cursor="...")`.
- `cursor` is whatever you returned last time (`None` on the first sync). Make it opaque and monotonic
  (a timestamp or the vendor's page token). It is stored only after the whole batch was imported, so a
  failed run is retried from the same cursor.
- Handle pagination and rate limits inside the connector (retry with backoff on 429/5xx). Return at most
  a few thousand sales per call; the worker calls again on the next tick.
- Do not touch the database and do not mutate `integration`. Read credentials from where
  `integration.credentials_ref` points (environment/secret manager), never from `config`.
- Errors: raise `ValueError` for configuration problems the operator must fix (bad credentials, missing
  account id) → surfaced as HTTP 400 / run `error`. Raise any other exception for transient/vendor
  failures → HTTP 502 and automatic retry with exponential backoff; five failures in a row pause the schedule.

### Canonical sale (`app/schemas/sales.py`)
- `external_id`: the vendor's stable transaction id. It is the idempotency key
  (unique per integration), so re-sending the same sale is always safe.
- `occurred_at`: timezone-aware. Convert vendor local time to UTC yourself.
- Amounts are decimals; `net_value + tax_value == gross_value` for the sale and line values should add up.
  Keep the vendor's currency code; do not convert currencies.
- Each line: `external_product_id` (vendor SKU/id), `product_name`, `quantity`, `uom`, `unit_price`,
  `net_value`, `tax_value`. Send the vendor's real unit of measure. Never "fix" units yourself: the platform
  converts only through explicit per-product conversions and keeps the original unit when none exists.
- Modifiers/combos: flatten to ordinary lines until the platform supports them.

### Webhooks
Vendors that push events post `{event_id, event_type, sale}` to
`POST /api/integrations/pos/{id}/webhook` with header `X-Webhook-Token` (generate it with
`POST /api/integrations/pos/{id}/webhook-token`; only a hash is stored). Event types:
`sale.created`, `sale.cancelled`, `sale.refunded`. Cancel/refund events may arrive before the create event;
that is handled. Failed events are stored and can be replayed. If the vendor cannot send custom headers,
put a small adapter in front that does.

### Cancellations and returns when polling
Polling connectors should also report voids: either return the sale again with its new state through
`apply_sale_status_event` (see `services/sales_ingestion.py`), or call the public status endpoint. The
current `SalesPullResult` carries created sales only; extending it with a `status_changes` list is the
first thing to do when the first real connector needs it.

## Checklist for a new vendor
1. Sandbox account and API credentials; confirm the API exposes transactions with stable ids, line items
   with SKUs and units, taxes, and cancellations.
2. Implement the connector against recorded vendor responses (store them as fixtures) and unit-test the
   mapping to `CanonicalSale`, including pagination, a 429, a 500, and an empty page.
3. Test through the API with the demo flow: sync twice (second run imports nothing), cancel a sale (stock
   returns), unmapped product shows up in "unmatched", missing UOM conversion fails loudly.
4. Run against realistic historical data on staging; compare totals with the vendor's own report.
5. Document vendor quirks here (rate limits, time zones, tax model).
6. Only after it ran stably for a while, start the next vendor.

## Generic REST/JSON connector (`http`)
Many POS APIs can be connected without code: create an integration with provider **Generic REST/JSON API**,
set `base_url`, put the secret in a server environment variable and reference it as
`credentials_ref = "env:MYPOS_TOKEN"` (Docker: add `MYPOS_TOKEN=...` to `deploy/pos-secrets.env`), and describe
the endpoint in `config` (see the docstring of `backend/app/services/http_connector.py` and the
example the UI inserts). It supports bearer/header/basic auth, cursor query parameter, page-number or
page-token pagination, a server-provided next cursor, ISO/epoch timestamps, amounts in minor units
(`amount_divisor`), retries with backoff on 429/5xx (honours `Retry-After`), and refuses internal
addresses and plain HTTP (SSRF protection). A record that cannot be mapped fails the whole sync
loudly instead of guessing, and **Test** maps a real sample record to prove the configuration. Limits: the
API must return items oldest-first when paginating, only GET JSON endpoints, no cancellation reporting yet.
Use it as the first real integration when a vendor's REST API is simple enough; write a dedicated
connector when it is not (OAuth flows, signing, odd pagination).

## What exists today
- `demo` and `mock`: deterministic connectors for development and tests.
- `csv`: any POS that can export sales to CSV (`POST /api/sales/import-csv`). This is the supported path
  until a vendor connector exists.
- `http`: generic REST/JSON pull connector, configurable per integration (tested against mocked APIs only).
- No vendor-specific connector yet: validating `http` or writing a dedicated one needs a pilot account.
