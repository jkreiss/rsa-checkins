"""Where data lives and the default settings."""
import os
from pathlib import Path

METAFIELD_AUTHENTICITY = "Authenticity (product.metafields.custom.authenticity)"
METAFIELD_LEAGUE = "League (product.metafields.custom.league)"
METAFIELD_PLAYER = "Player (product.metafields.custom.player)"
METAFIELD_SPORT = "Sport (product.metafields.custom.sport)"
METAFIELD_TEAM = "Team (product.metafields.custom.team)"
METAFIELD_COLUMNS = (METAFIELD_AUTHENTICITY, METAFIELD_LEAGUE, METAFIELD_PLAYER, METAFIELD_SPORT, METAFIELD_TEAM)
# Left empty for now (agents.md). Placed as in "Updates Template.csv": after the other custom metafields.
METAFIELD_WHOLESALE = "Wholesale Price (product.metafields.custom.wholesale_price)"

# Shopify rejects an import without these ("Product options input is required"). One-variant products use
# Option1 Name "Title" and Option1 Value "Default Title".
OPTION_COLUMNS = {"Option1 Name": "Title", "Option1 Value": "Default Title"}

DEFAULT_OUTPUT_COLUMNS = ["Handle", "Title", "Body (HTML)", *OPTION_COLUMNS, "SEO Title", *METAFIELD_COLUMNS, METAFIELD_WHOLESALE]

DEFAULT_SETTINGS = {
    "model": "claude-sonnet-5-5",
    "refresh_days": 30,            # active (and unknown) players: re-checked after about a month
    "retired_refresh_days": 180,   # retired players: re-checked after about 6 months
    "concurrency": 2,
    "output_columns": DEFAULT_OUTPUT_COLUMNS,
    "include_drafts": True,
}


def data_dir() -> Path:
    return Path(os.environ.get("CHECKINS_DATA_DIR", "./data"))


def db_path() -> Path:
    return data_dir() / "checkins.sqlite3"


def upload_dir() -> Path:
    return data_dir() / "uploads"
