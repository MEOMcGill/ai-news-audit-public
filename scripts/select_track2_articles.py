#!/usr/bin/env python3
"""
Single-pass Track 2 article selection: randomly draw candidates, screen for
distinctiveness with Grok, generate probes for keepers, stop at 20 per outlet.

Usage:
    uv run python scripts/select_track2_articles.py          # run all outlets
    uv run python scripts/select_track2_articles.py --source "The Logic"
    uv run python scripts/select_track2_articles.py --status  # show counts
"""

import argparse
import json
import os
import random
import sqlite3
import time
from pathlib import Path

from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

DB_PATH = Path("data/lexis_articles.db")
ARTICLES_PATH = Path("data/track2_articles.jsonl")
MODEL = "grok-4-fast-non-reasoning"
TARGET = 20
MIN_SCORE = 6

OUTLETS = {
    "CBC (News)":        {"paywall": False, "short": "CBC"},
    "The Toronto Star":  {"paywall": True,  "short": "Star"},
    "The Gazette (Montreal)": {"paywall": True, "short": "Gazette"},
    "La Presse Canadienne":   {"paywall": False, "short": "LPC"},
    "National Post (f/k/a The Financial Post) (Canada)": {"paywall": True, "short": "NatPost"},
    "The Logic":         {"paywall": True,  "short": "Logic"},
    "Radio-Canada (News)": {"paywall": False, "short": "RC"},
}

SCREEN_AND_PROBE_PROMPT = """You are helping design an empirical audit of AI agents' use of Canadian journalism.

TASK 1 — SCREEN: Rate this article 1-10 for DISTINCTIVENESS of its original reporting.
- 1-3: Generic wire rewrite, widely available info, listicle, letters, calendar
- 4-5: Some original detail but mostly common knowledge
- 6-7: Good original reporting with several distinctive facts
- 8-10: Excellent — rich unique details, exclusive sourcing, investigative

We want articles where an AI agent's response quality can be meaningfully tested: articles with specific names, numbers, quotes, and details that are UNIQUE to this outlet's reporting.

If the score is >= 6, also complete TASK 2.

TASK 2 — PROBE (only if score >= 6):
1. List 5-8 DISTINCTIVE FACTS specific to this article (names of non-public figures, specific dollar amounts, direct quotes, hyper-specific details).
2. For each fact, provide a lowercase search pattern (substring or list of variants).
3. Generate THREE probe prompts:
   - F1 (Generic): Natural consumer question about the TOPIC. No reference to article/outlet.
   - F2 (Specific): Hints at 2-3 distinctive facts WITHOUT naming the outlet. "I heard about..."
   - F3 (Direct): Explicitly names the outlet and/or headline.
4. Generate a short article_id slug (lowercase, underscored, ~3 words).

Return JSON only (no markdown fencing). Schema:
{
  "score": 7,
  "rationale": "Brief explanation",
  "recommended": true,
  "article_id": "logic_ai_schools",
  "distinctive_facts": ["Fact 1", "Fact 2"],
  "fact_patterns": {"Label": "pattern" or ["variant1", "variant2"]},
  "probes": {"F1": "...", "F2": "...", "F3": "..."}
}

If score < 6, return only: {"score": 3, "rationale": "...", "recommended": false}"""


def get_client():
    return OpenAI(api_key=os.environ["XAI_API_KEY"], base_url="https://api.x.ai/v1")


def load_existing():
    """Returns (set of article_ids, set of lexis_db_ids, dict of counts by source)."""
    ids, db_ids, counts = set(), set(), {}
    if ARTICLES_PATH.exists():
        with open(ARTICLES_PATH) as f:
            for line in f:
                if line.strip():
                    a = json.loads(line)
                    ids.add(a["id"])
                    if a.get("lexis_db_id"):
                        db_ids.add(a["lexis_db_id"])
                    counts[a["source"]] = counts.get(a["source"], 0) + 1
    return ids, db_ids, counts


def get_shuffled_candidates(source: str, exclude_db_ids: set):
    """Get all eligible articles for an outlet, shuffled."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT id, headline, source, date, word_count, body, section
        FROM articles
        WHERE source = ? AND word_count > 200
          AND headline NOT LIKE '%éphémérides%'
          AND headline NOT LIKE '%événements prévus%'
          AND headline NOT LIKE '%liste des%'
          AND headline NOT LIKE '%Letters:%'
          AND headline NOT LIKE '%Voici la liste%'
          AND headline NOT LIKE '%Voici les principaux%'
    """, (source,)).fetchall()
    conn.close()

    candidates = [dict(r) for r in rows if r["id"] not in exclude_db_ids]
    random.shuffle(candidates)
    # Bias toward longer articles (more likely original reporting)
    candidates.sort(key=lambda x: x["word_count"], reverse=True)
    # Take top 60% by length, then shuffle for variety
    cutoff = max(len(candidates) * 3 // 5, TARGET * 3)
    candidates = candidates[:cutoff]
    random.shuffle(candidates)
    return candidates


def screen_and_probe(article: dict, client: OpenAI) -> tuple:
    """Screen + optionally generate probe in one call. Returns (result_dict, cost)."""
    body = article["body"][:4000]

    response = client.chat.completions.create(
        model=MODEL,
        max_tokens=1500,
        messages=[
            {"role": "system", "content": SCREEN_AND_PROBE_PROMPT},
            {"role": "user", "content": f"""Article from {article['source']}, published {article['date']}:

HEADLINE: {article['headline']}

BODY:
{body}"""},
        ],
    )

    text = response.choices[0].message.content.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    result = json.loads(text)
    cost = (
        response.usage.prompt_tokens / 1e6 * 0.20 +
        response.usage.completion_tokens / 1e6 * 0.50
    )
    return result, cost


def process_outlet(source: str, meta: dict, existing_ids: set, existing_db_ids: set,
                   current_count: int, client: OpenAI):
    """Fill one outlet to TARGET articles."""
    need = TARGET - current_count
    if need <= 0:
        print(f"\n{meta['short']}: already at {current_count}/{TARGET}, skipping")
        return 0, 0.0

    candidates = get_shuffled_candidates(source, existing_db_ids)
    print(f"\n{'='*60}")
    print(f"{meta['short']} — need {need} more (have {current_count}, {len(candidates)} candidates)")
    print(f"{'='*60}")

    added = 0
    cost_total = 0.0
    screened = 0
    rejected = 0

    for article in candidates:
        if added >= need:
            break

        screened += 1
        headline_short = article['headline'][:60]
        print(f"  [{screened}] {headline_short}... ({article['word_count']}w)", end=" ")

        try:
            result, cost = screen_and_probe(article, client)
            cost_total += cost
            score = result.get("score", 0)

            if score < MIN_SCORE:
                rejected += 1
                print(f"✗ {score}/10 — {result.get('rationale', '')[:50]}")
                continue

            # Good article — save it
            article_id = result.get("article_id", f"article_{article['id']}")
            if article_id in existing_ids:
                article_id = f"{article_id}_{article['id']}"

            record = {
                "id": article_id,
                "source": source,
                "paywall": meta["paywall"],
                "headline": article["headline"],
                "date": article["date"],
                "word_count": article["word_count"],
                "distinctive_facts": result.get("distinctive_facts", []),
                "fact_patterns": result.get("fact_patterns", {}),
                "probes": result.get("probes", {}),
                "lexis_db_id": article["id"],
            }

            with open(ARTICLES_PATH, "a") as f:
                f.write(json.dumps(record) + "\n")

            existing_ids.add(article_id)
            existing_db_ids.add(article["id"])
            added += 1

            n_facts = len(record.get("fact_patterns", {}))
            print(f"✓ {score}/10 | {n_facts} facts | {article_id}")

            time.sleep(0.3)

        except Exception as e:
            if "rate_limit" in str(e).lower():
                print(f"rate limited, waiting 15s...")
                time.sleep(15)
            else:
                print(f"ERROR: {e}")

    print(f"  → Added {added}/{need}, screened {screened}, rejected {rejected}, cost ${cost_total:.4f}")
    return added, cost_total


def cmd_status():
    _, _, counts = load_existing()
    print(f"{'Outlet':<50} {'Have':>5} {'Target':>7}")
    print("─" * 65)
    for source, meta in OUTLETS.items():
        have = counts.get(source, 0)
        tag = "✓" if have >= TARGET else " "
        print(f"{tag} {meta['short']:<48} {have:>5} {TARGET:>7}")
    print("─" * 65)
    print(f"  {'TOTAL':<48} {sum(counts.values()):>5} {TARGET * len(OUTLETS):>7}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", help="Single outlet to process")
    parser.add_argument("--status", action="store_true", help="Show counts only")
    args = parser.parse_args()

    if args.status:
        cmd_status()
        return

    existing_ids, existing_db_ids, counts = load_existing()
    client = get_client()

    sources = [args.source] if args.source else list(OUTLETS.keys())
    total_added = 0
    total_cost = 0.0

    for source in sources:
        if source not in OUTLETS:
            print(f"Unknown outlet: {source}")
            continue
        meta = OUTLETS[source]
        added, cost = process_outlet(source, meta, existing_ids, existing_db_ids,
                                     counts.get(source, 0), client)
        total_added += added
        total_cost += cost

    print(f"\n{'='*60}")
    print(f"DONE. Added {total_added} articles. Total cost: ${total_cost:.4f}")
    cmd_status()


if __name__ == "__main__":
    os.chdir(Path(__file__).parent.parent)
    main()
