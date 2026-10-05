import secrets

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.common import clamp_page, set_total
from app.core.config import settings
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.company import Company
from app.models.invoice import InvoiceImport
from app.models.location import Location
from app.models.user import User
from app.schemas.invoices import InboxInfo, InboxSettings, InvoiceImportRead, InvoicePatch, InvoicePost
from app.services.invoice_intake import DuplicateInvoice, apply_patch, blocking_issues, import_invoice, post_invoice
from app.services.invoice_parsing import MAX_FILE_BYTES, InvoiceReadError

router = APIRouter(prefix="/invoices", tags=["invoices"])


def require_manager(user: User) -> None:
    if user.role not in {"owner", "manager"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Owner or manager role required")


def _own(db: Session, user: User, invoice_id: int) -> InvoiceImport:
    inv = db.get(InvoiceImport, invoice_id)
    if inv is None or inv.company_id != user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found")
    return inv


def _read(db: Session, inv: InvoiceImport) -> InvoiceImportRead:
    view = InvoiceImportRead.model_validate(inv)
    view.blocking = blocking_issues(db, inv)
    return view


@router.post("/upload", response_model=InvoiceImportRead, status_code=status.HTTP_201_CREATED)
async def upload_invoice(
    request: Request,
    filename: str | None = None,
    location_id: int | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> InvoiceImportRead:
    """Upload a supplier invoice/NIR as the raw request body: e-Factura XML or ZIP, PDF, or a PNG/JPEG/WEBP photo.

    XML is read exactly; PDFs and photos are read by AI and always need a person to confirm."""
    require_manager(current_user)
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail="The file is too large (10 MB maximum)")
    body = await request.body()
    if location_id is not None:
        location = db.get(Location, location_id)
        if location is None or location.company_id != current_user.company_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Location not found")
    company = db.get(Company, current_user.company_id)
    try:
        inv = import_invoice(
            db, company, current_user.id, body, filename, request.headers.get("content-type"),
            source="upload", location_id=location_id,
        )
    except DuplicateInvoice as dup:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"This file was already imported (invoice #{dup.existing.id}, {dup.existing.status})",
        )
    except InvoiceReadError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return _read(db, inv)


@router.get("", response_model=list[InvoiceImportRead])
def list_invoices(
    response: Response,
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[InvoiceImportRead]:
    query = select(InvoiceImport).where(InvoiceImport.company_id == current_user.company_id)
    if status_filter:
        query = query.where(InvoiceImport.status == status_filter)
    set_total(response, db, query)
    limit, offset = clamp_page(limit, offset, 200)
    rows = db.scalars(query.order_by(InvoiceImport.id.desc()).limit(limit).offset(offset)).all()
    return [_read(db, r) for r in rows]


@router.get("/inbox", response_model=InboxInfo)
def inbox_info(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> InboxInfo:
    company = db.get(Company, current_user.company_id)
    address = None
    if company.invoice_inbox_token and settings.invoice_inbox_address and "@" in settings.invoice_inbox_address:
        local, domain = settings.invoice_inbox_address.split("@", 1)
        address = f"{local}+{company.invoice_inbox_token}@{domain}"
    note = (
        "Ask suppliers to e-mail invoices (XML, PDF or photos) to this address; they appear here for review."
        if address
        else "E-mail intake is not available: the server has no mailbox configured, or no address was generated yet."
    )
    return InboxInfo(
        address=address,
        configured=bool(settings.imap_host and settings.invoice_inbox_address),
        auto_post=company.invoice_auto_post,
        default_location_id=company.invoice_default_location_id,
        note=note,
    )


@router.post("/inbox/token", response_model=InboxInfo)
def rotate_inbox_token(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> InboxInfo:
    """Generate (or replace) the secret part of the company's invoice e-mail address (owner only)."""
    if current_user.role != "owner":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Owner role required")
    company = db.get(Company, current_user.company_id)
    company.invoice_inbox_token = secrets.token_hex(8)
    db.commit()
    return inbox_info(current_user, db)


@router.patch("/inbox", response_model=InboxInfo)
def update_inbox_settings(payload: InboxSettings, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> InboxInfo:
    if current_user.role != "owner":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Owner role required")
    company = db.get(Company, current_user.company_id)
    values = payload.model_dump(exclude_unset=True)
    if values.get("default_location_id") is not None:
        location = db.get(Location, values["default_location_id"])
        if location is None or location.company_id != company.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Location not found")
    if "auto_post" in values and values["auto_post"] is not None:
        company.invoice_auto_post = values["auto_post"]
    if "default_location_id" in values:
        company.invoice_default_location_id = values["default_location_id"]
    db.commit()
    return inbox_info(current_user, db)


@router.get("/{invoice_id}", response_model=InvoiceImportRead)
def get_invoice(invoice_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> InvoiceImportRead:
    return _read(db, _own(db, current_user, invoice_id))


@router.get("/{invoice_id}/file")
def download_invoice_file(invoice_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Response:
    inv = _own(db, current_user, invoice_id)
    safe_name = "".join(c for c in (inv.filename or f"invoice-{inv.id}") if c.isalnum() or c in "._- ")[:100] or f"invoice-{inv.id}"
    return Response(
        content=inv.content or b"",
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}"', "X-Content-Type-Options": "nosniff"},
    )


@router.patch("/{invoice_id}", response_model=InvoiceImportRead)
def patch_invoice(
    invoice_id: int, payload: InvoicePatch, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> InvoiceImportRead:
    """Correct a draft: assign products to lines, skip lines, fix quantity/unit/price, set location/supplier."""
    require_manager(current_user)
    inv = _own(db, current_user, invoice_id)
    apply_patch(db, inv, payload, current_user.company_id)
    db.commit()
    db.refresh(inv)
    return _read(db, inv)


@router.post("/{invoice_id}/post", response_model=InvoiceImportRead)
def post_invoice_endpoint(
    invoice_id: int, payload: InvoicePost, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> InvoiceImportRead:
    """Create the goods receipt (stock + costs) from a reviewed draft. Teaches the system the supplier's product names."""
    require_manager(current_user)
    inv = _own(db, current_user, invoice_id)
    if payload.location_id is not None:
        location = db.get(Location, payload.location_id)
        if location is None or location.company_id != current_user.company_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Location not found")
    inv = post_invoice(db, inv, current_user.id, payload.location_id)
    return _read(db, inv)


@router.post("/{invoice_id}/reject", response_model=InvoiceImportRead)
def reject_invoice(invoice_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> InvoiceImportRead:
    require_manager(current_user)
    inv = _own(db, current_user, invoice_id)
    if inv.status not in {"draft", "failed"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Invoice is already {inv.status}")
    inv.status = "rejected"
    db.commit()
    db.refresh(inv)
    return _read(db, inv)
