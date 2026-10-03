import json
import logging
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from app.core.config import settings
from app.core.database import SessionLocal

from app.api.auth import router as auth_router
from app.api.inventory import router as inventory_router
from app.api.recipes import router as recipes_router
from app.api.webhooks import router as webhooks_router
from app.api.companies import router as companies_router
from app.api.dashboard import router as dashboard_router
from app.api.costs import router as costs_router
from app.api.locations import router as locations_router
from app.api.pos_integrations import router as pos_integrations_router
from app.api.pos_providers import router as pos_providers_router
from app.api.product_mappings import router as product_mappings_router
from app.api.products import router as products_router
from app.api.sales import router as sales_router
from app.api.users import router as users_router
from app.api.reports import router as reports_router
from app.api.purchasing import router as purchasing_router
from app.api.stock_ops import router as stock_ops_router

logger = logging.getLogger("horeca.api")
if not logging.getLogger().handlers:
    logging.basicConfig(level=logging.INFO, format="%(message)s")

app = FastAPI(title="HoReCa Management Platform API", version="1.3.0")

@app.middleware("http")
async def log_requests(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
    started = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        logger.info(
            json.dumps(
                {
                    "event": "http_request",
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status": status_code,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                }
            )
        )


app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix="/api")
app.include_router(inventory_router, prefix="/api")
app.include_router(recipes_router, prefix="/api")
app.include_router(webhooks_router, prefix="/api")
app.include_router(companies_router, prefix="/api")
app.include_router(dashboard_router, prefix="/api")
app.include_router(costs_router, prefix="/api")
app.include_router(locations_router, prefix="/api")
app.include_router(pos_integrations_router, prefix="/api")
app.include_router(pos_providers_router, prefix="/api")
app.include_router(product_mappings_router, prefix="/api")
app.include_router(products_router, prefix="/api")
app.include_router(sales_router, prefix="/api")
app.include_router(users_router, prefix="/api")
app.include_router(reports_router, prefix="/api")
app.include_router(purchasing_router, prefix="/api")
app.include_router(stock_ops_router, prefix="/api")


@app.get("/health", tags=["system"])
def health_check() -> dict[str, str]:
    with SessionLocal() as db:
        db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "ok"}
