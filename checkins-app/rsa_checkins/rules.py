"""
ALL DESCRIPTION WORDING LIVES HERE.

Edit this file to change how descriptions, SEO titles and the fixed
authentication/guarantee sentences read. Nothing else in the app contains
customer-facing wording.
"""

# Fixed sentence 2 for signed items (rotated per product). Verbatim from the original script.
SIGNED_GUARANTEES = [
    "and like every item we sell, is backed by our 100% money-back guarantee",
    "and is backed by the same 100% money-back guarantee we stand behind on every item",
    "and, as with everything in our store, comes with our 100% money-back guarantee",
]

# Fixed sentence 2 for unsigned items and sealed products (rotated per product).
UNSIGNED_SENTENCES = [
    "Like every item we sell, it is backed by our 100% money-back guarantee.",
    "It is backed by the same 100% money-back guarantee we stand behind on every item.",
    "As with everything in our store, it comes with our 100% money-back guarantee.",
]

# How authenticator names from titles are written.
AUTHENTICATOR_CASE = {"jsa": "JSA", "psa": "PSA", "beckett": "Beckett", "becket": "Beckett",
                      "fanatics": "Fanatics", "panini": "Panini"}

# The only values allowed in the Authenticity column.
AUTHENTICITY_VALUES = ("JSA", "Beckett", "Fanatics", "PSA", "Panini")

# Tag code -> sport. The Sport column holds the word ("BS" in the tags -> "Baseball").
SPORT_CODES = {"FB": "Football", "BS": "Baseball", "BK": "Basketball", "HK": "Hockey",
               "WR": "Wrestling", "SC": "Soccer"}

TITLE_PARSE_PROMPT = """You sort product listings for an autographed sports and entertainment memorabilia store.

You will get a JSON list of products (title, product type, tags). For EACH product return one result with the exact same title:

- kind:
  - "signed": the item is autographed by one or more people.
  - "unsigned_player": the item is not signed but is tied to a named person (e.g. "Jim Kelly ... Unsigned Nike Football Jersey").
  - "no_player": not tied to any person, e.g. sealed card boxes and packs.
- subjects: full, correctly spelled names of every signer (or, for unsigned_player, the person named).
  - Titles often use surnames only ("Atlanta Braves Greats Sheffield, Murphy, Jones, Justice") - use the team, sport and tags to give full names ("Gary Sheffield", "Dale Murphy", ...).
  - Write suffixes properly: "Odell Beckham Jr" -> "Odell Beckham Jr.".
  - Inscriptions, award years and words like "Dual", "Triple", "Multi", "Team" are not names.
  - Signed by a team, cast or group whose members the title doesn't name (e.g. "The Mighty Ducks Signed ... Jersey", "1957 Philadelphia Phillies Team Signed Baseball"): kind "signed" with empty subjects.
  - For no_player, give exactly one subject: the product line without box/pack words, e.g. "1981 Donruss Vintage Golf Stars".

Never guess wildly. If a name is genuinely unclear, give your best reading of the title as written."""

RESEARCH_PROMPT = """You research people (and occasionally sealed trading-card products) for an autographed sports and entertainment memorabilia store. The facts you save are used to write product descriptions, so they must be correct.

Use web search to verify facts. For a person: career highlights, awards, records, teams played for, current team if still active, and whether they are active or retired. For entertainers: notable roles and achievements. For a product line (kind "product_line"): release year, maker, notable cards or players in the set.

Rules:
- Save only facts you confirmed in search results, each with the URL of the page that confirms it.
- If something is uncertain or sources disagree, leave it out.
- 4 to 10 short, specific facts are ideal.
- status: "active" if still playing or performing, "retired" if not, "unknown" if you can't tell. Use "unknown" for product lines.

When you are done, call the save_research tool exactly once with everything you found."""
WRITE_PROMPT = """You write product descriptions for an autographed sports and entertainment memorabilia store.

You get JSON with:
- products: the items to write (handle, title, product type, tags, kind, authenticator, team).
- subjects: verified facts about the people (or product line) on these items. Use ONLY these facts for anything about careers, awards, records or history. If a fact you'd like isn't there, leave it out.
- previous_notes: notes already written for other items of the same people. Yours must be clearly different.

For EACH product return: handle (exactly as given), sentence1, call_to_action, note, seo_title.

sentence1 - one sentence:
- Signed items: "This [person] autographed [collectible term] is a [item description from the title], hand-signed by [short descriptor]." If the title has an inscription, quote it, e.g. inscribed "Who's Your Daddy?".
  - [collectible term] is a broad, high-search phrase, NOT the item type: "collectible", "memorabilia piece", or for athletes "sports collectible" / "sports memorabilia piece". Vary it between products.
  - The item type (jersey, football, helmet, photo...) appears only once, in the "is a ..." part.
  - Good: "This Kelvin Benjamin autographed collectible is a Florida State college red football jersey, hand-signed by the former Seminoles wide receiver."
  - Bad (item type twice): "This Kelvin Benjamin autographed football jersey is a Florida State college red football jersey, ..."
- Several signers: name all of them.
- Unsigned items (kind "unsigned_player" or "no_player"): describe the item plainly, naming the item type only once. Never say "autographed", "signed" or "hand-signed".
- Use only item details found in the title, product type or tags. No size or ink colour unless it's in the title.

call_to_action - one sentence aimed at fans, gift-givers and collectors. Warm, not corny. Vary the wording between products. Never write "serious collectors look for".

note - 2 to 3 sentences about the person's career (or the product line's history), tied to THIS item where possible: the team on the item, the inscription, college vs. pro. Every note must differ from the other notes in this batch and from previous_notes.

seo_title - at most 70 characters:
- Signed: "[Player] Autographed [team or place] [item] - [Authenticator] Authentication", e.g. "Ron Jaworski Autographed Philadelphia Jersey - JSA Authentication". Shorten the middle if needed, never the authenticator part.
- No authenticator given: leave off " - ... Authentication".
- Unsigned: no "Autographed" and no authentication part, e.g. "Jim Kelly Buffalo Bills Salute to Service Nike Jersey".

Never mention a certificate of authenticity or "COA" anywhere. Don't mention authentication or the guarantee in sentence1, call_to_action or note - the store adds that sentence itself."""

# Check-in sheet (Part 2): the same on every product, copied from the workbook's example rows.
CHECKIN_FIXED_VALUES = {
    "Vendor": "RSA",
    "Product Category": "Arts & Entertainment > Hobbies & Creative Arts > Collectibles > Autographs",
    "Published": "FALSE",
    "Option1 Name": "Title",
    "Option1 Value": "Default Title",
    "Variant Inventory Tracker": "shopify",
    "Variant Inventory Policy": "deny",
    "Variant Fulfillment Service": "manual",
    "Variant Requires Shipping": "TRUE",
    "Variant Taxable": "TRUE",
    "Gift Card": "FALSE",
    "Google Shopping / Google Product Category":
        "Arts & Entertainment > Hobbies & Creative Arts > Collectibles > Autographs",
    "Google Shopping / Condition": "New",
    "Variant Weight Unit": "oz",
    "Included / United States": "TRUE",
    "Included / International": "TRUE",
    "Status": "draft",
}

# Product Type per check-in tab. Tabs not listed get no Type (owner: "don't worry about type for now").
CHECKIN_TYPES = {"jerseys": "Autographed Football Jerseys"}
