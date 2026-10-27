"""Builds a small check-in workbook shaped like "Football checkin sheet.xlsx"."""
from pathlib import Path

import openpyxl

# Headers copied from the real workbook (spelling and stray spaces included).
HEADERS = {
    "jerseys": ["sport", "league", "product", "type", "model", "inv", "first-name", "last-name", "team",
                "mascot", "color", "inscription", "desc", "player-type", "cert", "class", "Green/Gold",
                "sku", "upc", "weight", "cost", "price", "compare", "WS", "Tag"],
    "fs-helm": ["date", "sport", "league", "product", "rep/auth", "model", "type", "inv", "first-name",
                "last-name", "team", "mascot", "color", "inscription", "desc", "player-type", "cert", "class",
                "Green/Gold", "sku", "upc", "weight", "cost", "price", "compare", "WS ", "Tag"],
    "minis": ["date", "sport", "category1", "category2", "category3", "product", "type", "inv", "first-name",
              "last-name", "team", "mascot", "color", "inscription", "desc", "player-type", "cert", "class",
              "Green/Gold", "sku", "upc", "weight", "cost", "price", "compare", "WS price", "Tag"],
    "fb-balls": ["date", "sport", "category1", "category2", "category3", "product", "type", "inv",
                 "first-name", "last-name", "team", "mascot", "color", "inscription", "desc", "player-type",
                 "cert", "green/gold", "class", "sku", "upc", "weight", "cost", "price", "compare", "Ws ", "Tag"],
}

_JERSEY = {"sport": "Football", "league": "NFL", "product": "Jersey", "type": "Custom", "weight": 32,
           "class": "Witnessed"}
ROWS = {
    "jerseys": [
        {**_JERSEY, "sport": "Hockey", "league": "NHL", "inv": 10, "first-name": "Philipp",
         "last-name": "Grubauer", "team": "Washington", "mascot": "#NAME?", "color": "White",
         "cert": "Beckett", "cost": 1, "price": 2, "compare": 4, "WS": "x"},
        {**_JERSEY, "type": "Authentic", "model": "Mitchell & Ness", "inv": 15, "first-name": "Keenan",
         "last-name": "Allen", "team": "Indianapolis", "mascot": "Colts", "color": "White",
         "player-type": "Current", "cert": "JSA", "Green/Gold": "Green Bag", "cost": 150,
         "price": "$349.99", "compare": 400, "WS": 200},
        {**_JERSEY, "model": "Throwback", "inv": 80, "first-name": "Keenan", "last-name": "Allen",
         "team": "Indianapolis", "mascot": "Colts", "color": "Blue", "player-type": "Current", "cert": "JSA"},
        {**_JERSEY, "inv": 5, "first-name": "Anthony", "last-name": "Munoz", "team": "Cincinnati",
         "mascot": "Bengals", "color": "Black", "inscription": "HOF 98", "player-type": "HOF", "cert": "JSA"},
        {**_JERSEY, "league": "NCAA", "inv": 9, "first-name": "Alvin", "last-name": "Kamara",
         "team": "Tennessee", "mascot": "Volunteers", "color": "Black", "cert": "Beckett"},
        {**_JERSEY, "inv": 8, "first-name": "Ron", "last-name": "Jaworski", "team": "Philadelphia",
         "mascot": "#REF!", "color": "Green", "cert": "JSA"},
    ],
    "fs-helm": [
        {"date": "sample", "sport": "Football", "league": "NFL", "product": "Full-Size Helmets",
         "rep/auth": "Authentic", "inv": 60, "first-name": "Sam", "last-name": "Sample", "cert": "JSA",
         "WS ": "x"},
        {"sport": "Football", "league": "NFL", "product": "Full-Size Helmets", "rep/auth": "Authentic",
         "model": "Speedflex", "type": "Eclipse", "inv": 1, "first-name": "Bob", "last-name": "Griese",
         "team": "Miami", "mascot": "Dolphins", "color": "Black", "player-type": "HOF", "cert": "JSA",
         "weight": 128},
    ],
    "minis": [
        {"date": "sample", "sport": "Football", "category1": "NFL", "product": "Mini Helmets", "inv": 60,
         "first-name": "Sam", "last-name": "Sample", "cert": "JSA"},
        {"sport": "Football", "category1": "NFL", "product": "Mini Helmets", "type": "Throwback Gold",
         "inv": 1, "first-name": "Terry", "last-name": "Bradshaw", "team": "Pittsburgh", "mascot": "Steelers",
         "color": "Yellow", "cert": "Beckett", "weight": 32, "cost": 95, "price": 199.99, "compare": 250},
        {"sport": "Football", "category1": "NFL", "product": "Mini Helmets", "type": "Speed", "inv": 24,
         "first-name": "LeGarrette", "last-name": "Blount ", "team": "Tampa Bay", "mascot": "#NAME?",
         "color": "Brown", "cert": "JSA", "weight": 32, "cost": 34, "price": 69.98999999999999,
         "compare": 120, "WS price": 54},
    ],
    "fb-balls": [
        {"date": "sample", "sport": "Football", "category1": "NFL", "product": "Footballs", "type": "Logo",
         "inv": 48, "first-name": "Maxx", "last-name": "Crosby", "team": "Oakland", "mascot": "Raiders",
         "cert": "JSA", "green/gold": "Gold Bag", "Ws ": "x"},
        {"sport": "Football", "category1": "NCAA", "product": "Footballs", "type": "Logo", "inv": 3,
         "first-name": "Devonta", "last-name": "Smith", "team": "Alabama", "mascot": "Crimson Tide",
         "cert": "Beckett", "weight": 32, "cost": 52, "price": 199.99, "compare": 250},
        {"sport": "Football", "category1": "NFL", "product": "Footballs", "type": "The Duke", "inv": 1,
         "first-name": "Jason", "last-name": "Kelce", "team": "Philadelphia", "mascot": "Eagles",
         "cert": "JSA", "weight": 32, "cost": 141, "price": 299.99, "compare": 350, "Ws ": 180},
    ],
}


def make_workbook(path: Path, extra: dict[str, list[dict]] | None = None) -> Path:
    """Write the four tabs: header, entry rows (+ extra), a blank row, then an example block."""
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for tab, headers in HEADERS.items():
        ws = wb.create_sheet(tab)
        ws.append(headers)
        for row in ROWS[tab] + (extra or {}).get(tab, []):
            ws.append([row.get(h) for h in headers])
        ws.append([])
        ws.append([None, "Title", "Body (HTML)", "Vendor"])
        ws.append([None, "Example Title - JSA", "SCRIPT", "RSA", "x", "y", "z", "Jersey", "Example", "Name"])
    wb.save(path)
    return Path(path)
