from fastapi import APIRouter

from app.services.pos_connectors import list_provider_catalog

router = APIRouter(prefix="/integrations/pos/providers", tags=["pos-providers"])


@router.get("")
def list_pos_providers() -> list[dict[str, object]]:
    return [
        {
            "provider": item.provider,
            "display_name": item.display_name,
            "supported_connection_types": list(item.supported_connection_types),
            "capabilities": list(item.capabilities),
        }
        for item in list_provider_catalog()
    ]
