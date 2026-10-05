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
        refunded_net_value=canonical_sale.net_value if status != "completed" else Decimal("0"),
        refunded_tax_value=canonical_sale.tax_value if status != "completed" else Decimal("0"),
    )
    consumption: list[tuple[Product, Decimal, SaleLine]] = []

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

        sale_line = SaleLine(
            product_id=product.id if product else None,
            external_product_id=line.external_product_id,
            product_name=line.product_name,
            quantity=quantity,
            uom=uom,
            unit_price=line.unit_price,
            net_value=line.net_value,
            tax_value=line.tax_value,
            refunded_quantity=quantity if status != "completed" else Decimal("0"),
            refunded_net_value=line.net_value if status != "completed" else Decimal("0"),
            refunded_tax_value=line.tax_value if status != "completed" else Decimal("0"),
        )
        sale.lines.append(sale_line)

        if product is not None:
            consumption.append((product, quantity, sale_line))

    db.add(sale)
    # Flush so the sale has an id (stock movements link to it) and is visible to the
    # duplicate check for later sales in the same batch.
    db.flush()

    if status == "completed":
        for product, quantity, sale_line in consumption:
            apply_recipe_consumption(
                db,
                integration,
                product,
                quantity,
                canonical_sale.external_id,
                canonical_sale.occurred_at,
                sale.id,
                sale_line.id,
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
    sale_line_id: int | None = None,
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
            sale_line_id=sale_line_id,
            occurred_at=occurred_at,
            note="Recipe consumption: " + recipe.name,
        ))


ACTIVE_STATUSES = ("completed", "partially_refunded")
CENT = Decimal("0.01")


def _movement_net(db: Session, sale: Sale, sale_line_id: int | None = None) -> dict[tuple[int, int, int | None], tuple[Decimal, str]]:
    """Net stock effect (consumption + reversals) of a sale, per (location, product, line)."""
    query = select(StockMovement).where(
        StockMovement.company_id == sale.company_id,
        StockMovement.sale_id == sale.id,
        StockMovement.movement_type.in_(("recipe_consumption", "sale_reversal")),
    )
    if sale_line_id is not None:
        query = query.where(StockMovement.sale_line_id == sale_line_id)
    net: dict[tuple[int, int, int | None], tuple[Decimal, str]] = {}
    for movement in db.scalars(query).all():
        key = (movement.location_id, movement.product_id, movement.sale_line_id)
        total, _ = net.get(key, (Decimal("0"), movement.uom))
        net[key] = (total + movement.quantity, movement.uom)
    return net


def _give_back(db: Session, sale: Sale, location_id: int, product_id: int, line_id: int | None, quantity: Decimal, uom: str, occurred_at: datetime, note: str) -> None:
    """Return ``quantity`` (positive) of an ingredient to stock and record the reversal."""
    if quantity == 0:
        return
    stock = db.scalar(
        select(ProductStock).where(
            ProductStock.company_id == sale.company_id,
            ProductStock.location_id == location_id,
            ProductStock.product_id == product_id,
        )
    )
    if stock is None:
        return
    stock.quantity += quantity
    db.add(
        StockMovement(
            company_id=sale.company_id,
            location_id=location_id,
            product_id=product_id,
            movement_type="sale_reversal",
            quantity=quantity,
            uom=uom,
            reference_type="sale",
            reference_id=sale.external_id,
            sale_id=sale.id,
            sale_line_id=line_id,
            occurred_at=occurred_at,
            note=note,
        )
    )


def reverse_sale_consumption(db: Session, sale: Sale, occurred_at: datetime) -> int:
    """Give back everything the sale still holds out of stock (idempotent after partial refunds).

    Returns the number of reversal movements created."""
    created = 0
    for (location_id, product_id, line_id), (net, uom) in _movement_net(db, sale).items():
        if net < 0:
            _give_back(db, sale, location_id, product_id, line_id, -net, uom, occurred_at, "Reversal of recipe consumption")
            created += 1
    return created


def change_sale_status(
    db: Session,
    sale: Sale,
    new_status: str,
    reason: str | None = None,
) -> bool:
    """Cancel or fully refund a sale (also after partial refunds) and restore stock.

    Idempotent: returns False if the sale is already cancelled/refunded."""
    if sale.status not in ACTIVE_STATUSES:
        return False
    now = datetime.now(timezone.utc)
    reverse_sale_consumption(db, sale, now)
    for sale_line in sale.lines:
        sale_line.refunded_quantity = sale_line.quantity
        sale_line.refunded_net_value = sale_line.net_value
        sale_line.refunded_tax_value = sale_line.tax_value
    sale.refunded_net_value = sale.net_value
    sale.refunded_tax_value = sale.tax_value
    sale.status = new_status
    sale.status_reason = reason
    sale.status_changed_at = now
    return True


class RefundError(ValueError):
    pass


def refund_sale_lines(
    db: Session,
    sale: Sale,
    requests: list[tuple[int, Decimal]],
    reason: str | None = None,
) -> None:
    """Refund part of a sale: ``requests`` is a list of (sale_line_id, quantity).

    Revenue and ingredient stock are reversed proportionally. When every line is fully
    refunded the sale becomes ``refunded``; otherwise ``partially_refunded``."""
    if sale.status not in ACTIVE_STATUSES:
        raise RefundError(f"Sale is already {sale.status}")
    if not requests:
        raise RefundError("Nothing to refund")
    lines = {line.id: line for line in sale.lines}
    seen: set[int] = set()
    now = datetime.now(timezone.utc)

    for line_id, quantity in requests:
        if line_id in seen:
            raise RefundError("A line can appear only once per refund")
        seen.add(line_id)
        line = lines.get(line_id)
        if line is None:
            raise RefundError(f"Line {line_id} does not belong to this sale")
        if quantity <= 0:
            raise RefundError("Refund quantity must be positive")
        remaining = line.quantity - line.refunded_quantity
        if quantity > remaining:
            raise RefundError(f"Line {line_id}: only {remaining} left to refund")

        final = quantity == remaining
        if final:
            net_part = line.net_value - line.refunded_net_value
            tax_part = line.tax_value - line.refunded_tax_value
        else:
            fraction = quantity / line.quantity
            net_part = (line.net_value * fraction).quantize(CENT)
            tax_part = (line.tax_value * fraction).quantize(CENT)

        if line.product_id is not None:
            movements = _movement_net(db, sale, line_id)
            consumed_rows = db.scalars(
                select(StockMovement).where(
                    StockMovement.sale_id == sale.id,
                    StockMovement.sale_line_id == line_id,
                    StockMovement.movement_type == "recipe_consumption",
                )
            ).all()
            if not consumed_rows and any(
                m.sale_line_id is None and m.movement_type == "recipe_consumption"
                for m in db.scalars(select(StockMovement).where(StockMovement.sale_id == sale.id)).all()
            ):
                raise RefundError("This sale predates line-level tracking: cancel or refund the whole sale instead")
            consumed_total: dict[tuple[int, int], Decimal] = {}
            for movement in consumed_rows:
                key = (movement.location_id, movement.product_id)
                consumed_total[key] = consumed_total.get(key, Decimal("0")) + movement.quantity
            for (location_id, product_id, _), (net, uom) in movements.items():
                if net >= 0:
                    continue
                give = -net if final else min(-net, (-consumed_total.get((location_id, product_id), Decimal("0")) * quantity / line.quantity))
                _give_back(db, sale, location_id, product_id, line_id, give, uom, now, f"Partial refund of sale {sale.external_id}")

        line.refunded_quantity += quantity
        line.refunded_net_value += net_part
        line.refunded_tax_value += tax_part
        sale.refunded_net_value += net_part
        sale.refunded_tax_value += tax_part

    fully = all(line.refunded_quantity >= line.quantity for line in sale.lines)
    sale.status = "refunded" if fully else "partially_refunded"
    sale.status_reason = reason
    sale.status_changed_at = now


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
