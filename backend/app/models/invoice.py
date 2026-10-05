from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class InvoiceImport(TimestampMixin, Base):
    """A supplier invoice / NIR read from a file or e-mail, waiting to become a goods receipt."""

    __tablename__ = "invoice_imports"
    __table_args__ = (UniqueConstraint("company_id", "content_sha256", name="uq_invoice_imports_company_file"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    location_id: Mapped[int | None] = mapped_column(ForeignKey("locations.id", ondelete="SET NULL"))
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id", ondelete="SET NULL"))
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="upload")  # upload | email
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)  # ubl_xml | pdf | image
    filename: Mapped[str | None] = mapped_column(String(300))
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(100))
    content: Mapped[bytes | None] = mapped_column(LargeBinary)
    # draft: extracted and matched, needs a person · posted: receipt created · rejected · failed: could not be read
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", index=True)
    extracted: Mapped[dict | None] = mapped_column(JSON)
    warnings: Mapped[list | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    receipt_id: Mapped[int | None] = mapped_column(ForeignKey("goods_receipts.id", ondelete="SET NULL"))
    mail_message_id: Mapped[str | None] = mapped_column(String(300))
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProductAlias(TimestampMixin, Base):
    """Remembers how a supplier names a product, so the next invoice matches automatically."""

    __tablename__ = "product_aliases"
    __table_args__ = (
        Index(
            "uq_product_aliases_supplier_key",
            "company_id", "supplier_id", "alias_key",
            unique=True,
            postgresql_where="supplier_id IS NOT NULL",
        ),
        Index(
            "uq_product_aliases_global_key",
            "company_id", "alias_key",
            unique=True,
            postgresql_where="supplier_id IS NULL",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id", ondelete="CASCADE"), index=True)
    alias_key: Mapped[str] = mapped_column(String(300), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
