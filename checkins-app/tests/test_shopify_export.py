import csv
from pathlib import Path

import pytest

from rsa_checkins.shopify_export import ExportFormatError, needs_description, read_export

FIX = Path(__file__).parent / "fixtures" / "export_small.csv"


def test_read_export_one_product_per_handle():
    header, products = read_export(FIX)
    assert len(header) == 87 and len(products) == 11
    box = next(p for p in products if p.handle == "1981-donruss-vintage-golf-stars-wax-box")
    assert box.title == "1981 Donruss Vintage Golf Stars Wax Box" and box.first_row["Handle"] == box.handle


def test_needs_description_rules():
    _, products = read_export(FIX)
    assert sum(needs_description(p, include_drafts=True) for p in products) == 10   # Mahomes Sr is new-style
    assert sum(needs_description(p, include_drafts=False) for p in products) == 7


def test_archived_products_are_skipped():
    _, products = read_export(FIX)
    p = products[0]
    archived = type(p)(**{**p.__dict__, "status": "archived"})
    assert not needs_description(archived, include_drafts=True)


def test_read_export_handles_bom(tmp_path):
    raw = FIX.read_text(encoding="utf-8")
    p = tmp_path / "excel.csv"
    p.write_bytes(("﻿" + raw.replace("\n", "\r\n")).encode("utf-8"))
    header, products = read_export(p)
    assert header[0] == "Handle" and len(products) == 11


def test_missing_columns_rejected(tmp_path):
    p = tmp_path / "bad.csv"
    p.write_text("Name,Price\nx,1\n")
    with pytest.raises(ExportFormatError, match="Handle"):
        read_export(p)


def test_columns_read_by_name(tmp_path):
    rows = list(csv.reader(FIX.open(encoding="utf-8", newline="")))
    order = list(reversed(range(len(rows[0]))))
    p = tmp_path / "reordered.csv"
    with p.open("w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows([[r[i] for i in order] for r in rows])
    assert {x.handle for x in read_export(p)[1]} == {x.handle for x in read_export(FIX)[1]}
