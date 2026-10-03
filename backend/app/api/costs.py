from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.location import Location
from app.models.product import Product
from app.models.product_cost import ProductCost
from app.models.recipe import Recipe
from app.models.user import User
from app.services.costing import resolve_unit_cost
from app.schemas.costs import ProductCostCreate, ProductCostRead, RecipeCostLineRead, RecipeCostRead

router = APIRouter(prefix="/costs", tags=["costs"])


def require_manager(user: User) -> None:
    if user.role not in {"owner", "manager"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Owner or manager role required")


@router.get("/products", response_model=list[ProductCostRead])
def list_product_costs(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[ProductCost]:
    return list(
        db.scalars(
            select(ProductCost)
            .where(ProductCost.company_id == current_user.company_id)
            .order_by(ProductCost.effective_from.desc())
        ).all()
    )


@router.post("/products", response_model=ProductCostRead, status_code=status.HTTP_201_CREATED)
def create_product_cost(
    payload: ProductCostCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProductCost:
    require_manager(current_user)
    product = db.get(Product, payload.product_id)
    if product is None or product.company_id != current_user.company_id:
        raise HTTPException(status_code=404, detail="Product not found")
    if payload.location_id is not None:
        location = db.get(Location, payload.location_id)
        if location is None or location.company_id != current_user.company_id:
            raise HTTPException(status_code=404, detail="Location not found")

    cost = ProductCost(
        company_id=current_user.company_id,
        product_id=payload.product_id,
        location_id=payload.location_id,
        unit_cost=payload.unit_cost,
        currency=payload.currency.upper(),
        effective_from=payload.effective_from,
    )
    db.add(cost)
    db.commit()
    db.refresh(cost)
    return cost


@router.get("/recipes/{recipe_id}", response_model=RecipeCostRead)
def calculate_recipe_cost(
    recipe_id: int,
    location_id: int | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RecipeCostRead:
    recipe = db.get(Recipe, recipe_id)
    if recipe is None or recipe.company_id != current_user.company_id:
        raise HTTPException(status_code=404, detail="Recipe not found")

    target_location_id = location_id or recipe.location_id
    lines: list[RecipeCostLineRead] = []
    total: Decimal | None = Decimal("0")
    currency = "RON"
    missing_cost = False

    for line in recipe.lines:
        cost = resolve_unit_cost(
            db, current_user.company_id, line.ingredient_product_id, target_location_id
        )

        line_cost = None
        unit_cost = None
        if cost is None:
            missing_cost = True
        else:
            unit_cost = cost.unit_cost
            line_cost = line.quantity * (Decimal("1") + line.waste_factor) * cost.unit_cost
            total += line_cost
            currency = cost.currency

        lines.append(
            RecipeCostLineRead(
                ingredient_product_id=line.ingredient_product_id,
                quantity=line.quantity,
                uom=line.uom,
                unit_cost=unit_cost,
                line_cost=line_cost,
            )
        )

    return RecipeCostRead(
        recipe_id=recipe.id,
        recipe_name=recipe.name,
        currency=currency,
        total_cost=None if missing_cost else total,
        lines=lines,
    )
