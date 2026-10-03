from dataclasses import dataclass
from typing import Protocol

from app.models.pos_integration import POSIntegration
from app.schemas.sales import CanonicalSale


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


CONNECTORS: dict[str, POSConnector] = {
    "mock": MockPOSConnector(),
}


def register_connector(provider: str, connector: POSConnector) -> None:
    CONNECTORS[provider.lower()] = connector


def get_connector(provider: str) -> POSConnector:
    connector = CONNECTORS.get(provider.lower())

    if connector is None:
        raise ValueError(f"No connector registered for provider '{provider}'")

    return connector
