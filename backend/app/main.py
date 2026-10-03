from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.auth import router as auth_router
from app.api.inventory import router as inventory_router
from app.api.recipes import router as recipes_router
from app.api.companies import router as companies_router
from app.api.locations import router as locations_router
from app.api.pos_integrations import router as pos_integrations_router
from app.api.pos_providers import router as pos_providers_router
from app.api.product_mappings import router as product_mappings_router
from app.api.products import router as products_router
from app.api.sales import router as sales_router
from app.api.users import router as users_router

app = FastAPI(title="HoReCa Management Platform API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix="/api")
app.include_router(inventory_router, prefix="/api")
app.include_router(recipes_router, prefix="/api")
app.include_router(companies_router, prefix="/api")
app.include_router(locations_router, prefix="/api")
app.include_router(pos_integrations_router, prefix="/api")
app.include_router(pos_providers_router, prefix="/api")
app.include_router(product_mappings_router, prefix="/api")
app.include_router(products_router, prefix="/api")
app.include_router(sales_router, prefix="/api")
app.include_router(users_router, prefix="/api")


@app.get("/health", tags=["system"])
def health_check() -> dict[str, str]:
    return {"status": "ok"}
