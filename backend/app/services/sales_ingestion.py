import json
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.pos_integration import POSIntegration
from app.models.product import Product
from app.models.product_mapping import ProductMapping
from app.models.product_uom_conversion import ProductUOMConversion
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
            Product.name.ilike(product_name),
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
) -> bool:
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
    )

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

    db.add(sale)
    return True
