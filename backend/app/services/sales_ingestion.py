import json
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.pos_integration import POSIntegration
from app.models.product import Product
from app.models.product_mapping import ProductMapping
from app.models.product_uom_conversion import ProductUOMConversion
from app.models.recipe import Recipe
from app.models.inventory import ProductStock, StockMovement
from app.models.sale import Sale, SaleLine
from app.schemas.sales import CanonicalSale


def resolve_product(
    db: Session,
    company_id: int,
    integration_id: int,
    external_product_id: str | None,
    product_name: str,
) -> Product | None:
    if external_product_id:
        mapping = db.scalar(
            select(ProductMapping).where(
                ProductMapping.company_id == company_id,
                ProductMapping.integration_id == integration_id,
                ProductMapping.external_product_id == external_product_id,
                ProductMapping.active.is_(True),
            )
        )
        if mapping is not None:
            return mapping.product

        product = db.scalar(
            select(Product).where(
                Product.company_id == company_id,
                Product.sku == external_product_id,
            )
        )
        if product is not None:
            return product

    return db.scalar(
        select(Product).where(
            Product.company_id == company_id,
            func.lower(Product.name) == product_name.lower(),
        )
    )


def normalize_quantity(
    db: Session,
    company_id: int,
    product: Product,
    quantity: Decimal,
    from_uom: str,
) -> tuple[Decimal, str]:
    source_uom = from_uom.upper()
    target_uom = product.base_uom.upper()

    if source_uom == target_uom:
        return quantity, target_uom

    conversion = db.scalar(
        select(ProductUOMConversion).where(
            ProductUOMConversion.company_id == company_id,
            ProductUOMConversion.product_id == product.id,
            ProductUOMConversion.from_uom == source_uom,
            ProductUOMConversion.to_uom == target_uom,
            ProductUOMConversion.active.is_(True),
        )
    )

    if conversion is None:
        return quantity, source_uom

    return quantity * conversion.factor, target_uom


def import_sale(
    db: Session,
    integration: POSIntegration,
    canonical_sale: CanonicalSale,
    status: str = "completed",
    reason: str | None = None,
) -> bool:
    """Persist a sale. Non-completed sales are stored without touching stock."""
    duplicate = db.scalar(
        select(Sale).where(
            Sale.company_id == integration.company_id,
            Sale.integration_id == integration.id,
            Sale.external_id == canonical_sale.external_id,
        )
    )

    if duplicate is not None:
        return False

    sale = Sale(
        company_id=integration.company_id,
        location_id=integration.location_id,
        integration_id=integration.id,
        external_id=canonical_sale.external_id,
        occurred_at=canonical_sale.occurred_at,
        currency=canonical_sale.currency.upper(),
        net_value=canonical_sale.net_value,
        tax_value=canonical_sale.tax_value,
        gross_value=canonical_sale.gross_value,
        source_payload=json.dumps(canonical_sale.model_dump(mode="json")),
        status=status,
        status_reason=reason,
        status_changed_at=datetime.now(timezone.utc) if status != "completed" else None,
    )
    consumption: list[tuple[Product, Decimal]] = []

    for line in canonical_sale.lines:
        product = resolve_product(
            db,
            integration.company_id,
            integration.id,
            line.external_product_id,
            line.product_name,
        )

        quantity = line.quantity
        uom = line.uom.upper()

        if product is not None:
            quantity, uom = normalize_quantity(
                db,
                integration.company_id,
                product,
                line.quantity,
                line.uom,
            )

        sale.lines.append(
            SaleLine(
                product_id=product.id if product else None,
                external_product_id=line.external_product_id,
                product_name=line.product_name,
                quantity=quantity,
                uom=uom,
                unit_price=line.unit_price,
                net_value=line.net_value,
                tax_value=line.tax_value,
            )
        )

        if product is not None:
            consumption.append((product, quantity))

    db.add(sale)
    # Flush so the sale has an id (stock movements link to it) and is visible to the
    # duplicate check for later sales in the same batch.
    db.flush()

    if status == "completed":
        for product, quantity in consumption:
            apply_recipe_consumption(
                db,
                integration,
                product,
                quantity,
                canonical_sale.external_id,
                canonical_sale.occurred_at,
                sale.id,
            )
    return True


def apply_recipe_consumption(
    db: Session,
    integration: POSIntegration,
    product: Product,
    sold_quantity: Decimal,
    sale_external_id: str,
    occurred_at: datetime,
    sale_id: int,
) -> None:
    recipe = db.scalar(
        select(Recipe).where(
            Recipe.company_id == integration.company_id,
            Recipe.product_id == product.id,
            Recipe.active.is_(True),
            Recipe.location_id == integration.location_id,
        )
    )
    if recipe is None:
        recipe = db.scalar(
            select(Recipe).where(
                Recipe.company_id == integration.company_id,
                Recipe.product_id == product.id,
                Recipe.active.is_(True),
                Recipe.location_id.is_(None),
            )
        )
    if recipe is None:
        return

    for line in recipe.lines:
        ingredient = line.ingredient_product
        required = sold_quantity * line.quantity * (Decimal("1") + line.waste_factor)
        normalized_quantity, normalized_uom = normalize_quantity(
            db, integration.company_id, ingredient, required, line.uom
        )
        if normalized_uom != ingredient.base_uom.upper():
            raise ValueError(
                f"No UOM conversion for recipe ingredient {ingredient.id}: "
                f"{line.uom} -> {ingredient.base_uom}"
            )
        stock = db.scalar(select(ProductStock).where(
            ProductStock.company_id == integration.company_id,
            ProductStock.location_id == integration.location_id,
            ProductStock.product_id == ingredient.id,
        ))
        if stock is None:
            stock = ProductStock(
                company_id=integration.company_id,
                location_id=integration.location_id,
                product_id=ingredient.id,
                quantity=Decimal("0"),
                uom=normalized_uom,
            )
            db.add(stock)
        stock.quantity -= normalized_quantity
        stock.uom = normalized_uom
        db.add(StockMovement(
            company_id=integration.company_id,
            location_id=integration.location_id,
            product_id=ingredient.id,
            movement_type="recipe_consumption",
            quantity=-normalized_quantity,
            uom=normalized_uom,
            reference_type="sale",
            reference_id=sale_external_id,
            sale_id=sale_id,
            occurred_at=occurred_at,
            note="Recipe consumption: " + recipe.name,
        ))


def reverse_sale_consumption(db: Session, sale: Sale, occurred_at: datetime) -> int:
    """Give back the ingredients a sale consumed. Returns the number of reversal movements."""
    consumed = db.scalars(
        select(StockMovement).where(
            StockMovement.company_id == sale.company_id,
            StockMovement.sale_id == sale.id,
            StockMovement.movement_type == "recipe_consumption",
        )
    ).all()
    for movement in consumed:
        stock = db.scalar(
            select(ProductStock).where(
                ProductStock.company_id == movement.company_id,
                ProductStock.location_id == movement.location_id,
                ProductStock.product_id == movement.product_id,
            )
        )
        if stock is None:
            continue
        stock.quantity -= movement.quantity  # consumption movements are negative
        db.add(
            StockMovement(
                company_id=movement.company_id,
                location_id=movement.location_id,
                product_id=movement.product_id,
                movement_type="sale_reversal",
                quantity=-movement.quantity,
                uom=movement.uom,
                reference_type="sale",
                reference_id=sale.external_id,
                sale_id=sale.id,
                occurred_at=occurred_at,
                note=f"Reversal of {movement.note or 'recipe consumption'}",
            )
        )
    return len(consumed)


def change_sale_status(
    db: Session,
    sale: Sale,
    new_status: str,
    reason: str | None = None,
) -> bool:
    """Cancel or refund a completed sale and restore stock. Idempotent: returns False if already changed."""
    if sale.status != "completed":
        return False
    now = datetime.now(timezone.utc)
    reverse_sale_consumption(db, sale, now)
    sale.status = new_status
    sale.status_reason = reason
    sale.status_changed_at = now
    return True


def apply_sale_status_event(
    db: Session,
    integration: POSIntegration,
    canonical_sale: CanonicalSale,
    new_status: str,
    reason: str | None = None,
) -> bool:
    """Handle a cancel/refund event from a POS. If the sale was never received (events can
    arrive out of order) it is stored as already cancelled so a late "created" event is a no-op."""
    sale = db.scalar(
        select(Sale).where(
            Sale.company_id == integration.company_id,
            Sale.integration_id == integration.id,
            Sale.external_id == canonical_sale.external_id,
        )
    )
    if sale is None:
        return import_sale(db, integration, canonical_sale, status=new_status, reason=reason)
    return change_sale_status(db, sale, new_status, reason)
