"""Where data lives and the default settings."""
import os
from pathlib import Path

METAFIELD_AUTHENTICITY = "Authenticity (product.metafields.custom.authenticity)"
METAFIELD_LEAGUE = "League (product.metafields.custom.league)"
METAFIELD_PLAYER = "Player (product.metafields.custom.player)"
METAFIELD_SPORT = "Sport (product.metafields.custom.sport)"
METAFIELD_TEAM = "Team (product.metafields.custom.team)"
METAFIELD_COLUMNS = (METAFIELD_AUTHENTICITY, METAFIELD_LEAGUE, METAFIELD_PLAYER, METAFIELD_SPORT, METAFIELD_TEAM)

DEFAULT_OUTPUT_COLUMNS = ["Handle", "Title", "Body (HTML)", "SEO Title", *METAFIELD_COLUMNS]

DEFAULT_SETTINGS = {
    "model": "claude-sonnet-5-5",
    "refresh_days": 90,
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
