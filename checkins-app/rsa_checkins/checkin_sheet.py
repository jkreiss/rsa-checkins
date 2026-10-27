"""Reads the check-in workbook ("Football checkin sheet.xlsx") into plain rows.

Each tab has its own headers, so columns are found by header name and turned
into meanings (first, last, cert, style, ...). Formula cells give the value
Excel last calculated; spreadsheet errors such as #REF! count as blank.
"""
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import openpyxl

TABS = ("jerseys", "fs-helm", "minis", "fb-balls")

MEANINGS = ("date", "sport", "league", "product", "jersey_type", "rep_auth", "model", "style", "inv",
            "first", "last", "city", "mascot", "color", "inscription", "player_type", "cert", "bag",
            "sku", "upc", "weight", "cost", "price", "compare", "ws")

_COMMON = {"date": "date", "sport": "sport", "league": "league", "product": "product", "model": "model",
           "inv": "inv", "first-name": "first", "last-name": "last", "team": "city", "mascot": "mascot",
           "color": "color", "inscription": "inscription", "player-type": "player_type", "cert": "cert",
           "green/gold": "bag", "sku": "sku", "upc": "upc", "weight": "weight", "cost": "cost",
           "price": "price", "compare": "compare", "ws": "ws", "ws price": "ws"}
HEADER_MEANINGS = {
    "jerseys": {**_COMMON, "type": "jersey_type"},
    "fs-helm": {**_COMMON, "rep/auth": "rep_auth", "type": "style"},
    "minis": {**_COMMON, "category1": "league", "type": "style"},
    "fb-balls": {**_COMMON, "category1": "league", "type": "style"},
}
REQUIRED_HEADERS = ("first-name", "last-name", "cert")
# A row with all of these blank ends a tab's entries (rows under it only carry formula defaults).
_ENTRY_FIELDS = ("first", "last", "cert", "inv", "price")
ERROR_VALUES = {"#REF!", "#NAME?", "#N/A", "#VALUE!", "#DIV/0!", "#NUM!", "#NULL!"}


class CheckinFormatError(ValueError):
    pass


@dataclass
class RawRow:
    tab: str
    row: int
    values: dict[str, str]


@dataclass
class SheetRead:
    rows: list[RawRow] = field(default_factory=list)
    ignored_tabs: list[str] = field(default_factory=list)


def cell_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else str(round(value, 6))
    if isinstance(value, (datetime, date)):
        return value.strftime("%Y-%m-%d")
    text = str(value).strip()
    return "" if text.upper() in ERROR_VALUES else text


def _read_tab(ws, tab: str) -> list[RawRow]:
    rows = ws.iter_rows(values_only=True)
    header = [cell_text(h).lower() for h in next(rows, ())]
    missing = [h for h in REQUIRED_HEADERS if h not in header]
    if missing:
        raise CheckinFormatError(f"The {tab} tab is missing the column(s): {', '.join(missing)}.")
    meanings = HEADER_MEANINGS[tab]
    columns = {}  # meaning -> column index (first matching header wins)
    for i, h in enumerate(header):
        if h in meanings and meanings[h] not in columns:
            columns[meanings[h]] = i
    out = []
    for number, cells in enumerate(rows, start=2):
        values = {m: "" for m in MEANINGS}
        for meaning, i in columns.items():
            values[meaning] = cell_text(cells[i]) if i < len(cells) else ""
        if not any(values[f] for f in _ENTRY_FIELDS):
            break
        if values["ws"].lower() == "x" or values["date"].lower() == "sample":
            continue
        out.append(RawRow(tab, number, values))
    return out


def read_workbook(path: Path | str) -> SheetRead:
    try:
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    except Exception as e:  # not an xlsx, or a damaged one
        raise CheckinFormatError(f"Couldn't open the workbook: {e}") from e
    try:
        by_name = {ws.title.strip().lower(): ws for ws in wb.worksheets}
        if not any(t in by_name for t in TABS):
            raise CheckinFormatError(
                f"This doesn't look like a check-in sheet: none of the tabs {', '.join(TABS)} were found.")
        read = SheetRead(ignored_tabs=[ws.title for ws in wb.worksheets if ws.title.strip().lower() not in TABS])
        for tab in TABS:
            if tab in by_name:
                read.rows.extend(_read_tab(by_name[tab], tab))
        return read
    finally:
        wb.close()
