"""
Ingest SimilarWeb screenshots → outlet_readership.csv

Usage (from project root):
    uv run python technical_brief/scripts/ingest_similarweb.py

Screenshots must be named <name>_monthly.png and placed in:
    technical_brief/data/similarweb/

The script reads each PNG via OCR (pytesseract), extracts the Monthly visits
figure, and writes/updates technical_brief/data/outlet_readership.csv.

To add a new outlet:
  1. Add its entry to OUTLET_MAP below (name -> domain, category)
  2. Screenshot SimilarWeb, save as <name>_monthly.png in the similarweb/ folder
  3. Re-run this script

Dependencies:
    uv pip install pytesseract pillow
    brew install tesseract
"""

import os
import re
import csv
from pathlib import Path
from datetime import date

# ── Configuration ──────────────────────────────────────────────────────────────

SCREENSHOT_DIR = Path("technical_brief/data/similarweb")
OUTPUT_CSV     = Path("technical_brief/data/outlet_readership.csv")
SOURCE         = "SimilarWeb"
SOURCE_DATE    = "2026-01"

# screenshot stem (without _monthly) -> (outlet name, domain, category)
OUTLET_MAP = {
    # Canadian (free)
    "cbc":            ("CBC News",           "cbc.ca",               "Canadian news (free)"),
    "ctvnews":        ("CTV News",           "ctvnews.ca",           "Canadian news (free)"),
    "radiocanada":    ("Radio-Canada",       "ici.radio-canada.ca",  "Canadian news (free)"),
    "globalnews":     ("Global News",        "globalnews.ca",        "Canadian news (free)"),
    "lapresse":       ("La Presse",          "lapresse.ca",          "Canadian news (free)"),
    "tsn":            ("TSN",                "tsn.ca",               "Canadian news (free)"),
    "sportsnet":      ("Sportsnet",          "sportsnet.ca",         "Canadian news (free)"),
    "canadianpress":  ("The Canadian Press", "thecanadianpress.com", "Canadian news (free)"),
    "cp24":           ("CP24",               "cp24.com",             "Canadian news (free)"),
    "citynews":       ("City News",          "citynews.ca",          "Canadian news (free)"),
    # Canadian (paywalled)
    "globeandmail":   ("The Globe and Mail", "theglobeandmail.com",  "Canadian news (paywalled)"),
    "nationalpost":   ("National Post",      "nationalpost.com",     "Canadian news (paywalled)"),
    "ledevoir":       ("Le Devoir",          "ledevoir.com",         "Canadian news (paywalled)"),
    "thestar":        ("Toronto Star",       "thestar.com",          "Canadian news (paywalled)"),
    "financialpost":  ("Financial Post",     "financialpost.com",    "Canadian news (paywalled)"),
    "bnnbloomberg":   ("BNN Bloomberg",      "bnnbloomberg.ca",      "Canadian news (paywalled)"),
    "edmontonjournal":("Edmonton Journal",   "edmontonjournal.com",  "Canadian news (paywalled)"),
    "calgaryherald":  ("Calgary Herald",     "calgaryherald.com",    "Canadian news (paywalled)"),
    "rebelnews":      ("Rebel News",         "rebelnews.com",        "Canadian news (paywalled)"),
    "ottawacitizen":  ("Ottawa Citizen",     "ottawacitizen.com",    "Canadian news (paywalled)"),
    "vancouversun":   ("Vancouver Sun",      "vancouversun.com",     "Canadian news (paywalled)"),
    "montrealgazette":("Montreal Gazette",   "montrealgazette.com",  "Canadian news (paywalled)"),
    "halifaxexaminer":("Halifax Examiner",   "halifaxexaminer.ca",   "Canadian news (paywalled)"),
    # International
    "reuters":        ("Reuters",            "reuters.com",          "International news"),
    "bbc":            ("BBC",                "bbc.com",              "International news"),
    "nytimes":        ("The New York Times", "nytimes.com",          "International news"),
    "espn":           ("ESPN",               "espn.com",             "International news"),
    "bloomberg":      ("Bloomberg",          "bloomberg.com",        "International news"),
    "foxnews":        ("Fox News",           "foxnews.com",          "International news"),
    "nhl":            ("NHL.com",            "nhl.com",              "International news"),
    "cnn":            ("CNN",                "cnn.com",              "International news"),
    "mlb":            ("MLB.com",            "mlb.com",              "International news"),
    "fifa":           ("FIFA",               "fifa.com",             "International news"),
    "wapo":           ("The Washington Post","washingtonpost.com",   "International news"),
    "aljazeera":      ("Al Jazeera",         "aljazeera.com",        "International news"),
    "atlantic":       ("The Atlantic",       "theatlantic.com",      "International news"),
    "guardian":       ("The Guardian",       "theguardian.com",      "International news"),
    "npr":            ("NPR",                "npr.org",              "International news"),
    "abcnews":        ("ABC News",           "abcnews.go.com",       "International news"),
}

# ── OCR ────────────────────────────────────────────────────────────────────────

def parse_visits(text: str) -> int | None:
    """Extract Monthly visits figure from SimilarWeb screenshot OCR text."""
    match = re.search(r'Monthly\s+visits[^0-9]*([\d.,]+)\s*([MKBmkb]?)', text, re.IGNORECASE)
    if not match:
        match = re.search(r'([\d,]+\.?\d*)\s*([MKBmkb])\b', text)
    if not match:
        return None
    num_str, suffix = match.group(1), match.group(2).upper()
    num = float(num_str.replace(',', ''))
    multiplier = {'M': 1_000_000, 'K': 1_000, 'B': 1_000_000_000}.get(suffix, 1)
    return int(round(num * multiplier))


def ocr_screenshot(path: Path) -> int | None:
    import pytesseract
    from PIL import Image
    text = pytesseract.image_to_string(Image.open(path))
    return parse_visits(text)


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    # Load existing rows keyed by domain
    existing = {}
    if OUTPUT_CSV.exists():
        with open(OUTPUT_CSV) as f:
            for row in csv.DictReader(f):
                existing[row["domain"]] = row

    screenshots = sorted(SCREENSHOT_DIR.glob("*_monthly*.png"))
    if not screenshots:
        print(f"No *_monthly*.png files found in {SCREENSHOT_DIR}")
        return

    skipped, failed = [], []

    for png in screenshots:
        # Strip _monthly and any trailing _2, _3 suffix
        key = re.sub(r'_monthly.*$', '', png.stem)

        entry = OUTLET_MAP.get(key)
        if not entry:
            print(f"  SKIP (no mapping): {png.name}  (key={key!r})")
            skipped.append(png.name)
            continue

        outlet, domain, category = entry

        try:
            visits = ocr_screenshot(png)
        except ImportError:
            print("pytesseract not installed. Run: uv pip install pytesseract pillow && brew install tesseract")
            return

        if visits is None:
            print(f"  OCR failed: {png.name}")
            failed.append(png.name)
            continue

        existing[domain] = {
            "outlet":         outlet,
            "domain":         domain,
            "monthly_visits": visits,
            "category":       category,
            "source":         SOURCE,
            "source_date":    SOURCE_DATE,
            "retrieved":      str(date.today()),
        }
        print(f"  {outlet:<30} {visits:>14,}  ({png.name})")

    # Write CSV sorted by category then outlet
    cat_order = {"Canadian news (free)": 0, "Canadian news (paywalled)": 1, "International news": 2}
    rows = sorted(existing.values(), key=lambda r: (cat_order.get(r["category"], 9), r["outlet"]))

    fieldnames = ["outlet", "domain", "monthly_visits", "category", "source", "source_date", "retrieved"]
    with open(OUTPUT_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nWrote {len(rows)} rows to {OUTPUT_CSV}")
    if skipped:
        print(f"Skipped (no mapping): {skipped}")
    if failed:
        print(f"OCR failed: {failed}")


if __name__ == "__main__":
    main()
