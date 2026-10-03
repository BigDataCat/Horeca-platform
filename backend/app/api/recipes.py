from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.location import Location
from app.models.product import Product
from app.models.recipe import Recipe, RecipeLine
from app.models.user import User
from app.schemas.recipes import RecipeCreate, RecipeRead

router = APIRouter(prefix="/recipes", tags=["recipes"])


def require_manager(user: User) -> None:
    if user.role not in {"owner", "manager"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Owner or manager role required")


@router.get("", response_model=list[RecipeRead])
def list_recipes(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[Recipe]:
    return list(
        db.scalars(
            select(Recipe)
            .options(selectinload(Recipe.lines))
            .where(Recipe.company_id == current_user.company_id)
            .order_by(Recipe.id)
        ).all()
    )


@router.post("", response_model=RecipeRead, status_code=status.HTTP_201_CREATED)
def create_recipe(
    payload: RecipeCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Recipe:
    require_manager(current_user)

    product = db.get(Product, payload.product_id)
    if product is None or product.company_id != current_user.company_id:
        raise HTTPException(status_code=404, detail="Recipe product not found")

    if payload.location_id is not None:
        location = db.get(Location, payload.location_id)
        if location is None or location.company_id != current_user.company_id:
            raise HTTPException(status_code=404, detail="Location not found")

    ingredient_ids = {line.ingredient_product_id for line in payload.lines}
    ingredients = {
        p.id: p
        for p in db.scalars(
            select(Product).where(
                Product.company_id == current_user.company_id,
                Product.id.in_(ingredient_ids),
            )
        ).all()
    }
    if len(ingredients) != len(ingredient_ids):
        raise HTTPException(status_code=404, detail="One or more ingredient products were not found")

    recipe = Recipe(
        company_id=current_user.company_id,
        product_id=payload.product_id,
        location_id=payload.location_id,
        name=payload.name,
        active=True,
    )
    recipe.lines = [
        RecipeLine(
            ingredient_product_id=line.ingredient_product_id,
            quantity=line.quantity,
            uom=line.uom,
            waste_factor=line.waste_factor,
        )
        for line in payload.lines
    ]

    db.add(recipe)
    db.commit()
    db.refresh(recipe)
    return db.scalar(
        select(Recipe)
        .options(selectinload(Recipe.lines))
        .where(Recipe.id == recipe.id)
    )


@router.delete("/{recipe_id}", response_model=RecipeRead)
def deactivate_recipe(
    recipe_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Recipe:
    require_manager(current_user)
    recipe = db.get(Recipe, recipe_id)
    if recipe is None or recipe.company_id != current_user.company_id:
        raise HTTPException(status_code=404, detail="Recipe not found")
    recipe.active = False
    db.commit()
    db.refresh(recipe)
    return recipe
