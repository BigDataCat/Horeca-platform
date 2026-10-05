"""Generic REST/JSON sales connector, configured per integration (no code needed for many POS APIs).

``integration.config`` example::

    {
      "sales_path": "/v1/transactions",
      "cursor_param": "updated_after",
      "page_size_param": "limit", "page_size": 100, "page_param": "page",
      "items_path": "data.items",
      "next_cursor_path": "meta.next_cursor",
      "auth": {"type": "bearer"},
      "amount_divisor": 100,
      "time_format": "iso",
      "default_currency": "RON",
      "mapping": {
        "external_id": "id", "occurred_at": "created_at", "currency": "currency",
        "net_value": "net", "tax_value": "tax", "gross_value": "gross",
        "lines_path": "items",
        "line": {"external_product_id": "sku", "product_name": "name", "quantity": "qty",
                 "uom": "unit", "unit_price": "price", "net_value": "net", "tax_value": "tax"}
      }
    }

``base_url`` is on the integration; the secret is read from the environment variable named in
``credentials_ref`` as ``env:VARIABLE`` and never stored in the database. Records that cannot be
mapped fail the sync loudly (nothing is guessed). When paginating, the API must return items
oldest first so the cursor (newest ``occurred_at`` seen) never skips data.
"""

import base64
import ipaddress
import os
import socket
import time
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse

import httpx

from app.core.config import settings
from app.models.pos_integration import POSIntegration
from app.schemas.sales import CanonicalSale, CanonicalSaleLine
from app.services.pos_connectors import ConnectorResult, SalesPullResult

MAX_PAGES = 50
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
RETRY_STATUSES = {429, 500, 502, 503, 504}
MAX_ATTEMPTS = 4

# Hooks so tests can avoid real DNS/network.
transport: httpx.BaseTransport | None = None
sleep = time.sleep
resolve_host = lambda host: [info[4][0] for info in socket.getaddrinfo(host, None)]  # noqa: E731


def get_path(data, path: str | None):
    """Read ``a.b.0.c`` from nested dicts/lists. Returns None if any step is missing."""
    if not path:
        return None
    current = data
    for part in path.split("."):
        if isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                return None
        elif isinstance(current, dict):
            if part not in current:
                return None
            current = current[part]
        else:
            return None
    return current


def check_url_is_safe(url: str) -> None:
    """Refuse non-HTTPS URLs and internal addresses (SSRF protection) unless explicitly allowed."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("base_url must be an http(s) URL")
    if settings.http_connector_allow_private:
        return
    if parsed.scheme != "https":
        raise ValueError("base_url must use https")
    try:
        addresses = resolve_host(parsed.hostname)
    except OSError:
        raise ValueError(f"Cannot resolve host {parsed.hostname}")
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            raise ValueError("base_url points to a private or internal address, which is not allowed")


def _auth_headers(integration: POSIntegration, config: dict) -> dict[str, str]:
    auth = config.get("auth") or {"type": "none"}
    kind = auth.get("type", "none")
    if kind == "none":
        return {}
    reference = integration.credentials_ref or ""
    if not reference.startswith("env:"):
        raise ValueError("credentials_ref must be 'env:VARIABLE_NAME' for authenticated APIs")
    secret = os.environ.get(reference[4:])
    if not secret:
        raise ValueError(f"Environment variable {reference[4:]} is not set on the server")
    if kind == "bearer":
        return {"Authorization": f"Bearer {secret}"}
    if kind == "header":
        return {auth.get("header_name", "X-Api-Key"): secret}
    if kind == "basic":
        return {"Authorization": "Basic " + base64.b64encode(secret.encode()).decode()}  # secret = user:password
    raise ValueError(f"Unknown auth type '{kind}'")


def _request(client: httpx.Client, url: str, params: dict, headers: dict) -> dict:
    last_error = "request failed"
    for attempt in range(MAX_ATTEMPTS):
        try:
            response = client.get(url, params=params, headers=headers)
        except httpx.HTTPError as exc:
            last_error = f"network error: {exc.__class__.__name__}"
        else:
            if response.status_code in RETRY_STATUSES:
                last_error = f"HTTP {response.status_code}"
                retry_after = response.headers.get("Retry-After")
                if attempt + 1 < MAX_ATTEMPTS:
                    sleep(min(float(retry_after), 30) if retry_after and retry_after.isdigit() else 2**attempt)
                continue
            if response.status_code in {401, 403}:
                raise ValueError(f"The POS API rejected the credentials (HTTP {response.status_code})")
            if response.status_code >= 400:
                raise ValueError(f"The POS API returned HTTP {response.status_code}")
            if len(response.content) > MAX_RESPONSE_BYTES:
                raise ValueError("The POS API response is too large")
            try:
                return response.json()
            except ValueError:
                raise ValueError("The POS API did not return JSON")
        if attempt + 1 < MAX_ATTEMPTS:
            sleep(2**attempt)
    raise RuntimeError(f"POS API unavailable after {MAX_ATTEMPTS} attempts ({last_error})")


def _decimal(value, divisor: Decimal, field: str) -> Decimal:
    if value is None or value == "":
        raise ValueError(f"missing {field}")
    try:
        return Decimal(str(value)) / divisor
    except InvalidOperation:
        raise ValueError(f"invalid number for {field}: {value!r}")


def _timestamp(value, time_format: str) -> datetime:
    if value is None or value == "":
        raise ValueError("missing occurred_at")
    if time_format == "epoch_s":
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    if time_format == "epoch_ms":
        return datetime.fromtimestamp(float(value) / 1000, tz=timezone.utc)
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def map_record(record: dict, config: dict) -> CanonicalSale:
    mapping = config.get("mapping") or {}
    divisor = Decimal(str(config.get("amount_divisor", 1)))
    time_format = config.get("time_format", "iso")
    line_map = mapping.get("line") or {}

    def field(source: dict, name: str, table: dict):
        return get_path(source, table.get(name))

    external_id = field(record, "external_id", mapping)
    if external_id in (None, ""):
        raise ValueError("missing external_id")
    raw_lines = get_path(record, mapping.get("lines_path")) or []
    if not isinstance(raw_lines, list) or not raw_lines:
        raise ValueError("sale has no lines")

    lines = []
    for raw in raw_lines:
        net = _decimal(field(raw, "net_value", line_map), divisor, "line net_value")
        tax_raw = field(raw, "tax_value", line_map)
        lines.append(
            CanonicalSaleLine(
                external_product_id=str(v) if (v := field(raw, "external_product_id", line_map)) is not None else None,
                product_name=str(field(raw, "product_name", line_map) or "Unknown"),
                quantity=_decimal(field(raw, "quantity", line_map), Decimal(1), "line quantity"),
                uom=str(field(raw, "uom", line_map) or config.get("default_uom", "EA")),
                unit_price=_decimal(field(raw, "unit_price", line_map), divisor, "line unit_price"),
                net_value=net,
                tax_value=_decimal(tax_raw, divisor, "line tax_value") if tax_raw not in (None, "") else Decimal(0),
            )
        )
    net_total = sum((l.net_value for l in lines), Decimal(0))
    tax_total = sum((l.tax_value for l in lines), Decimal(0))
    net_raw, tax_raw = field(record, "net_value", mapping), field(record, "tax_value", mapping)
    net_value = _decimal(net_raw, divisor, "net_value") if net_raw not in (None, "") else net_total
    tax_value = _decimal(tax_raw, divisor, "tax_value") if tax_raw not in (None, "") else tax_total
    gross_raw = field(record, "gross_value", mapping)
    return CanonicalSale(
        external_id=str(external_id),
        occurred_at=_timestamp(field(record, "occurred_at", mapping), time_format),
        currency=str(field(record, "currency", mapping) or config.get("default_currency") or "RON").upper(),
        net_value=net_value,
        tax_value=tax_value,
        gross_value=_decimal(gross_raw, divisor, "gross_value") if gross_raw not in (None, "") else net_value + tax_value,
        lines=lines,
    )


def validate_config(integration: POSIntegration) -> dict:
    config = integration.config or {}
    if not integration.base_url:
        raise ValueError("base_url is required for the http provider")
    for key in ("sales_path", "items_path"):
        if not config.get(key):
            raise ValueError(f"config.{key} is required")
    mapping = config.get("mapping") or {}
    for key in ("external_id", "occurred_at", "lines_path"):
        if not mapping.get(key):
            raise ValueError(f"config.mapping.{key} is required")
    line = mapping.get("line") or {}
    for key in ("product_name", "quantity", "unit_price", "net_value"):
        if not line.get(key):
            raise ValueError(f"config.mapping.line.{key} is required")
    check_url_is_safe(integration.base_url)
    return config


class HTTPJSONConnector:
    def _client(self) -> httpx.Client:
        return httpx.Client(timeout=settings.http_connector_timeout_seconds, transport=transport, follow_redirects=False)

    def test_connection(self, integration: POSIntegration) -> ConnectorResult:
        config = validate_config(integration)
        headers = _auth_headers(integration, config)
        params = {config["page_size_param"]: 1} if config.get("page_size_param") else {}
        with self._client() as client:
            payload = _request(client, integration.base_url.rstrip("/") + config["sales_path"], params, headers)
        items = get_path(payload, config["items_path"])
        if not isinstance(items, list):
            return ConnectorResult(False, f"The response has no list at '{config['items_path']}'.")
        if items:
            map_record(items[0], config)  # proves the mapping works on real data
        return ConnectorResult(True, f"Connected. Sample mapped successfully ({len(items)} record(s) in the test page).")

    def pull_sales(self, integration: POSIntegration, cursor: str | None = None) -> SalesPullResult:
        config = validate_config(integration)
        headers = _auth_headers(integration, config)
        url = integration.base_url.rstrip("/") + config["sales_path"]
        page_size = int(config.get("page_size", 100))
        sales: list[CanonicalSale] = []
        next_cursor = cursor
        page = 1
        token = None
        position = 0

        with self._client() as client:
            for _ in range(MAX_PAGES):
                params: dict = {}
                if cursor and config.get("cursor_param"):
                    params[config["cursor_param"]] = cursor
                if config.get("page_size_param"):
                    params[config["page_size_param"]] = page_size
                if config.get("page_param"):
                    params[config["page_param"]] = page
                if token and config.get("page_token_param"):
                    params[config["page_token_param"]] = token
                payload = _request(client, url, params, headers)
                items = get_path(payload, config["items_path"])
                if not isinstance(items, list):
                    raise ValueError(f"The response has no list at '{config['items_path']}'")
                for record in items:
                    position += 1
                    try:
                        sales.append(map_record(record, config))
                    except (ValueError, TypeError, KeyError) as exc:
                        raise ValueError(f"Record {position} could not be mapped: {exc}")
                token = get_path(payload, config.get("next_page_token_path"))
                if config.get("page_token_param") and token:
                    continue
                if config.get("page_param") and len(items) >= page_size and items:
                    page += 1
                    continue
                break

        server_cursor = None
        if config.get("next_cursor_path"):
            server_cursor = get_path(payload, config["next_cursor_path"])
        if server_cursor:
            next_cursor = str(server_cursor)
        elif sales:
            newest = max(s.occurred_at for s in sales)
            next_cursor = newest.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        return SalesPullResult(sales=sales, next_cursor=next_cursor)
