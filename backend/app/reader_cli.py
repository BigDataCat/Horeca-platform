"""Read an invoice file from the command line and print the extraction as JSON (no server, no database).

    python -m app.reader_cli factura.pdf
"""

import json
import os
import sys

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://unused:unused@localhost/unused")

from app.services.invoice_parsing import InvoiceReadError, detect_kind  # noqa: E402
from app.services.invoice_reader import read_document_locally  # noqa: E402


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python -m app.reader_cli <invoice.pdf|photo.png>", file=sys.stderr)
        return 2
    with open(argv[1], "rb") as handle:
        content = handle.read()
    try:
        kind = detect_kind(content)
        if kind not in {"pdf", "image"}:
            raise InvoiceReadError("Only PDF and image files are read here; e-Factura XML is parsed by the API")
        invoice = read_document_locally(content, kind)
    except InvoiceReadError as exc:
        print(f"Could not read the document: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(json.loads(invoice.model_dump_json()), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
