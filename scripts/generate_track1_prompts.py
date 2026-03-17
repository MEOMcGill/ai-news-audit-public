"""
Generate natural consumer questions from daily top stories using local LLM server.

Uses mlx_lm.server (OpenAI-compatible) running on localhost:8899.
Rephrases each story headline into a natural English question a person would ask.

Input:  data/daily_top_stories.jsonl      (default)
        data/daily_top_stories_fr.jsonl   (--lang fr)
Output: data/track1_prompts.jsonl         (default)
        data/track1_prompts_fr.jsonl      (--lang fr)

Usage:
    python scripts/generate_track1_prompts.py           # English stories
    python scripts/generate_track1_prompts.py --lang fr # French stories
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

import requests

MLX_URL = "http://localhost:8899/v1/chat/completions"
MODEL = "mlx-community/Qwen3-30B-A3B-Instruct-2507-4bit"

DATA_DIR = Path(__file__).parent.parent / "data"

# Strip outlet names from headlines
OUTLET_PATTERNS = re.compile(
    r'\|?\s*(Globalnews\.ca|CBC News|CTV News|Global News|Toronto Star|National Post'
    r'|The Globe and Mail|BNN Bloomberg|Financial Post|Maclean\'s'
    r'|The Canadian Press|Yahoo News Canada|La Presse|Le Devoir'
    r'|Radio-Canada|The Score|TSN|Breakfast Television|ET Canada'
    r'|Etalk|blogTO|National Observer|Rebel News Canada'
    r'|The Beaverton|City News|Canadian Dimension)',
    re.IGNORECASE
)


def clean_headline(headline: str) -> str:
    headline = OUTLET_PATTERNS.sub('', headline)
    headline = re.sub(r'https?://\S+', '', headline)
    headline = re.sub(r'»+', '', headline)
    headline = ' '.join(headline.split())
    return headline[:200].strip()


def generate_question(headline: str, date: str, language: str = 'en') -> str:
    """Call local LLM server to rephrase headline into a natural English question."""
    from datetime import datetime
    dt = datetime.strptime(date, "%Y-%m-%d")
    month_year = dt.strftime("%B %Y")  # e.g. "January 2024"

    if language == 'fr':
        lang_instruction = "Écris la question en français. N'utilise pas de mots anglais."
        starters = "'Qu'est-ce que', 'Pourquoi', 'Comment' ou 'Qui'"
        FRENCH_MONTHS = {1:'janvier',2:'février',3:'mars',4:'avril',5:'mai',6:'juin',
                         7:'juillet',8:'août',9:'septembre',10:'octobre',11:'novembre',12:'décembre'}
        month_year = f"{FRENCH_MONTHS[dt.month]} {dt.year}"
    else:
        lang_instruction = "Write the question in English."
        starters = "'What', 'Why', 'How', or 'Who'"

    resp = requests.post(MLX_URL, json={
        "model": MODEL,
        "messages": [
            {"role": "user", "content": (
                f"/no_think\n"
                f"Rewrite this news headline as a short, natural open-ended question "
                f"that a curious person might ask an AI assistant.\n\n"
                f"Rules:\n"
                f"- Start with {starters} — NEVER a yes/no question\n"
                f"- Include a time reference like 'in {month_year}'\n"
                f"- You MAY name well-known public figures (politicians, athletes, etc.) "
                f"and major places — these make the question specific and natural\n"
                f"- Do NOT include minor details like detective names, exact dollar "
                f"amounts, victim names, or case numbers\n"
                f"- Do not mention any news outlet or media organization\n"
                f"- Keep it to one sentence, casual and conversational\n"
                f"- {lang_instruction}\n"
                f"- Output ONLY the question, nothing else\n\n"
                f"Headline: \"{headline}\"\n"
                f"Date: {date}\n\n"
                f"Question:"
            )}
        ],
        "max_tokens": 60,
        "temperature": 0.3,
    }, timeout=15)
    resp.raise_for_status()
    text = resp.json()["choices"][0]["message"]["content"].strip()
    if text.startswith("Question:"):
        text = text[len("Question:"):].strip()
    text = text.strip('"').strip()
    return text


def main():
    parser = argparse.ArgumentParser(description="Generate Track 1 prompts from daily stories")
    parser.add_argument("--lang", choices=["en", "fr"], default="en",
                        help="Story language (default: en)")
    args = parser.parse_args()

    suffix = f"_{args.lang}" if args.lang != "en" else ""
    input_path = DATA_DIR / f"daily_top_stories{suffix}.jsonl"
    output_path = DATA_DIR / f"track1_prompts{suffix}.jsonl"

    print(f"Input:  {input_path}", flush=True)
    print(f"Output: {output_path}", flush=True)

    stories = []
    with open(input_path) as f:
        for line in f:
            line = line.strip()
            if line.startswith("{"):
                stories.append(json.loads(line))
    print(f"Loaded {len(stories)} stories", flush=True)

    # Resume support
    done_ids = set()
    if output_path.exists():
        with open(output_path) as f:
            for line in f:
                try:
                    done_ids.add(json.loads(line)["story_id"])
                except:
                    pass
        print(f"Already done: {len(done_ids)}", flush=True)

    remaining = [s for s in stories if f"{s['date']}_rank{s['rank']}" not in done_ids]
    print(f"Remaining: {len(remaining)}", flush=True)

    if not remaining:
        print("All done!")
        return

    t0 = time.time()
    with open(output_path, "a") as out_f:
        for i, s in enumerate(remaining):
            story_id = f"{s['date']}_rank{s['rank']}"
            headline = clean_headline(s["headline"])

            lang = s.get("language", args.lang)
            try:
                question = generate_question(headline, s["date"], language=lang)
            except Exception as e:
                print(f"  ERROR {story_id}: {e}", flush=True)
                question = f"What happened in Canada on {s['date']} regarding {s['terms']}?"

            record = {
                "story_id": story_id,
                "date": s["date"],
                "rank": s["rank"],
                "language": lang,
                "terms": s["terms"],
                "original_headline": s["headline"][:300],
                "prompt": question,
                "outlets": s["outlets"],
                "n_outlets": s["n_outlets"],
                "engagement": s["engagement"],
                "engagement_pct": s["engagement_pct"],
            }
            out_f.write(json.dumps(record, ensure_ascii=False) + "\n")
            out_f.flush()

            if (i + 1) % 50 == 0 or i == 0:
                elapsed = time.time() - t0
                rate = (i + 1) / elapsed
                eta = (len(remaining) - i - 1) / rate / 60
                print(f"  {i+1}/{len(remaining)} | {rate:.1f}/sec | ETA {eta:.0f}m | {question[:80]}",
                      flush=True)

    elapsed = time.time() - t0
    print(f"\nDone: {len(remaining)} prompts in {elapsed/60:.1f} min", flush=True)


if __name__ == "__main__":
    main()
