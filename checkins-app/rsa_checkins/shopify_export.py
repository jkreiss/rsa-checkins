"""Input adapter: a Shopify product export CSV."""
import csv
import sys
from dataclasses import dataclass
from pathlib import Path

REQUIRED_COLUMNS = ("Handle", "Title", "Body (HTML)", "Type", "Tags", "Status")
NEW_STYLE_MARKER = "tamper-evident authentication sticker"


class ExportFormatError(ValueError):
    pass


@dataclass(frozen=True)
class ExportProduct:
    handle: str
    title: str
    body_html: str
    product_type: str
    tags: str
    status: str
    first_row: dict[str, str]


def read_export(path: Path | str) -> tuple[list[str], list[ExportProduct]]:
    csv.field_size_limit(sys.maxsize)
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        header = next(reader, [])
        header = [h.strip() for h in header]
        missing = [c for c in REQUIRED_COLUMNS if c not in header]
        if missing:
            raise ExportFormatError(
                "This doesn't look like a Shopify product export. Missing columns: " + ", ".join(missing)
            )
        products: dict[str, ExportProduct] = {}
        for raw in reader:
            row = dict(zip(header, raw + [""] * (len(header) - len(raw))))
            handle = row["Handle"].strip()
            if not handle or handle in products or not row["Title"].strip():
                continue
            products[handle] = ExportProduct(
                handle=handle,
                title=row["Title"].strip(),
                body_html=row["Body (HTML)"],
                product_type=row["Type"].strip(),
                tags=row["Tags"].strip(),
                status=row["Status"].strip().lower(),
                first_row=row,
            )
    return header, list(products.values())


def needs_description(p: ExportProduct, include_drafts: bool) -> bool:
    if p.status == "active" or (p.status == "draft" and include_drafts):
        return NEW_STYLE_MARKER not in p.body_html
    return False
