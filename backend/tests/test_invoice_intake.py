from decimal import Decimal

import pytest

from tests.conftest import create_location, create_product, get_stock
from tests.invoice_samples import efactura_zip, ubl_invoice


def upload(client, tenant, content, filename="factura.xml", content_type="application/xml", **params):
    return client.post(
        "/api/invoices/upload", headers={**tenant["headers"], "Content-Type": content_type},
        params={"filename": filename, **params}, content=content,
    )


def get(client, tenant, invoice_id):
    return client.get(f"/api/invoices/{invoice_id}", headers=tenant["headers"]).json()


def patch(client, tenant, invoice_id, **body):
    return client.patch(f"/api/invoices/{invoice_id}", headers=tenant["headers"], json=body)


def post(client, tenant, invoice_id, **body):
    return client.post(f"/api/invoices/{invoice_id}/post", headers=tenant["headers"], json=body)


def stock(client, tenant, location, product):
    row = get_stock(client, tenant, location, product)
    return Decimal(row["quantity"]) if row else Decimal("0")


@pytest.fixture()
def shop(client, tenant_a):
    location = create_location(client, tenant_a, "Main")
    beef = create_product(client, tenant_a, "Carne vita", sku="SKU-1", base_uom="KG")
    salt = create_product(client, tenant_a, "Sare fina", base_uom="EA")
    return location, beef, salt


def test_xml_invoice_is_read_matched_and_posted(client, tenant_a, shop):
    location, beef, salt = shop
    response = upload(client, tenant_a, ubl_invoice())
    assert response.status_code == 201, response.text
    invoice = response.json()
    assert invoice["status"] == "draft" and invoice["source_type"] == "ubl_xml"
    assert invoice["location_id"] == location["id"]                      # only one location: chosen automatically
    header = invoice["extracted"]["header"]
    assert (header["supplier_name"], header["supplier_tax_id"], header["document_number"]) == ("Metro Cash & Carry SRL", "RO1234567", "FCT-100")
    lines = invoice["extracted"]["lines"]
    assert [(l["match"], l["unit"]) for l in lines] == [("sku", "KG"), ("name", "EA")]   # SKU, then exact name
    assert invoice["blocking"] == [] and invoice["warnings"] == ["New supplier 'Metro Cash & Carry SRL' will be created when the receipt is posted"]

    posted = post(client, tenant_a, invoice["id"])
    assert posted.status_code == 200, posted.text
    assert posted.json()["status"] == "posted" and posted.json()["receipt_id"]
    assert stock(client, tenant_a, location, beef) == Decimal("10")
    assert stock(client, tenant_a, location, salt) == Decimal("20")
    costs = {c["product_id"]: Decimal(c["unit_cost"]) for c in client.get("/api/costs/products", headers=tenant_a["headers"]).json()}
    assert costs == {beef["id"]: Decimal("42.5"), salt["id"]: Decimal("1.2")}      # net of VAT
    suppliers = client.get("/api/suppliers", headers=tenant_a["headers"]).json()
    assert [s["name"] for s in suppliers] == ["Metro Cash & Carry SRL"]
    receipt = client.get(f"/api/inventory/receipts/{posted.json()['receipt_id']}", headers=tenant_a["headers"]).json()
    assert receipt["document_number"] == "FCT-100" and receipt["received_at"].startswith("2026-10-02")


def test_unmatched_lines_block_posting_until_assigned_and_the_choice_is_remembered(client, tenant_a, shop):
    location, beef, salt = shop
    xml = ubl_invoice(number="A1", lines=[("Antricot de vita maturat", "5", "KGM", "80.00", "AX-9")])
    invoice = upload(client, tenant_a, xml).json()
    assert invoice["extracted"]["lines"][0]["match"] is None
    assert any("not matched" in b for b in invoice["blocking"])
    assert post(client, tenant_a, invoice["id"]).status_code == 400

    fixed = patch(client, tenant_a, invoice["id"], lines=[{"index": 0, "product_id": beef["id"]}])
    assert fixed.status_code == 200 and fixed.json()["blocking"] == []
    assert fixed.json()["extracted"]["lines"][0]["match"] == "manual"
    assert post(client, tenant_a, invoice["id"]).status_code == 200
    assert stock(client, tenant_a, location, beef) == Decimal("5")

    # next month, same supplier, same wording: matched by the remembered alias, no review needed
    again = upload(client, tenant_a, ubl_invoice(number="A2", lines=[("Antricot de vita maturat", "3", "KGM", "82.00", "AX-9")])).json()
    assert again["extracted"]["lines"][0]["match"] == "alias"
    assert again["blocking"] == []
    assert again["extracted"]["header"]["supplier_name"] == "Metro Cash & Carry SRL"
    assert not any("New supplier" in w for w in again["warnings"])        # the supplier now exists


def test_wording_is_matched_ignoring_case_diacritics_and_punctuation(client, tenant_a, shop):
    location, beef, salt = shop
    create_product(client, tenant_a, "Roșii cherry", base_uom="KG")
    invoice = upload(client, tenant_a, ubl_invoice(lines=[("ROSII  CHERRY.", "2", "KGM", "9.00", "")])).json()
    assert invoice["extracted"]["lines"][0]["match"] == "name"


def test_unit_conversion_is_never_guessed(client, tenant_a, shop):
    location, beef, salt = shop
    xml = ubl_invoice(lines=[("Sare fina", "4", "XBX", "30.00", "S")])           # a box of salt; product is counted in EA
    invoice = upload(client, tenant_a, xml).json()
    assert invoice["extracted"]["lines"][0]["unit"] == "BOX"
    assert any("no unit conversion" in b for b in invoice["blocking"])
    assert post(client, tenant_a, invoice["id"]).status_code == 400

    conversion = client.post(
        "/api/product-mappings/uom-conversions", headers=tenant_a["headers"],
        json={"product_id": salt["id"], "from_uom": "BOX", "to_uom": "EA", "factor": "10"},
    )
    assert conversion.status_code == 201
    assert get(client, tenant_a, invoice["id"])["blocking"] == []             # recomputed, no re-upload needed
    assert post(client, tenant_a, invoice["id"]).status_code == 200
    assert stock(client, tenant_a, location, salt) == Decimal("40")
    cost = client.get("/api/costs/products", headers=tenant_a["headers"]).json()[0]
    assert Decimal(cost["unit_cost"]) == Decimal("3")                        # 30 per box / 10 per box


def test_quantity_unit_and_price_can_be_corrected(client, tenant_a, shop):
    location, beef, salt = shop
    invoice = upload(client, tenant_a, ubl_invoice(lines=[("Carne vita", "10", "H87", "42.50", "SKU-1")])).json()
    assert invoice["blocking"]                                              # pieces cannot become kg
    fixed = patch(client, tenant_a, invoice["id"], lines=[{"index": 0, "unit": "kg", "quantity": "9.5", "unit_price": "43"}])
    assert fixed.json()["blocking"] == []
    post(client, tenant_a, invoice["id"])
    assert stock(client, tenant_a, location, beef) == Decimal("9.5")
    assert Decimal(client.get("/api/costs/products", headers=tenant_a["headers"]).json()[0]["unit_cost"]) == Decimal("43")


def test_discount_and_transport_lines_can_be_skipped(client, tenant_a, shop):
    location, beef, salt = shop
    xml = ubl_invoice(lines=[("Carne vita", "10", "KGM", "42.50", "SKU-1"), ("Discount comercial", "1", "H87", "-20.00", ""), ("Transport", "1", "H87", "50.00", "")])
    invoice = upload(client, tenant_a, xml).json()
    assert len(invoice["blocking"]) >= 2
    fixed = patch(client, tenant_a, invoice["id"], lines=[{"index": 1, "skip": True}, {"index": 2, "skip": True}])
    assert fixed.json()["blocking"] == []
    post(client, tenant_a, invoice["id"])
    assert stock(client, tenant_a, location, beef) == Decimal("10")
    assert len(client.get("/api/costs/products", headers=tenant_a["headers"]).json()) == 1


def test_numbers_that_do_not_add_up_are_flagged(client, tenant_a, shop):
    invoice = upload(client, tenant_a, ubl_invoice(total_net="999.00", total_gross="1088.91")).json()
    assert any("net total" in w for w in invoice["warnings"])


def test_same_file_and_same_document_number_are_not_imported_twice(client, tenant_a, shop):
    xml = ubl_invoice()
    first = upload(client, tenant_a, xml)
    assert first.status_code == 201
    assert upload(client, tenant_a, xml).status_code == 409
    post(client, tenant_a, first.json()["id"])
    # a re-issued file with the same invoice number from the same supplier
    variant = ubl_invoice(lines=[("Carne vita", "11", "KGM", "42.50", "SKU-1"), ("Sare fina", "20", "H87", "1.20", "SKU-2")])
    second = upload(client, tenant_a, variant, filename="again.xml").json()
    assert any("already posted" in w for w in second["warnings"])
    blocked = post(client, tenant_a, second["id"])
    assert blocked.status_code == 409 and "document number" in blocked.json()["detail"]


def test_credit_notes_are_not_posted(client, tenant_a, shop):
    invoice = upload(client, tenant_a, ubl_invoice(kind="CreditNote")).json()
    assert invoice["extracted"]["header"]["document_type"] == "credit_note"
    assert any("Credit notes" in b for b in invoice["blocking"])
    assert post(client, tenant_a, invoice["id"]).status_code == 400
    rejected = client.post(f"/api/invoices/{invoice['id']}/reject", headers=tenant_a["headers"])
    assert rejected.json()["status"] == "rejected"
    assert post(client, tenant_a, invoice["id"]).status_code == 409


def test_efactura_zip_with_signature_file_is_accepted(client, tenant_a, shop):
    response = upload(client, tenant_a, efactura_zip(ubl_invoice()), filename="123.zip", content_type="application/zip")
    assert response.status_code == 201 and response.json()["status"] == "draft"
    assert response.json()["extracted"]["header"]["document_number"] == "FCT-100"


def test_unreadable_and_hostile_files_are_kept_as_failed_not_crashed(client, tenant_a):
    broken = upload(client, tenant_a, b"<Invoice><unclosed>")
    assert broken.status_code == 201 and broken.json()["status"] == "failed" and broken.json()["error"]
    not_ubl = upload(client, tenant_a, b"<html><body>hello</body></html>")
    assert not_ubl.json()["status"] == "failed" and "not a UBL" in not_ubl.json()["error"]
    bomb = b'<?xml version="1.0"?><!DOCTYPE lol [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;">]><Invoice>&b;</Invoice>'
    assert upload(client, tenant_a, bomb).json()["status"] == "failed"
    xxe = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><Invoice>&e;</Invoice>'
    assert upload(client, tenant_a, xxe).json()["status"] == "failed"
    assert upload(client, tenant_a, b"\x00\x01binary").status_code == 400
    assert upload(client, tenant_a, b"").status_code == 400
    assert upload(client, tenant_a, b"x" * (10 * 1024 * 1024 + 1)).status_code in {400, 413}


def test_choose_location_when_there_are_several(client, tenant_a):
    first = create_location(client, tenant_a, "One")
    second = create_location(client, tenant_a, "Two")
    beef = create_product(client, tenant_a, "Carne vita", sku="SKU-1", base_uom="KG")
    invoice = upload(client, tenant_a, ubl_invoice(lines=[("Carne vita", "1", "KGM", "40", "SKU-1")])).json()
    assert invoice["location_id"] is None and any("location" in b for b in invoice["blocking"])
    assert post(client, tenant_a, invoice["id"]).status_code == 400
    assert post(client, tenant_a, invoice["id"], location_id=second["id"]).status_code == 200
    assert stock(client, tenant_a, second, beef) == Decimal("1") and stock(client, tenant_a, first, beef) == Decimal("0")


def test_roles_tenant_isolation_and_download(client, tenant_a, tenant_b, employee_a, shop):
    xml = ubl_invoice()
    assert upload(client, employee_a, xml).status_code == 403
    invoice = upload(client, tenant_a, xml).json()
    assert len(client.get("/api/invoices", headers=employee_a["headers"]).json()) == 1       # employees can look
    assert post(client, employee_a, invoice["id"]).status_code == 403
    assert patch(client, employee_a, invoice["id"], document_number="X").status_code == 403
    for call in (
        client.get(f"/api/invoices/{invoice['id']}", headers=tenant_b["headers"]),
        client.get(f"/api/invoices/{invoice['id']}/file", headers=tenant_b["headers"]),
        client.post(f"/api/invoices/{invoice['id']}/reject", headers=tenant_b["headers"]),
    ):
        assert call.status_code == 404
    assert client.get("/api/invoices", headers=tenant_b["headers"]).json() == []
    other_location = create_location(client, tenant_b, "B")
    assert upload(client, tenant_a, xml.replace(b"FCT-100", b"FCT-101"), location_id=other_location["id"]).status_code == 404
    downloaded = client.get(f"/api/invoices/{invoice['id']}/file", headers=tenant_a["headers"])
    assert downloaded.content == xml and "attachment" in downloaded.headers["content-disposition"]
    # the same file may be imported by another company
    assert upload(client, tenant_b, xml).status_code == 201


def test_list_filter_and_pagination(client, tenant_a, shop):
    for n in range(3):
        upload(client, tenant_a, ubl_invoice(number=f"N{n}"))
    rows = client.get("/api/invoices", headers=tenant_a["headers"], params={"limit": 2})
    assert len(rows.json()) == 2 and rows.headers["X-Total-Count"] == "3"
    assert client.get("/api/invoices", headers=tenant_a["headers"], params={"status": "posted"}).json() == []


def test_posting_a_draft_twice_is_rejected_and_stock_is_not_doubled(client, tenant_a, shop):
    location, beef, salt = shop
    invoice = upload(client, tenant_a, ubl_invoice()).json()
    assert post(client, tenant_a, invoice["id"]).status_code == 200
    assert post(client, tenant_a, invoice["id"]).status_code == 409
    assert stock(client, tenant_a, location, beef) == Decimal("10")


# ---- automatic posting
def enable_auto(client, tenant, location=None):
    body = {"auto_post": True}
    if location:
        body["default_location_id"] = location["id"]
    assert client.patch("/api/invoices/inbox", headers=tenant["headers"], json=body).status_code == 200


def test_auto_post_only_when_everything_is_known_and_adds_up(client, tenant_a, shop):
    location, beef, salt = shop
    enable_auto(client, tenant_a)
    first = upload(client, tenant_a, ubl_invoice(number="F1")).json()
    assert first["status"] == "posted"                                      # SKU/name matches, new supplier is fine
    assert stock(client, tenant_a, location, beef) == Decimal("10")

    unknown = upload(client, tenant_a, ubl_invoice(number="F2", lines=[("Produs nou", "1", "H87", "5", "NEW")])).json()
    assert unknown["status"] == "draft"                                     # needs a person

    mismatch = upload(client, tenant_a, ubl_invoice(number="F3", total_net="1.00", total_gross="1.09")).json()
    assert mismatch["status"] == "draft" and any("net total" in w for w in mismatch["warnings"])
    assert stock(client, tenant_a, location, beef) == Decimal("10")


def test_auto_post_failure_leaves_a_draft_with_the_reason(client, tenant_a, shop):
    location, beef, salt = shop
    enable_auto(client, tenant_a)
    upload(client, tenant_a, ubl_invoice(number="DUP"))
    again = upload(client, tenant_a, ubl_invoice(number="DUP", lines=[("Carne vita", "11", "KGM", "42.50", "SKU-1")])).json()
    assert again["status"] == "draft"
    assert any("Automatic posting failed" in w or "already posted" in w for w in again["warnings"])
    assert stock(client, tenant_a, location, beef) == Decimal("10")


def test_auto_post_is_off_by_default_and_owner_only(client, tenant_a, manager_a, shop):
    assert upload(client, tenant_a, ubl_invoice()).json()["status"] == "draft"
    assert client.patch("/api/invoices/inbox", headers=manager_a["headers"], json={"auto_post": True}).status_code == 403
    assert client.post("/api/invoices/inbox/token", headers=manager_a["headers"]).status_code == 403


def test_waiting_and_unreadable_invoices_raise_alerts(client, tenant_a, shop):
    assert client.get("/api/alerts", headers=tenant_a["headers"]).json() == []
    upload(client, tenant_a, ubl_invoice())
    upload(client, tenant_a, b"<Invoice><broken>")
    kinds = {a["type"]: a for a in client.get("/api/alerts", headers=tenant_a["headers"]).json()}
    assert kinds["invoices_waiting"]["severity"] == "warning" and "1 supplier invoice" in kinds["invoices_waiting"]["message"]
    assert kinds["invoices_unreadable"]["severity"] == "info"
    draft = [i for i in client.get("/api/invoices", headers=tenant_a["headers"]).json() if i["status"] == "draft"][0]
    post(client, tenant_a, draft["id"])
    assert "invoices_waiting" not in {a["type"] for a in client.get("/api/alerts", headers=tenant_a["headers"]).json()}
