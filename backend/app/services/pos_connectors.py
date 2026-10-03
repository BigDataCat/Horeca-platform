from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Protocol

from app.models.pos_integration import POSIntegration
from app.schemas.sales import CanonicalSale, CanonicalSaleLine


@dataclass
class ConnectorResult:
    success: bool
    message: str


class POSConnector(Protocol):
    def test_connection(self, integration: POSIntegration) -> ConnectorResult:
        ...

    def pull_sales(self, integration: POSIntegration) -> list[CanonicalSale]:
        ...


class MockPOSConnector:
    def test_connection(self, integration: POSIntegration) -> ConnectorResult:
        return ConnectorResult(
            success=True,
            message=f"Mock connector for {integration.provider} is reachable.",
        )

    def pull_sales(self, integration: POSIntegration) -> list[CanonicalSale]:
        return []


class DemoPOSConnector:
    """
    Deterministic local POS connector used to exercise the complete ingestion flow.

    It deliberately returns one mapped-product candidate and one unmatched product.
    Re-running the sync returns the same external sale IDs, so the import layer
    demonstrates idempotency by skipping duplicates.
    """

    def test_connection(self, integration: POSIntegration) -> ConnectorResult:
        return ConnectorResult(
            success=True,
            message="Demo POS connector is ready. No external POS credentials are required.",
        )

    def pull_sales(self, integration: POSIntegration) -> list[CanonicalSale]:
        return [
            CanonicalSale(
                external_id="DEMO-SALE-1001",
                occurred_at=datetime(2026, 10, 1, 18, 30, tzinfo=timezone.utc),
                currency="RON",
                net_value=Decimal("60.00"),
                tax_value=Decimal("11.40"),
                gross_value=Decimal("71.40"),
                lines=[
                    CanonicalSaleLine(
                        external_product_id="HEI-330",
                        product_name="Heineken 330ml",
                        quantity=Decimal("24"),
                        uom="CASE",
                        unit_price=Decimal("2.50"),
                        net_value=Decimal("60.00"),
                        tax_value=Decimal("11.40"),
                    )
                ],
            ),
            CanonicalSale(
                external_id="DEMO-SALE-1002",
                occurred_at=datetime(2026, 10, 1, 19, 15, tzinfo=timezone.utc),
                currency="RON",
                net_value=Decimal("25.00"),
                tax_value=Decimal("4.75"),
                gross_value=Decimal("29.75"),
                lines=[
                    CanonicalSaleLine(
                        external_product_id="COLA-500",
                        product_name="Cola 500ml",
                        quantity=Decimal("10"),
                        uom="EA",
                        unit_price=Decimal("2.50"),
                        net_value=Decimal("25.00"),
                        tax_value=Decimal("4.75"),
                    )
                ],
            ),
        ]


@dataclass(frozen=True)
class POSProviderInfo:
    provider: str
    display_name: str
    supported_connection_types: tuple[str, ...]
    capabilities: tuple[str, ...]


PROVIDER_CATALOG: tuple[POSProviderInfo, ...] = (
    POSProviderInfo(
        provider="demo",
        display_name="Demo POS",
        supported_connection_types=("api",),
        capabilities=("sales_pull", "product_mapping", "uom_normalization", "idempotent_sync"),
    ),
    POSProviderInfo(
        provider="mock",
        display_name="Mock",
        supported_connection_types=("api", "webhook", "file"),
        capabilities=("connection_test",),
    ),
)



CONNECTORS: dict[str, POSConnector] = {
    "mock": MockPOSConnector(),
    "demo": DemoPOSConnector(),
}


def list_provider_catalog() -> list[POSProviderInfo]:
    return list(PROVIDER_CATALOG)


def register_connector(provider: str, connector: POSConnector) -> None:
    CONNECTORS[provider.lower()] = connector


def get_connector(provider: str) -> POSConnector:
    connector = CONNECTORS.get(provider.lower())

    if connector is None:
        raise ValueError(f"No connector registered for provider '{provider}'")

    return connector
