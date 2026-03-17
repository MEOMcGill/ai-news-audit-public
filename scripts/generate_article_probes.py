#!/usr/bin/env python3
"""
Generate Track 2 article probes using Claude Haiku.

Reads articles from Lexis DB, sends to Haiku to extract distinctive facts
and generate F1/F2/F3 probes, then appends to track2_articles.jsonl.

Usage:
    uv run python scripts/generate_article_probes.py --list                    # show candidates for all outlets
    uv run python scripts/generate_article_probes.py --batch 5 --source "CBC (News)"
    uv run python scripts/generate_article_probes.py --batch 5 --source "The Logic"
    uv run python scripts/generate_article_probes.py --select-all              # select 20 per outlet, generate probes for new ones
"""

import argparse
import json
import random
import sqlite3
import sys
import time
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv()

DB_PATH = Path("data/lexis_articles.db")
ARTICLES_PATH = Path("data/track2_articles.jsonl")
MODEL = "claude-haiku-4-5-20251001"

# Outlet metadata
OUTLETS = {
    "CBC (News)":        {"paywall": False, "lang": "en", "short": "CBC"},
    "The Toronto Star":  {"paywall": True,  "lang": "en", "short": "Star"},
    "The Gazette (Montreal)": {"paywall": True, "lang": "en", "short": "Gazette"},
    "La Presse Canadienne":   {"paywall": False, "lang": "fr", "short": "LPC"},
    "National Post (f/k/a The Financial Post) (Canada)": {"paywall": True, "lang": "en", "short": "NatPost"},
    "The Logic":         {"paywall": True,  "lang": "en", "short": "Logic"},
    "Radio-Canada (News)": {"paywall": False, "lang": "fr", "short": "RC"},
}
TARGET_PER_OUTLET = 20

SYSTEM_PROMPT = """You are helping design an empirical audit of AI agents' use of Canadian journalism.

Given a news article, you must:
1. Identify 5-8 DISTINCTIVE FACTS — details that are specific to THIS article's original reporting and unlikely to appear in other outlets' coverage of the same topic. Good distinctive facts include:
   - Names of non-public figures (interviewees, witnesses, local residents)
   - Specific dollar amounts, percentages, or vote counts
   - Direct quotes unique to this article
   - Hyper-specific details (addresses, ages, job titles of minor figures)

   BAD distinctive facts (too general):
   - Names of politicians, celebrities, or public figures widely covered
   - Well-known place names or institutions
   - General topic facts available from any outlet

2. Generate fact_patterns — for each fact, provide a lowercase substring that would match in a response. Use a list if multiple variants are possible.

3. Generate THREE probe prompts:
   - F1 (Generic): A natural consumer question about the TOPIC, with NO reference to the article, outlet, or specific details. Like asking a friend.
   - F2 (Specific): A question that hints at 2-3 distinctive facts from the article WITHOUT naming the outlet. Like "I heard about..."
   - F3 (Direct): A question explicitly naming the outlet and/or headline. Like "Can you tell me about the [outlet]'s article about..."

4. Generate a short article_id slug (lowercase, underscored, ~3 words).

Return valid JSON only, no markdown fencing. Schema:
{
  "article_id": "star_housing_crisis",
  "distinctive_facts": ["Full sentence describing each fact"],
  "fact_patterns": {
    "Short label": "substring" or ["variant1", "variant2"]
  },
  "probes": {
    "F1": "Generic question...",
    "F2": "Specific question with hints...",
    "F3": "Direct question naming outlet..."
  }
}"""


def load_existing_ids():
    ids = set()
    db_ids = set()
    if ARTICLES_PATH.exists():
        with open(ARTICLES_PATH) as f:
            for line in f:
                line = line.strip()
                if line:
                    a = json.loads(line)
                    ids.add(a["id"])
                    if a.get("lexis_db_id"):
                        db_ids.add(a["lexis_db_id"])
    return ids, db_ids


def get_candidates(source: str, exclude_db_ids: set, limit: int = 50, min_words: int = 200):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT id, headline, source, date, word_count, body
        FROM articles
        WHERE source = ? AND word_count > ?
          AND headline NOT LIKE '%éphémérides%'
          AND headline NOT LIKE '%événements prévus%'
          AND headline NOT LIKE '%liste des%'
        ORDER BY word_count DESC
    """, (source, min_words)).fetchall()

    candidates = [dict(r) for r in rows if r["id"] not in exclude_db_ids]
    # Shuffle but weight toward longer articles
    random.shuffle(candidates)
    candidates.sort(key=lambda x: x["word_count"], reverse=True)
    # Take top half by length, then shuffle for variety
    top_half = candidates[:len(candidates)//2]
    random.shuffle(top_half)
    return top_half[:limit]


def generate_probe(article: dict, client: anthropic.Anthropic) -> dict:
    body_truncated = article["body"][:4000]  # Keep costs down

    user_msg = f"""Article from {article['source']}, published {article['date']}:

HEADLINE: {article['headline']}

BODY:
{body_truncated}

Generate the probe JSON for this article."""

    response = client.messages.create(
        model=MODEL,
        max_tokens=1500,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
    )

    text = response.content[0].text.strip()
    # Clean markdown fencing if present
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        if text.endswith("```"):
            text = text[:-3]

    result = json.loads(text)

    cost = (
        response.usage.input_tokens / 1e6 * 1.00 +
        response.usage.output_tokens / 1e6 * 5.00
    )

    return result, cost, response.usage


def generate_probe_with_retry(article, client, existing_ids, existing_db_ids, source_meta):
    """Generate probe for one article with retry on rate limit. Returns (record, cost) or (None, 0)."""
    for attempt in range(2):
        try:
            result, cost, usage = generate_probe(article, client)
            article_id = result["article_id"]
            if article_id in existing_ids:
                article_id = f"{article_id}_{article['id']}"

            record = {
                "id": article_id,
                "source": article["source"],
                "paywall": source_meta["paywall"],
                "headline": article["headline"],
                "date": article["date"],
                "word_count": article["word_count"],
                "distinctive_facts": result["distinctive_facts"],
                "fact_patterns": result.get("fact_patterns", {}),
                "probes": result["probes"],
                "lexis_db_id": article["id"],
            }

            existing_ids.add(article_id)
            existing_db_ids.add(article["id"])

            facts = list(record.get("fact_patterns", {}).keys())
            print(f"  -> {article_id} | {len(facts)} facts | ${cost:.4f}")
            return record, cost

        except Exception as e:
            if "rate_limit" in str(e).lower() and attempt == 0:
                print(f"  Rate limited, waiting 30s...")
                time.sleep(30)
            else:
                print(f"  ERROR: {e}")
                return None, 0

    return None, 0


def select_articles_for_outlet(source: str, existing_articles: list, existing_db_ids: set, target: int = 20):
    """Select articles for an outlet: keep existing, randomly sample rest from DB."""
    existing_for_source = [a for a in existing_articles if a["source"] == source]
    keep = existing_for_source[:target]

    need = target - len(keep)
    if need <= 0:
        return keep, []

    # Get candidates, excluding already-selected DB IDs
    all_db_ids = existing_db_ids | {a.get("lexis_db_id") for a in keep if a.get("lexis_db_id")}
    candidates = get_candidates(source, all_db_ids, limit=need * 3, min_words=200)

    random.seed(42)
    selected = random.sample(candidates, min(need, len(candidates)))
    return keep, selected


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", type=int, default=5, help="Number of articles per batch")
    parser.add_argument("--source", help="Filter by source name")
    parser.add_argument("--list", action="store_true", help="List candidates without generating")
    parser.add_argument("--select-all", action="store_true",
                        help="Select 20 per outlet, generate probes for new articles")
    parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmation prompt")
    args = parser.parse_args()

    existing_ids, existing_db_ids = load_existing_ids()

    if args.list:
        for source, meta in OUTLETS.items():
            candidates = get_candidates(source, existing_db_ids, limit=10)
            tag = "PAYWALL" if meta["paywall"] else "FREE"
            lang = meta["lang"].upper()
            print(f"\n{source} ({tag}, {lang}) — top candidates:")
            for c in candidates[:10]:
                print(f"  [{c['id']:4d}] {c['word_count']:5d}w | {c['date']} | {c['headline'][:65]}")
        return

    if args.select_all:
        # Load all existing articles
        existing_articles = []
        if ARTICLES_PATH.exists():
            with open(ARTICLES_PATH) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        existing_articles.append(json.loads(line))

        print(f"=== Selecting {TARGET_PER_OUTLET} articles per outlet ===\n")
        print(f"Existing articles: {len(existing_articles)}")

        all_new_articles = []
        for source, meta in OUTLETS.items():
            keep, new_db = select_articles_for_outlet(
                source, existing_articles, existing_db_ids, TARGET_PER_OUTLET
            )
            tag = "PAYWALL" if meta["paywall"] else "FREE"
            print(f"\n{meta['short']} ({tag}): keeping {len(keep)}, need {len(new_db)} new")
            for a in new_db:
                print(f"  + {a['headline'][:70]}... ({a['date']}, {a['word_count']}w)")
            all_new_articles.append((source, meta, new_db))

        total_new = sum(len(new) for _, _, new in all_new_articles)
        print(f"\nTotal new articles to generate probes for: {total_new}")

        if total_new == 0:
            print("Nothing to do!")
            return

        # Confirm before spending API credits
        if not args.yes:
            resp = input(f"\nProceed with generating {total_new} probes? [y/N] ")
            if resp.lower() != "y":
                print("Aborted.")
                return

        client = anthropic.Anthropic()
        total_cost = 0
        added = 0

        for source, meta, new_db in all_new_articles:
            if not new_db:
                continue
            print(f"\n--- {meta['short']} ({len(new_db)} articles) ---")

            for i, article in enumerate(new_db):
                print(f"[{i+1}/{len(new_db)}] {article['headline'][:70]}...")
                record, cost = generate_probe_with_retry(
                    article, client, existing_ids, existing_db_ids, meta
                )
                if record:
                    with open(ARTICLES_PATH, "a") as f:
                        f.write(json.dumps(record) + "\n")
                    added += 1
                    total_cost += cost
                time.sleep(1)

        print(f"\n=== Done. Added {added} articles. Total cost: ${total_cost:.4f} ===")
        return

    # Single source mode
    if not args.source:
        print("Provide --source '<name>' or --select-all")
        print(f"\nAvailable sources:")
        for s, m in OUTLETS.items():
            print(f"  {s} ({m['short']})")
        return

    source_meta = OUTLETS.get(args.source)
    if not source_meta:
        print(f"Unknown source: {args.source}")
        print(f"Available: {list(OUTLETS.keys())}")
        return

    candidates = get_candidates(args.source, existing_db_ids, limit=args.batch * 2)
    batch = candidates[:args.batch]

    if not batch:
        print(f"No candidates for {args.source}")
        return

    tag = "PAYWALL" if source_meta["paywall"] else "FREE"
    print(f"Generating probes for {len(batch)} {args.source} articles ({tag})")
    print()

    client = anthropic.Anthropic()
    total_cost = 0
    added = 0

    for i, article in enumerate(batch):
        print(f"[{i+1}/{len(batch)}] {article['headline'][:70]}...")
        record, cost = generate_probe_with_retry(
            article, client, existing_ids, existing_db_ids, source_meta
        )
        if record:
            with open(ARTICLES_PATH, "a") as f:
                f.write(json.dumps(record) + "\n")
            added += 1
            total_cost += cost
        time.sleep(1)

    print(f"\nDone. Added {added} articles. Cost: ${total_cost:.4f}")


if __name__ == "__main__":
    main()
