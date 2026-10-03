from dataclasses import dataclass
from typing import Protocol

from app.models.pos_integration import POSIntegration


@dataclass
class ConnectorResult:
    success: bool
    message: str


class POSConnector(Protocol):
    def test_connection(self, integration: POSIntegration) -> ConnectorResult:
        ...

    def pull_sales(self, integration: POSIntegration) -> list[dict]:
        ...


class MockPOSConnector:
    def test_connection(self, integration: POSIntegration) -> ConnectorResult:
        return ConnectorResult(
            success=True,
            message=f"Mock connector for {integration.provider} is reachable.",
        )

    def pull_sales(self, integration: POSIntegration) -> list[dict]:
        return []


CONNECTORS: dict[str, POSConnector] = {
    "mock": MockPOSConnector(),
}


def get_connector(provider: str) -> POSConnector:
    connector = CONNECTORS.get(provider.lower())

    if connector is None:
        raise ValueError(f"No connector registered for provider '{provider}'")

    return connector
