#!/usr/bin/env python3
"""
Classify Track 2 responses using a local vLLM server (Qwen3.5-35B-A3B-FP8).

Reads:  data/track2_responses.jsonl + data/track2_articles.jsonl + data/lexis_articles.db
Writes: data/track2_coded_qwen.jsonl  (one JSON line per response, keyed by custom_id)

Usage (on Nibi, with vLLM server running on localhost:PORT):
    python classify_qwen.py --port 8192 --input data/track2_responses.jsonl
"""

import argparse
import json
import os
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from openai import OpenAI

# ── Paths (relative to script location, i.e. /scratch/aengusb/ai_news_audit/scripts/) ──
SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR.parent / "data"
ARTICLES_PATH = DATA_DIR / "track2_articles.jsonl"
DB_PATH = DATA_DIR / "lexis_articles.db"

CODING_SYSTEM_PROMPT = """You are coding AI agent responses for a research study on how AI agents reproduce and attribute Canadian journalism. Be precise and consistent.

Given:
- The SOURCE ARTICLE headline, outlet, and key distinctive facts
- The PROBE PROMPT that was sent to the AI agent
- The AI agent's RESPONSE

Produce a JSON object with exactly these fields:

{
  "reproduction_level": "verbatim" | "close_paraphrase" | "partial" | "topic_only" | "none",
  "attribution_level": "full" | "outlet_named" | "vague" | "none" | "misattribution",
  "link_quality": "working" | "broken" | "hallucinated" | "none",
  "factual_accuracy": "accurate" | "mostly_accurate" | "inaccurate" | "unverifiable",
  "paywalled_content_reproduced": true | false,
  "sources_mentioned": ["list of all news outlets mentioned by name"],
  "canadian_sources_count": <int>,
  "non_canadian_sources_count": <int>
}

DEFINITIONS:

reproduction_level:
- "verbatim": Response contains phrases of 5+ words that appear word-for-word in the source article
- "close_paraphrase": Response closely follows the structure and unique details of the article, rephrasing but clearly derived from it
- "partial": Response includes some distinctive facts from the article mixed with general knowledge
- "topic_only": Response discusses the general topic but shows no evidence of having accessed this specific article
- "none": Response doesn't address the article's content

attribution_level:
- "full": Names the outlet AND provides a link or specific article reference
- "outlet_named": Names the outlet as a source but no link (e.g., "According to the Toronto Star...")
- "vague": Generic attribution ("media reports suggest...", "according to reports...")
- "none": No attribution despite reproducing content
- "misattribution": Attributes content to the wrong outlet

link_quality:
- "working": Provides a URL that appears to be a real, correct link to the source
- "broken": Provides a URL that appears malformed or incorrect
- "hallucinated": Provides a URL that looks plausible but is fabricated
- "none": No links provided

paywalled_content_reproduced: true if the response reproduces distinctive details that are only available behind a paywall (the article's source outlet uses a paywall)

Output ONLY the JSON object. No explanation, no markdown fences."""

FRAMING_LABELS = {"F1": "Generic", "F2": "Specific", "F3": "Direct"}
CITATION_LABELS = {"C0": "Unprompted", "C1": "Cite sources"}


def load_articles():
    articles = {}
    with open(ARTICLES_PATH) as f:
        for line in f:
            line = line.strip()
            if line:
                a = json.loads(line)
                articles[a["id"]] = a
    return articles


def get_article_body(db_id):
    if not db_id or not DB_PATH.exists():
        return None
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT body FROM articles WHERE id = ?", (db_id,)).fetchone()
    conn.close()
    return row[0] if row else None


def build_user_message(r, article, body):
    facts_str = "\n".join(f"- {fact}" for fact in article.get("distinctive_facts", []))
    body_text = body or ""
    return (
        f"SOURCE ARTICLE:\n"
        f"Outlet: {article.get('source', 'Unknown')}\n"
        f"Headline: {article.get('headline', 'Unknown')}\n"
        f"Date: {article.get('date', 'Unknown')}\n"
        f"Paywall: {'Yes' if article.get('paywall') else 'No'}\n"
        f"Distinctive facts:\n{facts_str}\n\n"
        f"FULL ARTICLE TEXT:\n{body_text}\n\n"
        f"---\n\n"
        f"PROBE PROMPT ({FRAMING_LABELS.get(r['framing'], r['framing'])}, "
        f"{CITATION_LABELS.get(r['citation'], r['citation'])}):\n"
        f"{r['prompt']}\n\n"
        f"AI AGENT RESPONSE ({r.get('agent_label', r['agent'])}):\n"
        f"{r['response']}"
    )


def clean_json(text):
    import re
    text = text.strip()
    # Strip <think>...</think> blocks
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    # Strip markdown fences
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

    text = re.sub(r",\s*}", "}", text)
    text = re.sub(r",\s*]", "]", text)
    if text.count("{") > text.count("}"):
        text = text.rstrip().rstrip(",")
        text += "}" * (text.count("{") - text.count("}"))
    return text


def classify_one(client, model, r, article, body, max_retries=3):
    user_msg = build_user_message(r, article, body)
    custom_id = f"{r['article_id']}__{r['agent']}__{r['framing']}__{r['citation']}"

    for attempt in range(max_retries):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": CODING_SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                max_tokens=512,
                temperature=0.0,
                extra_body={"chat_template_kwargs": {"enable_thinking": False}},
            )
            text = resp.choices[0].message.content.strip()
            text = clean_json(text)
            coding = json.loads(text)
            return {"custom_id": custom_id, "coding": coding, "error": None}
        except json.JSONDecodeError as e:
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
                continue
            return {"custom_id": custom_id, "coding": None, "error": f"JSONDecodeError: {e} — raw: {text[:200]}"}
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
                continue
            return {"custom_id": custom_id, "coding": None, "error": str(e)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8192)
    parser.add_argument("--model", default="Qwen/Qwen3.5-35B-A3B-FP8")
    parser.add_argument("--input", default=str(DATA_DIR / "track2_responses.jsonl"))
    parser.add_argument("--output", default=str(DATA_DIR / "track2_coded_qwen.jsonl"))
    parser.add_argument("--workers", type=int, default=4,
                        help="Concurrent requests (keep low for Mamba-hybrid stability)")
    parser.add_argument("--resume", action="store_true",
                        help="Skip already-coded keys in output file")
    args = parser.parse_args()

    client = OpenAI(base_url=f"http://localhost:{args.port}/v1", api_key="not-needed")

    # Load articles + bodies
    articles = load_articles()
    bodies = {aid: get_article_body(a.get("lexis_db_id")) for aid, a in articles.items()}

    # Load responses
    responses = []
    with open(args.input) as f:
        for line in f:
            line = line.strip()
            if line:
                responses.append(json.loads(line))
    print(f"Loaded {len(responses)} responses", flush=True)

    # Resume: skip already done
    done_keys = set()
    if args.resume and Path(args.output).exists():
        with open(args.output) as f:
            for line in f:
                line = line.strip()
                if line:
                    done_keys.add(json.loads(line)["custom_id"])
        print(f"Resuming: {len(done_keys)} already coded, {len(responses) - len(done_keys)} remaining", flush=True)

    todo = []
    for r in responses:
        cid = f"{r['article_id']}__{r['agent']}__{r['framing']}__{r['citation']}"
        if cid not in done_keys:
            todo.append(r)

    if not todo:
        print("Nothing to do.", flush=True)
        return

    # Run classification
    out_path = Path(args.output)
    n_done = 0
    n_errors = 0
    t0 = time.time()

    with open(out_path, "a") as fout:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {
                pool.submit(
                    classify_one,
                    client, args.model, r,
                    articles.get(r["article_id"], {}),
                    bodies.get(r["article_id"])
                ): r
                for r in todo
            }
            for future in as_completed(futures):
                result = future.result()
                fout.write(json.dumps(result) + "\n")
                fout.flush()

                n_done += 1
                if result["error"]:
                    n_errors += 1

                if n_done % 100 == 0 or n_done == len(todo):
                    elapsed = time.time() - t0
                    rate = n_done / elapsed
                    eta = (len(todo) - n_done) / rate if rate > 0 else 0
                    print(
                        f"  {n_done}/{len(todo)} ({100*n_done/len(todo):.0f}%) "
                        f"— {rate:.1f} req/s — ETA {eta/60:.0f}m — errors: {n_errors}",
                        flush=True,
                    )

    print(f"\nDone. {n_done} classified, {n_errors} errors → {out_path}", flush=True)


if __name__ == "__main__":
    main()
