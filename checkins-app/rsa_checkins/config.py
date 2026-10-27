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

# The header of "Updates Template.csv", in its order: the check-in import file has every one of these.
TEMPLATE_COLUMNS = [
    "Handle", "Title", "Body (HTML)", "Vendor", "Product Category", "Type", "Tags", "Published",
    "Option1 Name", "Option1 Value", "Option1 Linked To", "Option2 Name", "Option2 Value",
    "Option2 Linked To", "Option3 Name", "Option3 Value", "Option3 Linked To", "Variant SKU", "Variant Grams",
    "Variant Inventory Tracker", "Variant Inventory Qty", "Variant Inventory Policy",
    "Variant Fulfillment Service", "Variant Price", "Variant Compare At Price", "Variant Requires Shipping",
    "Variant Taxable", "Unit Price Total Measure", "Unit Price Total Measure Unit", "Unit Price Base Measure",
    "Unit Price Base Measure Unit", "Variant Barcodes", "Image Src", "Image Position", "Image Alt Text",
    "Gift Card", "SEO Title", "SEO Description", "Google Shopping / Google Product Category",
    "Google Shopping / Gender", "Google Shopping / Age Group", "Google Shopping / MPN",
    "Google Shopping / Condition", "Google Shopping / Custom Product", "Google Shopping / Custom Label 0",
    "Google Shopping / Custom Label 1", "Google Shopping / Custom Label 2",
    "Google Shopping / Custom Label 3", "Google Shopping / Custom Label 4",
    "Authenticity (product.metafields.custom.authenticity)",
    "Badge First (product.metafields.custom.badge_first)",
    "Badge Second (product.metafields.custom.badge_second)", "League (product.metafields.custom.league)",
    "Player (product.metafields.custom.player)",
    "Sales last 30 days (product.metafields.custom.sales_last_30_days)",
    "Sport (product.metafields.custom.sport)", "Team (product.metafields.custom.team)",
    "Text (product.metafields.custom.text)", "Wholesale Price (product.metafields.custom.wholesale_price)",
    "Google: Custom Product (product.metafields.mm-google-shopping.custom_product)",
    "Product rating count (product.metafields.reviews.rating_count)",
    "Autograph type (product.metafields.shopify.autograph-type)",
    "Card attributes (product.metafields.shopify.card-attributes)",
    "Condition (product.metafields.shopify.condition)", "Medium (product.metafields.shopify.medium)",
    "Signature placement (product.metafields.shopify.signature-placement)",
    "Sports logo (product.metafields.shopify.sports-logo)",
    "Sports theme (product.metafields.shopify.sports-theme)",
    "Trading card packaging (product.metafields.shopify.trading-card-packaging)",
    "Complementary products (product.metafields.shopify--discovery--product_recommendation.complementary_products)",
    "Related products (product.metafields.shopify--discovery--product_recommendation.related_products)",
    "Related products settings (product.metafields.shopify--discovery--product_recommendation.related_products_display)",
    "Search product boosts (product.metafields.shopify--discovery--product_search_boost.queries)",
    "Variant Image", "Variant Weight Unit", "Variant Tax Code", "Cost per item", "Included / United States",
    "Price / United States", "Compare At Price / United States", "Included / International",
    "Price / International", "Compare At Price / International", "Status", "Variant Packed Length",
    "Variant Packed Width", "Variant Packed Height", "Variant Packed Dimension Unit",
]

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
