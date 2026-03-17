"""
Parse LexisNexis Uni RTF exports into a structured SQLite database + CSV.

Handles:
- Multiple ZIP files with RTF articles
- French accented characters (CBC Radio-Canada)
- Metadata extraction: headline, source, date, section, word count, body
- Deduplication by headline
- Incremental: can re-run as new ZIPs are added

Usage:
    uv run python scripts/parse_lexis.py
"""

import zipfile
import os
import re
import sqlite3
import subprocess
import tempfile
import hashlib
import csv
from datetime import datetime
from pathlib import Path

DATA_DIR = Path("data/lexis_uni")
DB_PATH = Path("data/lexis_articles.db")
CSV_PATH = Path("data/lexis_articles.csv")


def rtf_to_text(rtf_bytes: bytes) -> str:
    """Convert RTF bytes to plain text using macOS textutil."""
    with tempfile.NamedTemporaryFile(suffix=".rtf", delete=False) as f:
        f.write(rtf_bytes)
        f.flush()
        try:
            result = subprocess.run(
                ["textutil", "-convert", "txt", "-stdout", f.name],
                capture_output=True, timeout=10
            )
            return result.stdout.decode("utf-8", errors="replace")
        finally:
            os.unlink(f.name)


def parse_article(text: str) -> dict | None:
    """Parse a LexisNexis article from plain text into structured fields."""
    lines = text.strip().split("\n")
    # Strip leading blank lines
    while lines and not lines[0].strip():
        lines.pop(0)

    if len(lines) < 4:
        return None

    headline = lines[0].strip()
    source = lines[1].strip() if len(lines) > 1 else ""
    date_line = lines[2].strip() if len(lines) > 2 else ""

    # Parse date — multiple formats:
    #   CBC:          "February 19, 2026 Thursday 10:41 PM EST"
    #   Star/Gazette: "February 27, 2026 Friday"
    #   Radio-Canada: "jeudi 26 février 2026 9:00 AM EST"
    date_parsed = None
    fr_months = {
        "janvier": "January", "février": "February", "mars": "March",
        "avril": "April", "mai": "May", "juin": "June",
        "juillet": "July", "août": "August", "septembre": "September",
        "octobre": "October", "novembre": "November", "décembre": "December"
    }

    # Try English format: "Month DD, YYYY DayOfWeek ..."
    date_match = re.match(r"(\w+ \d{1,2}, \d{4})", date_line)
    if date_match:
        try:
            date_parsed = datetime.strptime(date_match.group(1), "%B %d, %Y").strftime("%Y-%m-%d")
        except ValueError:
            pass

    # Try French format: "dayname DD monthname YYYY ..."
    if not date_parsed:
        d = date_line.lower()
        for fr, en in fr_months.items():
            d = d.replace(fr, en)
        dm = re.match(r"\w+\s+(\d{1,2})\s+(\w+)\s+(\d{4})", d)
        if dm:
            try:
                date_parsed = datetime.strptime(
                    f"{dm.group(1)} {dm.group(2)} {dm.group(3)}", "%d %B %Y"
                ).strftime("%Y-%m-%d")
            except ValueError:
                pass

    # Extract section
    section = ""
    section_match = re.search(r"Section:\s*(.+)", text)
    if section_match:
        section = section_match.group(1).strip()

    # Extract word count
    word_count = None
    length_match = re.search(r"Length:\s*(\d+)\s*words", text)
    if length_match:
        word_count = int(length_match.group(1))

    # Extract body — between "Body" marker and "Load-Date:" or "End of Document"
    body = ""
    body_match = re.search(r"\bBody\b\s*\n(.*?)(?:Load-Date:|End of Document)", text, re.DOTALL)
    if body_match:
        body = body_match.group(1).strip()
    else:
        # Fallback: everything after the metadata block
        meta_end = text.find("Length:")
        if meta_end > 0:
            rest = text[meta_end:]
            nl = rest.find("\n")
            if nl > 0:
                body = rest[nl:].strip()
                # Remove trailing markers
                for marker in ["Load-Date:", "End of Document"]:
                    idx = body.find(marker)
                    if idx > 0:
                        body = body[:idx].strip()

    # Extract load date
    load_date = ""
    ld_match = re.search(r"Load-Date:\s*(.+)", text)
    if ld_match:
        try:
            load_date = datetime.strptime(
                ld_match.group(1).strip(), "%B %d, %Y"
            ).strftime("%Y-%m-%d")
        except ValueError:
            load_date = ld_match.group(1).strip()

    # Language detection (simple heuristic)
    language = "fr" if source.startswith("Radio-Canada") or re.search(r"[àâéèêëïîôùûüç]", headline) else "en"

    return {
        "headline": headline,
        "source": source,
        "date": date_parsed or "",
        "date_raw": date_line,
        "section": section,
        "word_count": word_count,
        "body": body,
        "load_date": load_date,
        "language": language,
        "content_hash": hashlib.md5(body.encode()).hexdigest() if body else "",
    }


def init_db(db_path: Path) -> sqlite3.Connection:
    """Create the SQLite database and articles table."""
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            headline TEXT NOT NULL,
            source TEXT,
            date TEXT,
            date_raw TEXT,
            section TEXT,
            word_count INTEGER,
            body TEXT,
            load_date TEXT,
            language TEXT,
            content_hash TEXT UNIQUE,
            zip_file TEXT,
            filename TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_articles_source ON articles(source)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_articles_date ON articles(date)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_articles_language ON articles(language)
    """)
    conn.commit()
    return conn


def split_multi_article_text(text: str) -> list[str]:
    """Split a concatenated Lexis RTF (multiple articles in one file) into individual article texts.

    Splits on 'End of Document' markers. Strips the Lexis metadata header
    (User Name, Date and Time, Job Number, Documents, etc.) from the first chunk.
    """
    chunks = re.split(r"End of Document", text)
    articles = []
    for i, chunk in enumerate(chunks):
        chunk = chunk.strip()
        if not chunk:
            continue
        # First chunk may have the Lexis header — strip lines before first article
        if i == 0:
            lines = chunk.split("\n")
            # Find where the header ends: look for first line that looks like a headline
            # (not a metadata key like "User Name:", "Job Number:", "Documents", etc.)
            header_patterns = [
                r"^User Name:", r"^Date and Time:", r"^Job Number:",
                r"^Documents\b", r"^Client/Matter:", r"^Search Terms:",
                r"^Search Type:", r"^Content Type", r"^Narrowed by",
                r"^Sources:", r"^news$", r"^\d+\.\s",
            ]
            body_start = 0
            for j, line in enumerate(lines):
                stripped = line.strip()
                if not stripped:
                    continue
                is_header = any(re.match(p, stripped) for p in header_patterns)
                if not is_header:
                    body_start = j
                    break
            chunk = "\n".join(lines[body_start:]).strip()

        if chunk and len(chunk) > 50:
            articles.append(chunk)
    return articles


def insert_article(conn: sqlite3.Connection, article: dict, zpath_name: str, filename: str, stats: dict):
    """Insert a parsed article into the database, updating stats."""
    if not article or not article["body"]:
        stats["errors"] += 1
        return
    try:
        conn.execute("""
            INSERT INTO articles
            (headline, source, date, date_raw, section, word_count,
             body, load_date, language, content_hash, zip_file, filename)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            article["headline"], article["source"], article["date"],
            article["date_raw"], article["section"], article["word_count"],
            article["body"], article["load_date"], article["language"],
            article["content_hash"], zpath_name, filename,
        ))
        stats["inserted"] += 1
    except sqlite3.IntegrityError:
        stats["skipped_dup"] += 1


def process_zips(data_dir: Path, conn: sqlite3.Connection) -> dict:
    """Process all ZIP files and insert articles into the database."""
    stats = {"total": 0, "inserted": 0, "skipped_dup": 0, "skipped_doclist": 0, "errors": 0}

    zips = sorted(list(data_dir.glob("*.ZIP")) + list(data_dir.glob("*.zip")))
    print(f"Found {len(zips)} ZIP files")

    for zpath in zips:
        print(f"\nProcessing: {zpath.name}")
        zf = zipfile.ZipFile(zpath)
        rtf_names = [n for n in zf.namelist() if n.endswith(".RTF") or n.endswith(".rtf")]

        for name in rtf_names:
            stats["total"] += 1

            # Skip doclist files
            if "doclist" in name.lower():
                stats["skipped_doclist"] += 1
                continue

            try:
                rtf_bytes = zf.read(name)
                text = rtf_to_text(rtf_bytes)

                # Check if this is a multi-article file (contains "End of Document" markers)
                eod_count = text.count("End of Document")
                if eod_count > 1:
                    # Multi-article RTF — split and parse each
                    article_texts = split_multi_article_text(text)
                    print(f"  Multi-article RTF: {name} ({eod_count} articles found, {len(article_texts)} parsed)")
                    for idx, art_text in enumerate(article_texts):
                        stats["total"] += 1
                        article = parse_article(art_text)
                        insert_article(conn, article, zpath.name, f"{name}#{idx+1}", stats)
                    stats["total"] -= 1  # compensate for the outer count
                else:
                    # Single-article RTF
                    article = parse_article(text)
                    insert_article(conn, article, zpath.name, name, stats)

            except Exception as e:
                stats["errors"] += 1
                print(f"  ERROR: {name}: {e}")

        conn.commit()
        print(f"  Processed {len(rtf_names)} files from {zpath.name}")

    return stats


def export_csv(conn: sqlite3.Connection, csv_path: Path):
    """Export articles to CSV (without body text for quick inspection)."""
    cursor = conn.execute("""
        SELECT id, headline, source, date, section, word_count,
               language, load_date, filename
        FROM articles ORDER BY date, source, headline
    """)
    rows = cursor.fetchall()
    cols = [d[0] for d in cursor.description]

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(cols)
        writer.writerows(rows)

    print(f"\nExported {len(rows)} articles to {csv_path}")


def print_summary(conn: sqlite3.Connection):
    """Print a summary of the database contents."""
    print("\n" + "=" * 60)
    print("DATABASE SUMMARY")
    print("=" * 60)

    total = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
    print(f"Total articles: {total}")

    print("\nBy source:")
    for row in conn.execute(
        "SELECT source, COUNT(*) as n FROM articles GROUP BY source ORDER BY n DESC"
    ):
        print(f"  {row[0]}: {row[1]}")

    print("\nBy language:")
    for row in conn.execute(
        "SELECT language, COUNT(*) as n FROM articles GROUP BY language ORDER BY n DESC"
    ):
        print(f"  {row[0]}: {row[1]}")

    print("\nDate range:")
    row = conn.execute(
        "SELECT MIN(date), MAX(date) FROM articles WHERE date != ''"
    ).fetchone()
    print(f"  {row[0]} to {row[1]}")

    print("\nBy date (top 10):")
    for row in conn.execute(
        "SELECT date, COUNT(*) as n FROM articles WHERE date != '' GROUP BY date ORDER BY n DESC LIMIT 10"
    ):
        print(f"  {row[0]}: {row[1]}")


if __name__ == "__main__":
    os.chdir(Path(__file__).parent.parent)

    print("Initializing database...")
    conn = init_db(DB_PATH)

    # Clear existing data for clean re-run
    conn.execute("DELETE FROM articles")
    conn.commit()

    stats = process_zips(DATA_DIR, conn)

    print(f"\n--- Processing Stats ---")
    print(f"Total RTF files: {stats['total']}")
    print(f"Inserted: {stats['inserted']}")
    print(f"Duplicates skipped: {stats['skipped_dup']}")
    print(f"Doclists skipped: {stats['skipped_doclist']}")
    print(f"Errors: {stats['errors']}")

    export_csv(conn, CSV_PATH)
    print_summary(conn)
    conn.close()
